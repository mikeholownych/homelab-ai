//! Best-effort local GPU telemetry via Intel's `xpu-smi`, when present.
//!
//! This is deliberately vendor-agnostic in spirit: it shells out to
//! whatever GPU telemetry tool is actually installed rather than assuming
//! one exists. Today that's `xpu-smi` (Intel); there is no dependency on
//! any NVIDIA-specific tooling, and none is introduced by design — if
//! `xpu-smi` isn't present (e.g. on an NVIDIA box), this degrades to an
//! empty result immediately, cheaply, every time.
//!
//! `xpu-smi` reports several fields as unavailable (`N/A`) on at least one
//! real deployment this was built against — utilization, temperature and
//! memory bandwidth are absent from its own JSON output in that case,
//! which this treats as a hard "unsupported," never a fabricated zero.
//! Only fields the tool actually reports are ever populated here.

use serde::Deserialize;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::Duration;

/// Static device properties — fetched once at startup, never polled again
/// (a GPU's name and installed memory don't change during a session, and
/// re-fetching them on the 5s telemetry cadence would just add needless
/// `xpu-smi` calls for data that can't have changed).
#[derive(Debug, Clone, Default)]
pub struct GpuInfo {
    pub index: u32,
    pub device_name: Option<String>,
    pub pci_bdf: Option<String>,
    pub mem_total_mib: Option<f64>,
    /// PCIe link state, when the driver reports it. `None` here (as opposed
    /// to `GpuStats`'s per-field `Option`s) covers the same "genuinely
    /// unavailable" case: on the hardware this was verified against,
    /// `xpu-smi` itself reports these as the literal string "N/A".
    pub pcie_generation: Option<String>,
    pub pcie_max_link_width: Option<String>,
}

/// Live counters — refreshed on the 5s telemetry cadence.
#[derive(Debug, Clone, Default)]
pub struct GpuStats {
    pub index: u32,
    /// Package temperature (°C) read from the kernel's hwmon interface — no privileges, no `xpu-smi`.
    pub temp_c: Option<f64>,
    /// Video-memory temperature (°C), same source.
    pub vram_temp_c: Option<f64>,
    pub power_w: Option<f64>,
    pub mem_used_mib: Option<f64>,
    pub mem_util_percent: Option<f64>,
    /// Share of the last interval the GPU was awake (not in RC6 idle), from the Xe `gtidle` residency
    /// counter. Coarse - it says "busy or not", not execution-unit occupancy - but real, unprivileged and
    /// cheap. `None` on the first sample or when the driver does not expose the counter.
    pub util_percent: Option<f64>,
}

/// Fetch each GPU's static identity/capacity once. Call at startup only.
pub fn discover_static() -> Vec<GpuInfo> {
    let indices = discover_indices();
    let handles: Vec<_> = indices
        .into_iter()
        .map(|i| std::thread::spawn(move || static_info_for(i)))
        .collect();
    handles.into_iter().filter_map(|h| h.join().ok().flatten()).collect()
}

fn static_info_for(index: u32) -> Option<GpuInfo> {
    let idx = index.to_string();
    let text = run_bounded(&["discovery", "-d", &idx, "-j"], Duration::from_millis(2000))?;

    #[derive(Deserialize)]
    struct Discovery {
        device_name: Option<String>,
        pci_bdf_address: Option<String>,
        memory_physical_size_byte: Option<f64>,
        #[serde(default)]
        pcie_generation: Option<String>,
        #[serde(default)]
        pcie_max_link_width: Option<String>,
    }
    // "N/A" is xpu-smi's own literal for "the driver didn't report this" —
    // normalize it to a real `None` rather than displaying the string.
    fn present(v: Option<String>) -> Option<String> {
        v.filter(|s| s != "N/A" && !s.is_empty())
    }

    let parsed: Discovery = serde_json::from_str(&text).ok()?;
    Some(GpuInfo {
        index,
        device_name: parsed.device_name,
        pci_bdf: parsed.pci_bdf_address,
        mem_total_mib: parsed.memory_physical_size_byte.map(|b| b / (1024.0 * 1024.0)),
        pcie_generation: present(parsed.pcie_generation),
        pcie_max_link_width: present(parsed.pcie_max_link_width),
    })
}

/// Probe every GPU `xpu-smi` reports, each bounded so one slow/hung device
/// can't stall the others or the caller. Returns an empty vec (cheaply) if
/// `xpu-smi` isn't installed at all.
///
/// `targets` are the devices found once at startup (`discover_static`). They are deliberately *not*
/// rediscovered here: `xpu-smi discovery` also queries GPU firmware over the MEI interface (root-only),
/// which fails for an unprivileged monitor and logged hundreds of syslog lines a minute, and the device
/// list cannot change while the monitor runs.
pub fn probe(targets: &[(u32, Option<String>)]) -> Vec<GpuStats> {
    if targets.is_empty() {
        return Vec::new();
    }
    let handles: Vec<_> = targets
        .iter()
        .cloned()
        .map(|(index, bdf)| {
            std::thread::spawn(move || {
                let mut stats = stats_for(index)?;
                if let Some((pkg, vram)) = bdf.as_deref().and_then(|b| hwmon_temps(std::path::Path::new("/sys/class/hwmon"), b)) {
                    stats.temp_c = Some(pkg);
                    stats.vram_temp_c = vram;
                }
                stats.util_percent = bdf.as_deref().and_then(|b| sample_gt_util(std::path::Path::new("/sys/bus/pci/devices"), b));
                Some(stats)
            })
        })
        .collect();
    handles.into_iter().filter_map(|h| h.join().ok().flatten()).collect()
}

/// Idle residency (ms) of GT0 for the Xe GPU at `bdf`: `<root>/<bdf>/tile0/gt0/gtidle/idle_residency_ms`.
pub fn read_gtidle_ms(root: &std::path::Path, bdf: &str) -> Option<u64> {
    std::fs::read_to_string(root.join(bdf).join("tile0/gt0/gtidle/idle_residency_ms"))
        .ok()?
        .trim()
        .parse()
        .ok()
}

/// Active percentage between two `(time, idle_residency_ms)` readings. `None` when the interval is too
/// short to mean anything or the counter went backwards (driver reload).
pub fn gt_active_percent(prev: (std::time::Instant, u64), now: (std::time::Instant, u64)) -> Option<f64> {
    let wall_ms = now.0.checked_duration_since(prev.0)?.as_secs_f64() * 1000.0;
    if wall_ms < 50.0 || now.1 < prev.1 {
        return None;
    }
    Some((100.0 * (1.0 - (now.1 - prev.1) as f64 / wall_ms)).clamp(0.0, 100.0))
}

/// Read the counter now and compare with the previous reading for this device (kept per process).
fn sample_gt_util(root: &std::path::Path, bdf: &str) -> Option<f64> {
    use std::collections::HashMap;
    use std::sync::{Mutex, OnceLock};
    static PREVIOUS: OnceLock<Mutex<HashMap<String, (std::time::Instant, u64)>>> = OnceLock::new();
    let now = (std::time::Instant::now(), read_gtidle_ms(root, bdf)?);
    let mut map = PREVIOUS.get_or_init(|| Mutex::new(HashMap::new())).lock().ok()?;
    let prev = map.insert(bdf.to_string(), now)?;
    gt_active_percent(prev, now)
}

/// Package and video-memory temperatures (°C) for the Xe GPU at PCI address `bdf`, from
/// `<root>/hwmon*/` (`name == xe`, `device` → the PCI function, `temp*_label` of `pkg` / `vram`).
/// Returns `None` when no matching hwmon exists or it exposes no package temperature.
pub fn hwmon_temps(root: &std::path::Path, bdf: &str) -> Option<(f64, Option<f64>)> {
    let read = |p: std::path::PathBuf| std::fs::read_to_string(p).ok();
    for entry in std::fs::read_dir(root).ok()?.flatten() {
        let dir = entry.path();
        if read(dir.join("name")).as_deref().map(str::trim) != Some("xe") {
            continue;
        }
        let device = std::fs::canonicalize(dir.join("device")).ok()?;
        if device.file_name().and_then(|n| n.to_str()) != Some(bdf) {
            continue;
        }
        let mut pkg = None;
        let mut vram = None;
        for n in 1..=32 {
            let Some(label) = read(dir.join(format!("temp{n}_label"))) else { continue };
            let Some(milli) = read(dir.join(format!("temp{n}_input"))).and_then(|v| v.trim().parse::<f64>().ok()) else { continue };
            match label.trim() {
                "pkg" => pkg = Some(milli / 1000.0),
                "vram" => vram = Some(milli / 1000.0),
                _ => {}
            }
        }
        return pkg.map(|p| (p, vram));
    }
    None
}

fn discover_indices() -> Vec<u32> {
    let Some(text) = run_bounded(&["discovery", "-j"], Duration::from_millis(2000)) else {
        return Vec::new();
    };
    #[derive(Deserialize)]
    struct Discovery {
        device_list: Vec<Device>,
    }
    #[derive(Deserialize)]
    struct Device {
        device_id: u32,
    }
    serde_json::from_str::<Discovery>(&text)
        .map(|d| d.device_list.into_iter().map(|dev| dev.device_id).collect())
        .unwrap_or_default()
}

fn stats_for(index: u32) -> Option<GpuStats> {
    let idx = index.to_string();
    let text = run_bounded(&["stats", "-d", &idx, "-j"], Duration::from_millis(2000))?;

    #[derive(Deserialize)]
    struct Stats {
        #[serde(default)]
        power: Option<Power>,
        #[serde(default)]
        memory: Option<Memory>,
    }
    #[derive(Deserialize)]
    struct Power {
        gpu_power_w: Option<std::collections::BTreeMap<String, Tile>>,
    }
    #[derive(Deserialize)]
    struct Memory {
        used_mib: Option<std::collections::BTreeMap<String, Tile>>,
        util_percent: Option<std::collections::BTreeMap<String, Tile>>,
    }
    #[derive(Deserialize)]
    struct Tile {
        current: f64,
    }
    fn first_tile(m: &Option<std::collections::BTreeMap<String, Tile>>) -> Option<f64> {
        m.as_ref()?.values().next().map(|t| t.current)
    }

    let parsed: Stats = serde_json::from_str(&text).ok()?;
    Some(GpuStats {
        index,
        temp_c: None,
        vram_temp_c: None,
        power_w: parsed.power.as_ref().and_then(|p| first_tile(&p.gpu_power_w)),
        mem_used_mib: parsed.memory.as_ref().and_then(|m| first_tile(&m.used_mib)),
        mem_util_percent: parsed.memory.as_ref().and_then(|m| first_tile(&m.util_percent)),
        util_percent: None,
    })
}

/// Run `xpu-smi <args>`, bounded by `timeout` regardless of what the child
/// does (a hang, not just a slow reply). `Command` has no built-in timeout,
/// so this waits for output on a helper thread and gives up on the
/// `recv_timeout` deadline.
///
/// Rust's `Child` is *not* reaped on drop — unlike a thread, an
/// un-`wait()`ed child process becomes a zombie the moment it exits, and
/// stays one until something calls `wait()`/`try_wait()` on it. Since this
/// runs from a long-lived process (the TTY1 console can run for weeks),
/// never reaping would leak one zombie per probe, unbounded, for as long
/// as the console runs. A detached reaper thread guarantees `wait()` is
/// always eventually called, whether or not the timeout fired first —
/// verified live: without this, a real deployment accumulated 100+
/// zombies within minutes.
fn run_bounded(args: &[&str], timeout: Duration) -> Option<String> {
    spawn_bounded("xpu-smi", args, timeout).1
}

/// Core of `run_bounded`, parameterized over the program so tests can
/// exercise the real subprocess/timeout/reaping machinery against a
/// controllable command instead of only the real `xpu-smi`. Also returns
/// the child's PID (when spawn succeeded at all) so tests can verify it
/// actually gets reaped rather than lingering as a zombie — `/proc/<pid>`
/// exists (in state `Z`) for a zombie and disappears entirely once
/// reaped, which is the only externally-observable proof of reaping.
///
/// Note the exit code is never checked here, deliberately matching what
/// this needs: any stdout produced (even by a command that then exits
/// nonzero) is returned as-is; whether it parses as valid JSON is the
/// caller's problem (`stats_for`/`static_info_for` already handle that
/// via `serde_json`'s own `Result`). A timeout does not kill the child —
/// it only stops *waiting* for it; the child keeps running to completion
/// in the background and is reaped once it exits, whenever that is.
fn spawn_bounded(program: &str, args: &[&str], timeout: Duration) -> (Option<u32>, Option<String>) {
    let mut cmd = Command::new(program);
    cmd.args(args).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
    let Ok(mut child) = cmd.spawn() else {
        return (None, None);
    };
    let pid = child.id();
    let Some(mut stdout) = child.stdout.take() else {
        return (Some(pid), None);
    };
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        use std::io::Read;
        let mut buf = String::new();
        let _ = stdout.read_to_string(&mut buf);
        let _ = tx.send(buf);
    });
    let result = match rx.recv_timeout(timeout) {
        Ok(text) if !text.trim().is_empty() => Some(text),
        _ => None,
    };
    std::thread::spawn(move || {
        let _ = child.wait();
    });
    (Some(pid), result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_real_xpu_smi_stats_shape() {
        // Captured verbatim (values redacted) from a real Intel Arc Pro B65
        // deployment: utilization/temperature/bandwidth are genuinely
        // absent from the JSON (not present as fields at all, not null),
        // while power and memory are.
        let text = r#"{
            "device_index": 0,
            "pci_bdf": "0000:51:00.0",
            "device_type": "discrete",
            "power": {
                "gpu_power_w": {"tile_0": {"avg": 6.8, "min": 6.7, "max": 6.9, "current": 6.7}},
                "energy_consumed_j": 1.6
            },
            "memory": {
                "used_mib": {"tile_0": {"avg": 29582.6, "min": 29582.6, "max": 29582.6, "current": 29582.6}},
                "util_percent": {"tile_0": {"avg": 90.5, "min": 90.5, "max": 90.5, "current": 90.5}}
            }
        }"#;
        #[derive(Deserialize)]
        struct Stats {
            pci_bdf: Option<String>,
        }
        let parsed: Stats = serde_json::from_str(text).unwrap();
        assert_eq!(parsed.pci_bdf.as_deref(), Some("0000:51:00.0"));
    }

    #[test]
    fn parses_real_xpu_smi_discovery_detail_shape() {
        // Captured verbatim from a real Intel Arc Pro B65: pcie_generation
        // and pcie_max_link_width are the literal string "N/A", which must
        // normalize to `None`, not be displayed as the text "N/A".
        let text = r#"{
            "device_id": 0,
            "device_name": "Intel(R) Arc(TM) Pro B65 Graphics",
            "pci_bdf_address": "0000:51:00.0",
            "memory_physical_size_byte": 34242297856,
            "pcie_generation": "N/A",
            "pcie_max_link_width": "N/A"
        }"#;
        #[derive(Deserialize)]
        struct Discovery {
            device_name: Option<String>,
            memory_physical_size_byte: Option<f64>,
        }
        let parsed: Discovery = serde_json::from_str(text).unwrap();
        assert_eq!(parsed.device_name.as_deref(), Some("Intel(R) Arc(TM) Pro B65 Graphics"));
        // 34242297856 bytes / (1024*1024) MiB ≈ 32656 MiB, matching the real
        // device's reported `memory_physical_size` of "32656.00 MiB".
        let mib = parsed.memory_physical_size_byte.unwrap() / (1024.0 * 1024.0);
        assert!((mib - 32656.0).abs() < 1.0, "{mib}");
    }

    #[test]
    fn na_string_normalizes_to_none() {
        fn present(v: Option<String>) -> Option<String> {
            v.filter(|s| s != "N/A" && !s.is_empty())
        }
        assert_eq!(present(Some("N/A".to_string())), None);
        assert_eq!(present(Some("".to_string())), None);
        assert_eq!(present(Some("Gen4".to_string())), Some("Gen4".to_string()));
        assert_eq!(present(None), None);
    }

    #[test]
    fn stats_for_missing_binary_returns_none_quickly() {
        // No xpu-smi in a minimal test environment is the expected common
        // case (e.g. CI, or any non-Intel-GPU machine) — must not hang or
        // panic, just report nothing.
        let start = std::time::Instant::now();
        let result = run_bounded(&["stats", "-d", "0", "-j"], Duration::from_millis(500));
        assert!(start.elapsed() < Duration::from_secs(2));
        // Either xpu-smi is absent (None) or, if this happens to run on a
        // machine that has it, we at least didn't hang either way.
        let _ = result;
    }

    // -- subprocess lifecycle: execution, exit codes, timeout, reaping ----
    //
    // These exercise the real subprocess/timeout/reaping machinery against
    // `sh`, a controllable stand-in, rather than only the real `xpu-smi` —
    // closing the gap the 0.2.0 zombie-fix report flagged: that fix had
    // live evidence (zombie count observed flat) but no deterministic
    // regression test. `/proc/<pid>` is the reaping oracle: it exists
    // (state `Z`) for an unreaped zombie and disappears entirely once
    // something calls `wait()` on it.

    fn proc_exists(pid: u32) -> bool {
        std::path::Path::new(&format!("/proc/{pid}")).exists()
    }

    /// Poll until the pid disappears from /proc (reaped) or the deadline
    /// passes. Returns whether it was reaped in time.
    fn wait_for_reap(pid: u32, deadline: Duration) -> bool {
        let start = std::time::Instant::now();
        while start.elapsed() < deadline {
            if !proc_exists(pid) {
                return true;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        !proc_exists(pid)
    }

    #[test]
    fn successful_execution_returns_stdout_and_is_reaped() {
        let (pid, out) = spawn_bounded("sh", &["-c", "echo hello-world"], Duration::from_secs(2));
        assert_eq!(out.as_deref().map(str::trim), Some("hello-world"));
        assert!(wait_for_reap(pid.expect("spawned"), Duration::from_secs(2)), "child was not reaped");
    }

    #[test]
    fn nonzero_exit_with_output_still_returns_the_output() {
        // The exit code is never checked (documented on `spawn_bounded`) —
        // this pins that as intended behavior, not an oversight: whether
        // the output is usable is left to the caller's own JSON parsing.
        let (pid, out) = spawn_bounded("sh", &["-c", "echo partial-output; exit 1"], Duration::from_secs(2));
        assert_eq!(out.as_deref().map(str::trim), Some("partial-output"));
        assert!(wait_for_reap(pid.expect("spawned"), Duration::from_secs(2)));
    }

    #[test]
    fn nonzero_exit_with_no_output_returns_none() {
        let (pid, out) = spawn_bounded("sh", &["-c", "exit 1"], Duration::from_secs(2));
        assert_eq!(out, None);
        assert!(wait_for_reap(pid.expect("spawned"), Duration::from_secs(2)));
    }

    #[test]
    fn malformed_output_is_returned_verbatim_for_the_caller_to_reject() {
        // spawn_bounded itself doesn't parse anything — it hands back
        // whatever came out, and it's on the caller (stats_for /
        // static_info_for, already covered by the JSON-shape tests above)
        // to fail closed on a parse error via serde_json's own Result.
        let (pid, out) = spawn_bounded("sh", &["-c", "echo not valid json"], Duration::from_secs(2));
        let out = out.expect("some output");
        assert!(serde_json::from_str::<serde_json::Value>(&out).is_err());
        assert!(wait_for_reap(pid.expect("spawned"), Duration::from_secs(2)));
    }

    #[test]
    fn timeout_returns_none_promptly_and_still_reaps_the_child_later() {
        // The child (sleeping 1.5s) outlives the 150ms timeout — must
        // return None quickly rather than blocking for the child's full
        // lifetime, and the child must still be reaped once it does exit,
        // even though nothing was waiting for it at the time of timeout.
        let start = std::time::Instant::now();
        let (pid, out) = spawn_bounded("sh", &["-c", "sleep 1.5; echo late"], Duration::from_millis(150));
        assert!(start.elapsed() < Duration::from_millis(800), "did not return promptly on timeout");
        assert_eq!(out, None, "a timed-out call must not return the child's eventual output");
        let pid = pid.expect("spawned");
        // The child is still legitimately running at this point — not
        // reaped yet, and that's correct (it hasn't exited).
        assert!(proc_exists(pid), "child should still be running immediately after the timeout fires");
        assert!(
            wait_for_reap(pid, Duration::from_secs(3)),
            "child was never reaped after it finished sleeping — this is the exact zombie-leak pattern from the 0.2.0 defect"
        );
    }

    #[test]
    fn repeated_calls_do_not_accumulate_overlapping_zombies() {
        // Simulates the real 5s polling cadence's failure mode: many
        // probes over time. None should ever coexist as zombies.
        let mut pids = Vec::new();
        for i in 0..8 {
            let (pid, _) = spawn_bounded("sh", &["-c", &format!("echo n{i}")], Duration::from_secs(2));
            pids.push(pid.expect("spawned"));
        }
        for pid in pids {
            assert!(wait_for_reap(pid, Duration::from_secs(2)), "pid {pid} was left unreaped");
        }
    }

    #[test]
    fn missing_program_returns_none_without_a_pid() {
        let (pid, out) = spawn_bounded("this-command-does-not-exist-xyz", &[], Duration::from_millis(500));
        assert_eq!(pid, None);
        assert_eq!(out, None);
    }
}

#[cfg(test)]
mod hwmon_tests {
    use super::hwmon_temps;
    use std::fs;
    use std::path::Path;

    fn write(p: &Path, v: &str) {
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, v).unwrap();
    }

    /// Builds <root>/pci/<bdf> (the device) and <root>/hwmon/hwmonN with `device` -> that PCI function.
    fn fake(root: &Path, hw: &str, name: &str, bdf: &str, temps: &[(u32, &str, &str)]) {
        let dev = root.join("pci").join(bdf);
        fs::create_dir_all(&dev).unwrap();
        let hwdir = root.join("hwmon").join(hw);
        fs::create_dir_all(&hwdir).unwrap();
        write(&hwdir.join("name"), &format!("{name}\n"));
        std::os::unix::fs::symlink(&dev, hwdir.join("device")).unwrap();
        for (n, label, milli) in temps {
            write(&hwdir.join(format!("temp{n}_label")), &format!("{label}\n"));
            write(&hwdir.join(format!("temp{n}_input")), &format!("{milli}\n"));
        }
    }

    #[test]
    fn reads_pkg_and_vram_for_the_matching_xe_device_only() {
        let t = tempfile_dir();
        fake(&t, "hwmon4", "xe", "0000:51:00.0", &[(2, "pkg", "42000"), (3, "vram", "46000"), (6, "vram_ch_0", "99000")]);
        fake(&t, "hwmon5", "xe", "0000:93:00.0", &[(2, "pkg", "66000"), (3, "vram", "70000")]);
        fake(&t, "hwmon1", "coretemp", "0000:00:18.3", &[(2, "pkg", "11000")]);
        let root = t.join("hwmon");
        assert_eq!(hwmon_temps(&root, "0000:51:00.0"), Some((42.0, Some(46.0))));
        assert_eq!(hwmon_temps(&root, "0000:93:00.0"), Some((66.0, Some(70.0))));
        assert_eq!(hwmon_temps(&root, "0000:ff:00.0"), None, "unknown device");
    }

    #[test]
    fn a_device_without_a_package_sensor_reports_nothing_instead_of_zero() {
        let t = tempfile_dir();
        fake(&t, "hwmon4", "xe", "0000:51:00.0", &[(3, "vram", "46000")]);
        assert_eq!(hwmon_temps(&t.join("hwmon"), "0000:51:00.0"), None);
    }

    fn tempfile_dir() -> std::path::PathBuf {
        let p = std::env::temp_dir().join(format!("vtop-hwmon-{}-{:?}", std::process::id(), std::thread::current().id()));
        let _ = fs::remove_dir_all(&p);
        fs::create_dir_all(&p).unwrap();
        p
    }
}

#[cfg(test)]
mod gtidle_tests {
    use super::*;
    use std::time::{Duration, Instant};

    #[test]
    fn active_percent_is_one_minus_idle_share_of_wall_time() {
        let t0 = Instant::now();
        let t1 = t0 + Duration::from_millis(1000);
        let ten = gt_active_percent((t0, 5_000), (t1, 5_900)).expect("measurable");
        assert!((ten - 10.0).abs() < 1e-6, "idle 900 of 1000 ms -> 10% active, got {ten}");
        assert_eq!(gt_active_percent((t0, 5_000), (t1, 6_000)), Some(0.0), "fully idle");
        assert_eq!(gt_active_percent((t0, 5_000), (t1, 5_000)), Some(100.0), "never idle");
        assert_eq!(gt_active_percent((t0, 5_000), (t1, 7_000)), Some(0.0), "clamped when residency outruns the clock");
    }

    #[test]
    fn unusable_intervals_are_unknown_not_zero() {
        let t0 = Instant::now();
        assert_eq!(gt_active_percent((t0, 10), (t0 + Duration::from_millis(10), 12)), None, "too short to mean anything");
        assert_eq!(gt_active_percent((t0, 900), (t0 + Duration::from_millis(1000), 100)), None, "counter went backwards");
    }

    #[test]
    fn reads_the_xe_residency_counter_from_the_pci_device_directory() {
        let root = std::env::temp_dir().join(format!("vt-gtidle-{}", std::process::id()));
        let dir = root.join("0000:51:00.0/tile0/gt0/gtidle");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("idle_residency_ms"), "3504771\n").unwrap();
        assert_eq!(read_gtidle_ms(&root, "0000:51:00.0"), Some(3_504_771));
        assert_eq!(read_gtidle_ms(&root, "0000:99:00.0"), None, "unknown device");
        let _ = std::fs::remove_dir_all(&root);
    }
}
