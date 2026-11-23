mod app;
mod cli;
mod config;
mod discover;
mod gpu;
mod history;
mod metrics;
mod orchestrator;
mod promparse;
mod source;
mod ui;
mod util;

use anyhow::Result;
use clap::Parser;
use std::time::Duration;

fn main() -> Result<()> {
    // Restore default SIGPIPE behaviour so `vllm-top --once | head` exits
    // quietly instead of panicking when the reader closes the pipe.
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_DFL);
    }

    let cli = cli::Cli::parse();
    discover::set_ignored_ports(&cli.ignore_ports);
    let (settings, defs) = config::resolve(&cli)?;

    if cli.demo {
        // Synthetic fleet unless the user asked for specific endpoints.
        let defs = if defs.len() <= 1 {
            vec![
                config::InstanceDef {
                    name: "local".into(),
                    kind: config::SourceKind::Direct,
                    url: "http://localhost:8000".into(),
                    api_key: None,
                    discovered_via: None,
                    auth: None,
                    confidence: None,
                },
                config::InstanceDef {
                    name: "gpu-node-09".into(),
                    kind: config::SourceKind::Direct,
                    url: "http://10.0.9.21:8000".into(),
                    api_key: None,
                    discovered_via: None,
                    auth: None,
                    confidence: None,
                },
                config::InstanceDef {
                    name: "cluster-prom".into(),
                    kind: config::SourceKind::Prometheus,
                    url: "http://prometheus:9090".into(),
                    api_key: None,
                    discovered_via: None,
                    auth: None,
                    confidence: None,
                },
            ]
        } else {
            defs
        };
        let app = app::demo(&settings, defs)?;
        print!("{}", ui::render_text(&app, 140, 42)?);
        return Ok(());
    }

    if cli.once {
        return once(defs);
    }

    // Make sure a panic mid-frame does not leave the terminal in raw mode.
    let hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let _ = ui::restore();
        hook(info);
    }));

    let mut app = app::App::new(&settings, defs)?;
    let mut terminal = ui::init()?;
    let result = run(&mut terminal, &mut app);
    ui::restore()?;
    result
}

fn run(terminal: &mut ui::Tui, app: &mut app::App) -> Result<()> {
    use crossterm::event::{self, Event};
    const TICK: Duration = Duration::from_millis(100);

    loop {
        terminal.draw(|frame| ui::draw(frame, app))?;

        if event::poll(TICK)? {
            if let Event::Key(key) = event::read()? {
                app.handle_key(key);
            }
        }
        app.tick();

        if app.should_quit {
            return Ok(());
        }
    }
}

/// `--once`: one synchronous scrape per instance, printed as plain text.
fn once(defs: Vec<config::InstanceDef>) -> Result<()> {
    println!(
        "{:<18} {:<10} {:<30} {:<26} {:>5} {:>6} {:>7} {:>12} {:>12} {:>18}",
        "instance", "source", "endpoint", "model", "run", "wait", "kv", "prompt tok",
        "output tok", "ttft p50/p99"
    );
    println!("{}", "-".repeat(150));

    let mut failures = 0usize;
    for def in &defs {
        if let Some(via) = &def.discovered_via {
            let auth = def.auth.as_ref().map(|a| a.label()).unwrap_or("unknown");
            let confidence = def
                .confidence
                .as_ref()
                .map(|c| c.label())
                .unwrap_or("unknown");
            println!("  \u{21b3} discovered via {via}; attribution: {confidence}; auth: {auth}");
        }
        let src = source::build(def.kind, &def.url, def.api_key.as_deref())?;
        match src.fetch() {
            Ok(samples) => {
                let snap = metrics::Snapshot::extract(&samples);
                let model = snap.model.clone().unwrap_or_else(|| "-".into());
                println!(
                    "{:<18} {:<10} {:<30} {:<26} {:>5.0} {:>6.0} {:>6.1}% {:>12} {:>12} {:>9}/{:<8}",
                    util::truncate_for_cli(&def.name, 18),
                    def.kind.label(),
                    util::truncate_for_cli(&util::short_url(&def.url), 30),
                    util::truncate_for_cli(&model, 26),
                    snap.running,
                    snap.waiting,
                    snap.kv_cache_usage * 100.0,
                    util::fmt_si(snap.prompt_tokens),
                    util::fmt_si(snap.generation_tokens),
                    util::fmt_secs(snap.ttft.p50),
                    util::fmt_secs(snap.ttft.p99),
                );
            }
            Err(err) => {
                failures += 1;
                println!(
                    "{:<18} {:<10} {:<30} ERROR: {:#}",
                    util::truncate_for_cli(&def.name, 18),
                    def.kind.label(),
                    util::truncate_for_cli(&util::short_url(&def.url), 30),
                    err
                );
            }
        }
    }

    // GPU telemetry (same path the TUI uses) so operators can verify amdgpu/GTT without a TTY.
    let infos = gpu::discover_static();
    if infos.is_empty() {
        println!("gpu: (none discovered)");
    } else {
        let targets: Vec<_> = infos.iter().map(|i| (i.index, i.pci_bdf.clone())).collect();
        let stats = gpu::probe(&targets);
        for info in &infos {
            let live = stats.iter().find(|s| s.index == info.index);
            let name = info.device_name.as_deref().unwrap_or("GPU");
            let bdf = info.pci_bdf.as_deref().unwrap_or("-");
            let mem = match (
                live.and_then(|s| s.mem_used_mib),
                live.and_then(|s| s.mem_util_percent),
                info.mem_total_mib,
            ) {
                (Some(used), Some(pct), Some(total)) => {
                    format!("{used:.0}/{total:.0} MiB ({pct:.1}%)")
                }
                (Some(used), _, Some(total)) => format!("{used:.0}/{total:.0} MiB"),
                (Some(used), Some(pct), None) => format!("{used:.0} MiB ({pct:.1}%)"),
                (None, _, Some(total)) => format!("total {total:.0} MiB"),
                _ => "n/a".into(),
            };
            let power = live
                .and_then(|s| s.power_w)
                .map(|w| format!("{w:.1} W"))
                .unwrap_or_else(|| "n/a".into());
            let util = live
                .and_then(|s| s.util_percent)
                .map(|u| format!("{u:.0}%"))
                .unwrap_or_else(|| "n/a".into());
            let temp = live
                .and_then(|s| s.temp_c)
                .map(|t| format!("{t:.0}°C"))
                .unwrap_or_else(|| "n/a".into());
            println!(
                "gpu{index} {name} ({bdf})  mem {mem}  power {power}  util {util}  temp {temp}",
                index = info.index,
            );
        }
    }

    if failures > 0 {
        anyhow::bail!("{failures} instance(s) failed");
    }
    Ok(())
}
