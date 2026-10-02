//! btop-style rendering: a header of instance tabs, a grid of bordered
//! panels (graphs, gauges, tables) and a keybind footer.

use crate::app::{App, BoxVisibility, Health, SortKey, View};
use crate::util;
use anyhow::Result;
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use ratatui::backend::{CrosstermBackend, TestBackend};
use ratatui::layout::{Alignment, Constraint, Layout, Position, Rect};
use ratatui::style::{Modifier, Stylize, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, BorderType, Clear, Paragraph, Row, Table};
use ratatui::{Frame, Terminal};
use std::io::{self, Stdout};

pub type Tui = Terminal<CrosstermBackend<Stdout>>;

// btop-ish palette
const ACCENT: ratatui::style::Color = ratatui::style::Color::Cyan;
const GOOD: ratatui::style::Color = ratatui::style::Color::Green;
const WARN: ratatui::style::Color = ratatui::style::Color::Yellow;
const BAD: ratatui::style::Color = ratatui::style::Color::Red;
const DIM: ratatui::style::Color = ratatui::style::Color::DarkGray;
const GRAPH_2: ratatui::style::Color = ratatui::style::Color::Blue;
/// btop's own `meter_bg` default-theme value (`#40`, grayscale) — the
/// unfilled portion of a gradient meter.
const METER_BG: ratatui::style::Color = ratatui::style::Color::Rgb(0x40, 0x40, 0x40);

const MIN_WIDTH: u16 = 90;
const MIN_HEIGHT: u16 = 35;

pub fn init() -> Result<Tui> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let mut terminal = Terminal::new(CrosstermBackend::new(stdout))?;
    terminal.clear()?;
    Ok(terminal)
}

pub fn restore() -> Result<()> {
    if crossterm::terminal::is_raw_mode_enabled()? {
        disable_raw_mode()?;
    }
    let _ = execute!(io::stdout(), LeaveAlternateScreen);
    Ok(())
}

// ---------------------------------------------------------------------------
// frame
// ---------------------------------------------------------------------------

pub fn draw(frame: &mut Frame, app: &App) {
    let area = frame.area();

    if area.width < MIN_WIDTH || area.height < MIN_HEIGHT {
        draw_too_small(frame, area);
        return;
    }

    let sizes = compute_layout(area.height, area.width, app.runtimes.len(), app.boxes);
    let rows = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(sizes.overview),
        Constraint::Length(sizes.graphs),
        Constraint::Length(sizes.detail),
        Constraint::Length(sizes.instances),
        Constraint::Length(sizes.requests),
        Constraint::Length(1),
    ])
    .split(area);

    draw_header(frame, app, rows[0]);
    if sizes.overview > 0 {
        draw_overview(frame, app, rows[1]);
    }
    if sizes.graphs > 0 {
        draw_main(frame, app, rows[2]);
    }
    if sizes.detail > 0 {
        draw_detail_row(frame, app, rows[3]);
    }
    if sizes.instances > 0 {
        draw_instances(frame, app, rows[4]);
    }
    if sizes.requests > 0 {
        draw_requests(frame, app, rows[5]);
    }
    draw_footer(frame, app, rows[6]);

    if app.show_help {
        draw_help(frame, area);
    }
}

/// Row heights for the vertical stack, computed fresh every frame from the
/// actual terminal size — this is what makes resizing "just work" rather
/// than needing a special-case handler, and what stops graphs/detail
/// panels from either clipping on a small terminal or turning into mostly
/// empty space on a very large one (verified against a real TTY1 at
/// 240×67: the previous fixed/`Min()`-based layout let the latency panel
/// balloon to ~37 rows of near-empty space).
struct LayoutSizes {
    overview: u16,
    graphs: u16,
    detail: u16,
    instances: u16,
    requests: u16,
}

fn compute_layout(total_height: u16, total_width: u16, instance_count: usize, vis: BoxVisibility) -> LayoutSizes {
    const HEADER_FOOTER: u16 = 2;
    const REQUESTS: u16 = 8;
    // A panel needs at least this many rows to render as more than a bare
    // border (1 content line + top/bottom border). Below this, ratatui's
    // own constraint solver shrinks things further rather than panicking —
    // this floor just keeps the *common* cases from getting cramped.
    const FLOOR: u16 = 3;
    // The detail row's content (service/GPU/session) is short and static —
    // a handful of text lines regardless of terminal size — so it's capped
    // rather than given a share of extra height it has nothing to show in.
    // The graphs row is the opposite: its multi-row btop-style graphs
    // (`gradient_graph_rows`) render meaningfully at *any* height, so
    // rather than also capping it and leaving the remainder as a blank
    // margin (the previous behavior — verified live: 5 dead rows at the
    // real TTY1's 240×67), it takes 100% of whatever height detail didn't
    // use. `graphs + detail` therefore always equals `flexible` exactly,
    // so the footer lands on the terminal's actual last row at any size.
    const DETAIL_CAP: u16 = 22;

    // The KPI overview strip needs real horizontal room for its tiles;
    // below this width it's dropped entirely rather than wrapped or
    // truncated into illegibility. Its information isn't lost — the same
    // numbers appear in the graphs/detail panels below. A hidden box
    // (`BoxVisibility`, toggled with F1-F5) contributes 0 to `fixed`
    // exactly like a too-narrow overview does, so its space becomes part
    // of `flexible` and flows to the graphs row automatically — the same
    // "no dead margin" mechanism as above, not a separate code path.
    let overview = if vis.overview && total_width >= 100 { 3 } else { 0 };
    let instances = if vis.instances { (instance_count as u16 + 3).clamp(5, 14) } else { 0 };
    let requests = if vis.requests { REQUESTS } else { 0 };

    let fixed = HEADER_FOOTER + overview + instances + requests;
    let flexible = total_height.saturating_sub(fixed);

    // If graphs is hidden, detail is the last one standing in this pair —
    // it should absorb all of `flexible` rather than staying capped and
    // leaving the rest as dead space again. (If both are hidden, that
    // leftover genuinely has nowhere left to go; an acceptable edge case
    // for a state the user has to deliberately create by hiding two boxes
    // at once.)
    let detail = match (vis.detail, vis.graphs) {
        (true, true) => (flexible / 2).clamp(FLOOR, DETAIL_CAP),
        (true, false) => flexible.max(FLOOR),
        (false, _) => 0,
    };
    let graphs = if vis.graphs { flexible.saturating_sub(detail).max(FLOOR) } else { 0 };

    LayoutSizes { overview, graphs, detail, instances, requests }
}

/// Verified directly against a live TTY1 console: this is the *only*
/// environment signal checked, deliberately — `TERM=linux` is set by the
/// kernel's own virtual-terminal login/service setup, not guessed at from
/// a broader heuristic. Confirmed by reading that console's actual screen
/// buffer (`/dev/vcsa`) while vllm-top was running on it: color is capped
/// at a handful of palette slots (1 byte of attribute per character
/// cell — the classic VGA text-mode model, independent of what escape
/// codes are sent to it), and the default console font has no Braille
/// glyphs and no rounded box-drawing corners — those code points collapse
/// unpredictably to a `space`/`│`/`■`/`+` substitute depending on the
/// exact pattern requested. None of that is fixable by emitting different
/// escape sequences; it's what the kernel's VT layer does. SSH/tmux/GUI
/// terminals are unaffected and keep the full truecolor+Braille rendering.
fn is_raw_console() -> bool {
    std::env::var("TERM").map(|t| t == "linux").unwrap_or(false)
}

/// Pure so tests can exercise both branches deterministically without
/// depending on the process's actual `TERM` — see [`is_raw_console`].
fn border_type_for(console_safe: bool) -> BorderType {
    if console_safe {
        // Verified: ┌┐└┘─│ (`BorderType::Plain`'s glyphs) map to the
        // console font's native CP437 box-drawing slots and render
        // correctly. Rounded's corners (╭╮╰╯) do not exist in that font
        // and all four collapse to a generic '+' there.
        BorderType::Plain
    } else {
        BorderType::Rounded
    }
}

fn panel(title: &str) -> Block<'static> {
    Block::bordered()
        .border_type(border_type_for(is_raw_console()))
        .border_style(Style::default().fg(DIM))
        .title(Span::styled(
            format!(" {title} "),
            Style::default().fg(ACCENT).add_modifier(ratatui::style::Modifier::BOLD),
        ))
}

fn draw_too_small(frame: &mut Frame, area: Rect) {
    let text = Text::from(vec![
        Line::from(""),
        Line::from(Span::styled(
            " vllm-top ",
            Style::default().fg(ratatui::style::Color::Black)
                .bg(ACCENT)
                .add_modifier(ratatui::style::Modifier::BOLD),
        )),
        Line::from(""),
        Line::from(format!(
            "terminal too small: {}x{} (need at least {}x{})",
            area.width, area.height, MIN_WIDTH, MIN_HEIGHT
        )),
        Line::from(""),
        Line::from("press q to quit"),
    ]);
    frame.render_widget(
        Paragraph::new(text).alignment(Alignment::Center),
        area,
    );
}

// ---------------------------------------------------------------------------
// header / footer
// ---------------------------------------------------------------------------

fn health_color(h: Health) -> ratatui::style::Color {
    match h {
        Health::Ok => GOOD,
        Health::Stale => WARN,
        Health::Down => BAD,
    }
}

fn health_symbol(h: Health) -> &'static str {
    match h {
        Health::Ok => "●",
        Health::Stale => "◐",
        Health::Down => "✕",
    }
}

struct ServiceHealthSummary {
    worst: Health,
    ok: usize,
    stale: usize,
    down: usize,
    total: usize,
}

impl ServiceHealthSummary {
    fn label(&self) -> String {
        if self.total <= 1 {
            match self.worst {
                Health::Ok => "ok".to_string(),
                Health::Stale => "stale".to_string(),
                Health::Down => "down".to_string(),
            }
        } else {
            format!("{}/{} ok", self.ok, self.total)
        }
    }
}

/// The worst health across every monitored instance, plus the counts
/// behind it — used by the header's "SVC" indicator so one dead instance
/// among several is visible at a glance without switching tabs.
fn overall_health(app: &App) -> ServiceHealthSummary {
    let (mut ok, mut stale, mut down) = (0, 0, 0);
    for rt in &app.runtimes {
        match rt.health(app.poll) {
            Health::Ok => ok += 1,
            Health::Stale => stale += 1,
            Health::Down => down += 1,
        }
    }
    let worst = if down > 0 {
        Health::Down
    } else if stale > 0 {
        Health::Stale
    } else {
        Health::Ok
    };
    ServiceHealthSummary { worst, ok, stale, down, total: app.runtimes.len() }
}

fn draw_header(frame: &mut Frame, app: &App, area: Rect) {
    let now = chrono_free_clock();
    let right = format!(
        " {} │ poll {} │ {} ",
        now,
        util::fmt_interval(app.poll),
        if app.paused { "⏸ paused" } else { "▶ live" },
    );
    let right_len = right.chars().count() as u16 + 2;
    let cols = Layout::horizontal([Constraint::Min(0), Constraint::Length(right_len)]).split(area);

    let mut spans: Vec<Span> = vec![Span::styled(
        " vllm-top ",
        Style::default()
            .fg(ratatui::style::Color::Black)
            .bg(ACCENT)
            .add_modifier(ratatui::style::Modifier::BOLD),
    )];
    spans.push(Span::raw(" "));

    // The monitor and the service it watches are two different things
    // being reported on here — a perfectly healthy vllm-top correctly
    // showing a down vLLM must never look like vllm-top itself is broken.
    // "MON" reflects vllm-top's own render/poll loop (if this frame is
    // drawing at all, it's alive; "paused" is the one other state it can
    // honestly report); "SVC" reflects the monitored instance(s).
    let mon_label = if app.paused { "MON paused" } else { "MON ok" };
    let mon_color = if app.paused { WARN } else { GOOD };
    spans.push(Span::styled(
        format!(" {mon_label} "),
        Style::default().fg(ratatui::style::Color::Black).bg(mon_color),
    ));
    spans.push(Span::raw(" "));

    let svc = overall_health(app);
    spans.push(Span::styled(
        format!(" SVC {} ", svc.label()),
        Style::default().fg(ratatui::style::Color::Black).bg(health_color(svc.worst)),
    ));
    spans.push(Span::raw(" "));

    // aggregate tab
    let agg_selected = app.view == View::Aggregate;
    let agg_style = if agg_selected {
        Style::default()
            .fg(ratatui::style::Color::Black)
            .bg(ACCENT)
            .add_modifier(ratatui::style::Modifier::BOLD)
    } else {
        Style::default().fg(DIM)
    };
    spans.push(Span::styled(" all ", agg_style));
    spans.push(Span::raw(" "));

    for (i, rt) in app.runtimes.iter().enumerate() {
        let h = rt.health(app.poll);
        let selected = app.view == View::Instance(i);
        let name_style = if selected {
            Style::default()
                .fg(ratatui::style::Color::Black)
                .bg(ACCENT)
                .add_modifier(ratatui::style::Modifier::BOLD)
        } else {
            Style::default().fg(ratatui::style::Color::Gray)
        };
        spans.push(Span::styled(
            format!(" {}:{} ", i + 1, rt.def.name),
            name_style,
        ));
        spans.push(Span::styled(
            health_symbol(h),
            Style::default().fg(health_color(h)),
        ));
        spans.push(Span::raw(" "));
    }

    if let Some(err) = app.error() {
        spans.push(Span::styled(
            format!(" {} ", truncate(&err, 60)),
            Style::default()
                .fg(ratatui::style::Color::Black)
                .bg(BAD),
        ));
    }

    frame.render_widget(Paragraph::new(Line::from(spans)), cols[0]);
    frame.render_widget(
        Paragraph::new(right).alignment(Alignment::Right),
        cols[1],
    );
}

fn draw_footer(frame: &mut Frame, app: &App, area: Rect) {
    let mut spans = vec![Span::styled(
        format!(" vllm-top {} ", env!("CARGO_PKG_VERSION")),
        Style::default().fg(ratatui::style::Color::Black).bg(DIM),
    )];

    // While typing a filter, every ordinary keybind below is inert (see
    // `App::handle_key`) — showing them here instead of what's actually
    // active would be actively misleading, so this replaces the whole
    // hint bar rather than just adding to it.
    if app.filter_editing {
        spans.push(Span::raw(" "));
        spans.push(Span::styled(
            format!("filtering: {}_", app.filter),
            Style::default().fg(ACCENT).add_modifier(ratatui::style::Modifier::BOLD),
        ));
        spans.push(Span::styled("  enter confirm  esc cancel", Style::default().fg(DIM)));
        frame.render_widget(Paragraph::new(Line::from(spans)), area);
        return;
    }

    let keys = [
        ("q", "quit"),
        ("tab", "cycle"),
        ("1-9/a", "instance"),
        ("p", "pause"),
        ("r", "refresh"),
        ("+/-", "interval"),
        ("F1-5", "boxes"),
        ("s/S", "sort"),
        ("/", "filter"),
        ("?", "help"),
    ];
    for (k, label) in keys {
        spans.push(Span::raw(" "));
        spans.push(Span::styled(
            k,
            Style::default().fg(ACCENT).add_modifier(ratatui::style::Modifier::BOLD),
        ));
        spans.push(Span::styled(format!(" {label}"), Style::default().fg(DIM)));
    }

    let right = format!(
        " {} │ {} polls │ view: {} ",
        if app.paused { "PAUSED" } else { "live" },
        app.polls,
        app.title(),
    );
    let right_len = right.chars().count() as u16;
    let cols = Layout::horizontal([Constraint::Min(0), Constraint::Length(right_len)]).split(area);
    frame.render_widget(Paragraph::new(Line::from(spans)), cols[0]);
    frame.render_widget(Paragraph::new(right).alignment(Alignment::Right), cols[1]);
}

// ---------------------------------------------------------------------------
// overview strip: at-a-glance KPIs, wide terminals only (see compute_layout)
// ---------------------------------------------------------------------------

fn kpi(label: &str, value: String, color: ratatui::style::Color) -> Vec<Span<'static>> {
    vec![
        Span::styled(format!("{label} "), Style::default().fg(DIM)),
        Span::styled(value, Style::default().fg(color).add_modifier(Modifier::BOLD)),
        Span::raw("   "),
    ]
}

fn draw_overview(frame: &mut Frame, app: &App, area: Rect) {
    let d = app.derived();
    let snap = app.snapshot();

    let mut spans = Vec::new();
    let model = snap
        .and_then(|s| s.model.clone())
        .unwrap_or_else(|| "waiting for first sample…".to_string());
    spans.extend(kpi("MODEL", truncate(&model, 40), ratatui::style::Color::White));
    spans.extend(kpi("RUN", format!("{:.0}", d.running), GOOD));
    spans.extend(kpi("WAIT", format!("{:.0}", d.waiting), WARN));
    spans.extend(kpi("GEN", format!("{}/s", util::fmt_si(d.gen_tps)), GOOD));
    spans.extend(kpi("PROMPT", format!("{}/s", util::fmt_si(d.prompt_tps)), GRAPH_2));
    spans.extend(kpi("KV", util::fmt_pct(d.kv), gauge_color(d.kv)));
    spans.extend(kpi("TTFT p99", util::fmt_secs(d.ttft_p99), color_for_p99(d.ttft_p99)));
    if !app.gpu.is_empty() {
        let total_power: f64 = app.gpu.iter().filter_map(|g| g.power_w).sum();
        if total_power > 0.0 {
            spans.extend(kpi("GPU PWR", format!("{total_power:.0}W"), ACCENT));
        }
    }

    frame.render_widget(
        Paragraph::new(Line::from(spans)).block(panel(" overview ")),
        area,
    );
}

// ---------------------------------------------------------------------------
// main row: throughput | kv cache + latency
// ---------------------------------------------------------------------------

fn draw_main(frame: &mut Frame, app: &App, area: Rect) {
    let cols = Layout::horizontal([Constraint::Percentage(46), Constraint::Percentage(54)])
        .split(area);
    draw_throughput(frame, app, cols[0]);
    let right = Layout::vertical([Constraint::Length(7), Constraint::Min(7)]).split(cols[1]);
    draw_kv(frame, app, right[0]);
    draw_latency(frame, app, right[1]);
}

/// The throughput panel's headline graph — deliberately not a ratatui
/// `Chart`/`Dataset` (that renders as a few thin braille lines lost in a
/// sea of blank cells, which is a large part of why the previous rendering
/// still read as generic rather than btop-like). Each series instead gets
/// its own [`gradient_graph_rows`] block — the same real btop
/// `Graph::_create` multi-row technique used everywhere else in this file
/// — so the panel's full height is actually filled with graph, not axis
/// labels and empty space around a few pixel-thin lines.
fn draw_throughput(frame: &mut Frame, app: &App, area: Rect) {
    let hist = app.histories();
    let title = format!(" throughput · {} ", app.title());
    let block = panel(&title);
    let inner = block.inner(area);
    frame.render_widget(block, area);

    if hist.gen_tps.is_empty() {
        frame.render_widget(
            Paragraph::new(centered_note("collecting samples…")).alignment(Alignment::Center),
            inner,
        );
        return;
    }

    let gen = hist.gen_tps.values();
    let prompt = hist.prompt_tps.values();

    let rows = Layout::vertical([
        Constraint::Length(1),
        Constraint::Min(3),
        Constraint::Length(1),
        Constraint::Min(3),
    ])
    .split(inner);

    draw_throughput_series(frame, "gen tok/s", GOOD, &gen, rows[0], rows[1]);
    draw_throughput_series(frame, "prompt tok/s", GRAPH_2, &prompt, rows[2], rows[3]);
}

fn draw_throughput_series(
    frame: &mut Frame,
    label: &str,
    color: ratatui::style::Color,
    values: &[f64],
    header_area: Rect,
    graph_area: Rect,
) {
    let current = values.last().copied().unwrap_or(0.0);
    let peak = values.iter().cloned().fold(0.0_f64, f64::max);
    frame.render_widget(
        Line::from(vec![
            Span::styled(
                format!("{label} "),
                Style::default().fg(color).add_modifier(Modifier::BOLD),
            ),
            Span::styled(util::fmt_si(current), Style::default().fg(ratatui::style::Color::White)),
            Span::styled("  peak ", Style::default().fg(DIM)),
            Span::styled(util::fmt_si(peak), Style::default().fg(DIM)),
        ]),
        header_area,
    );
    let lines = gradient_graph_rows(values, graph_area.width as usize, graph_area.height as usize);
    frame.render_widget(Paragraph::new(lines), graph_area);
}

fn draw_kv(frame: &mut Frame, app: &App, area: Rect) {
    let d = app.derived();
    let snap = app.snapshot();
    let block = panel(" kv cache ");
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let rows = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(1),
        Constraint::Min(3),
    ])
    .split(inner);

    frame.render_widget(
        Paragraph::new(gradient_meter("kv cache", d.kv, rows[0].width)),
        rows[0],
    );
    frame.render_widget(
        Paragraph::new(gradient_meter("prefix hit", d.prefix_hit_rate.unwrap_or(0.0), rows[1].width)),
        rows[1],
    );

    let (cached, model) = match snap {
        Some(s) => (
            s.cached_ratio()
                .map(util::fmt_pct)
                .unwrap_or_else(|| "-".into()),
            s.model.clone().unwrap_or_else(|| "unknown model".into()),
        ),
        None => ("-".into(), "waiting for first sample…".into()),
    };
    let prefix_rate = d
        .prefix_hit_rate
        .map(util::fmt_pct)
        .unwrap_or_else(|| "-".into());

    let lines = vec![
        Line::from(vec![
            Span::styled("model    ", Style::default().fg(DIM)),
            Span::styled(
                truncate(&model, 46),
                Style::default().fg(ratatui::style::Color::White),
            ),
        ]),
        Line::from(vec![
            Span::styled("cached   ", Style::default().fg(DIM)),
            Span::styled(
                format!("{cached} of prompt tokens"),
                Style::default().fg(ratatui::style::Color::White),
            ),
        ]),
        Line::from(vec![
            Span::styled("hit rate ", Style::default().fg(DIM)),
            Span::styled(prefix_rate, Style::default().fg(ratatui::style::Color::White)),
        ]),
    ];
    frame.render_widget(Paragraph::new(lines), rows[2]);
}

/// Smooth green → amber → red interpolation, the core of every gradient
/// meter/sparkline below — btop's signature look is a continuous
/// per-value color, not a handful of discrete buckets. `t` is clamped to
/// `[0, 1]`. Dispatches to a raw-console-safe discrete version when
/// running on the physical TTY1 (see [`is_raw_console`]) — continuous
/// `Rgb` there gets silently crushed by the kernel's VT layer down to
/// whichever of ~16 palette slots is nearest, producing inconsistent,
/// jumpy banding rather than a clean gradient; explicit named ANSI colors
/// pick deterministic, correctly-ordered steps instead.
fn gradient_color(t: f64) -> ratatui::style::Color {
    gradient_color_impl(t, is_raw_console())
}

/// Pure implementation so both branches are directly, deterministically
/// testable without depending on the process's actual `TERM`.
fn gradient_color_impl(t: f64, console_safe: bool) -> ratatui::style::Color {
    let t = t.clamp(0.0, 1.0);
    if console_safe {
        // Four named ANSI colors — guaranteed to map to distinct palette
        // slots on any terminal, console included, unlike an arbitrary
        // Rgb value that the console quantizes unpredictably.
        if t < 0.34 {
            ratatui::style::Color::Green
        } else if t < 0.55 {
            ratatui::style::Color::Yellow
        } else if t < 0.8 {
            ratatui::style::Color::LightRed
        } else {
            ratatui::style::Color::Red
        }
    } else {
        // btop's own default-theme stops (src/btop_theme.cpp: cpu_start
        // #77ca9b, cpu_mid #cbc06c, cpu_end #dc4c4c) — not a guessed
        // approximation. Softer/more muted than a typical Material-style
        // traffic-light gradient, which is exactly the btop look being
        // matched here.
        const STOPS: [(f64, u8, u8, u8); 3] = [
            (0.0, 0x77, 0xca, 0x9b), // cpu_start
            (0.5, 0xcb, 0xc0, 0x6c), // cpu_mid
            (1.0, 0xdc, 0x4c, 0x4c), // cpu_end
        ];
        let (lo, hi) = if t <= STOPS[1].0 { (STOPS[0], STOPS[1]) } else { (STOPS[1], STOPS[2]) };
        let (t0, r0, g0, b0) = lo;
        let (t1, r1, g1, b1) = hi;
        let frac = ((t - t0) / (t1 - t0).max(1e-9)).clamp(0.0, 1.0);
        let lerp = |a: u8, b: u8| (a as f64 + (b as f64 - a as f64) * frac).round() as u8;
        ratatui::style::Color::Rgb(lerp(r0, r1), lerp(g0, g1), lerp(b0, b1))
    }
}

/// Same 3-bucket semantics existing callers rely on (kv%/kv-cache-table
/// coloring etc.), now backed by the smooth gradient instead of three
/// hard steps — every caller gets continuous coloring with no call-site
/// changes.
fn gauge_color(r: f64) -> ratatui::style::Color {
    gradient_color(r)
}

/// btop's actual meter glyph (`src/btop_draw.cpp`: `const string meter =
/// "■";`) — a solid-square *foreground* glyph repeated across the bar,
/// not a background-colored blank cell. That distinction is the biggest
/// single reason an earlier version of this looked "blocky": a
/// background-filled space renders as an edge-to-edge slab in every
/// font, where a repeated glyph reads as a row of discrete meter
/// segments, which is what actually looks like btop.
const METER_GLYPH: &str = "■";

/// A btop-style meter bar: label + percentage as plain text, then a row
/// of `METER_GLYPH` characters — filled ones colored by a fixed
/// green→amber→red gradient across the bar's full width (only the
/// *filled* portion up to `ratio` is revealed, so a half-full bar shows
/// just the green-to-amber half, never a solid green bar re-colored by
/// its overall level), unfilled ones colored with the dim `METER_BG`
/// tone — exactly btop's `Meter::operator()`, which colors both filled
/// and unfilled cells with the *same* glyph and only varies the color.
fn gradient_meter(label: &str, ratio: f64, width: u16) -> Line<'static> {
    let r = ratio.clamp(0.0, 1.0);
    let prefix = format!("{} {} ", label, util::fmt_pct(r));
    let prefix_len = prefix.chars().count();
    let bar_width = (width as usize).saturating_sub(prefix_len).max(1);
    let filled = ((r * bar_width as f64).round() as usize).min(bar_width);

    let mut spans = Vec::with_capacity(bar_width + 1);
    spans.push(Span::styled(prefix, Style::default().fg(ratatui::style::Color::Gray)));
    for col in 0..bar_width {
        let color = if col < filled {
            gradient_color(col as f64 / (bar_width.saturating_sub(1)).max(1) as f64)
        } else {
            METER_BG
        };
        spans.push(Span::styled(METER_GLYPH, Style::default().fg(color)));
    }
    Line::from(spans)
}

/// Scale a series for a [`Sparkline`], zoomed onto the observed range so
/// ordinary variation stays visible instead of pinning every bar at full
/// height. Returns (values, max).
fn spark(data: &[f64]) -> (Vec<u64>, u64) {
    const RES: f64 = 1_000.0;
    if data.is_empty() {
        return (Vec::new(), 1);
    }
    let min = data.iter().cloned().fold(f64::INFINITY, f64::min);
    let max = data.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let span = (max - min).max(max.abs() * 0.05).max(1e-9);
    let floor = min - span * 0.15;
    let values = data
        .iter()
        .map(|v| (((v - floor) * (RES / span)).clamp(0.0, RES)) as u64)
        .collect();
    (values, RES as u64)
}

/// btop's exact `braille_up` lookup table (`src/btop_draw.cpp`), indexed
/// `[left][right]` where each of `left`/`right` is a 0-4 quantized
/// height for the previous/current sample — each braille character packs
/// 4 vertical sub-positions per half, versus one flat block-height level
/// per character. This (not the gradient coloring) is what actually
/// makes a btop graph look smooth rather than "blocky": far higher
/// effective vertical resolution per column, plus each character visibly
/// connects to its neighbor instead of standing alone.
const BRAILLE_UP: [[char; 5]; 5] = [
    [' ', '⢀', '⢠', '⢰', '⢸'],
    ['⡀', '⣀', '⣠', '⣰', '⣸'],
    ['⡄', '⣄', '⣤', '⣴', '⣼'],
    ['⡆', '⣆', '⣦', '⣶', '⣾'],
    ['⡇', '⣇', '⣧', '⣷', '⣿'],
];

/// btop's own `tty_mode` fallback table (`src/btop_draw.cpp`: `tty_up`,
/// which is byte-for-byte identical to `tty_down` there — unlike Braille,
/// where the up/down variants differ, the coarser shade-block alphabet
/// doesn't distinguish them). Verified against the real source rather than
/// guessed: only 3 non-blank glyphs exist (`░` `▒` `█` — no `▓`), and
/// — same as [`BRAILLE_UP`] — it's a previous→current *transition* table,
/// so this console-safe path packs 2 samples per character exactly like
/// the truecolor/Braille path does, not a flattened 1x-per-sample
/// approximation. All 4 distinct glyphs here (including blank) are
/// individually confirmed to render as their own correct native CP437
/// slot on a live TTY1 (`is_raw_console`).
const TTY_LEVELS: [[char; 5]; 5] = [
    [' ', '░', '░', '▒', '▒'],
    ['░', '░', '▒', '▒', '█'],
    ['░', '▒', '▒', '▒', '█'],
    ['▒', '▒', '▒', '█', '█'],
    ['▒', '█', '█', '█', '█'],
];

/// A btop-style history graph: each character encodes the *transition*
/// from the previous sample's height to the current one (btop's own
/// comment on this technique: "calculate previous + current value to fit
/// two values in 1 braille character"), colored via [`gradient_color`]
/// by the current sample's value — taller (higher-value) points shift
/// toward red. Takes the same `(values, peak)` shape [`spark`] already
/// produces.
fn braille_sparkline(values: &[u64], peak: u64) -> Line<'static> {
    let peak = peak.max(1);
    let level = |v: u64| ((v as f64 / peak as f64).clamp(0.0, 1.0) * 4.0).round() as usize;

    let mut spans = Vec::with_capacity(values.len());
    let mut prev_level = values.first().map(|&v| level(v)).unwrap_or(0);
    for &v in values {
        let cur_level = level(v);
        let glyph = BRAILLE_UP[prev_level.min(4)][cur_level.min(4)];
        let frac = (v as f64 / peak as f64).clamp(0.0, 1.0);
        spans.push(Span::styled(glyph.to_string(), Style::default().fg(gradient_color_impl(frac, false))));
        prev_level = cur_level;
    }
    Line::from(spans)
}

/// [`is_raw_console`]-safe equivalent of [`braille_sparkline`]: same
/// previous→current transition encoding (2 samples per character, via
/// [`TTY_LEVELS`] instead of [`BRAILLE_UP`]), colored by the *current*
/// sample's value.
fn shade_sparkline(values: &[u64], peak: u64) -> Line<'static> {
    let peak = peak.max(1);
    let level = |v: u64| ((v as f64 / peak as f64).clamp(0.0, 1.0) * 4.0).round() as usize;

    let mut spans = Vec::with_capacity(values.len());
    let mut prev_level = values.first().map(|&v| level(v)).unwrap_or(0);
    for &v in values {
        let cur_level = level(v);
        let glyph = TTY_LEVELS[prev_level.min(4)][cur_level.min(4)];
        let frac = (v as f64 / peak as f64).clamp(0.0, 1.0);
        spans.push(Span::styled(glyph.to_string(), Style::default().fg(gradient_color_impl(frac, true))));
        prev_level = cur_level;
    }
    Line::from(spans)
}

/// btop's height==1 case colors by data value, not row position (there's
/// no "row" to speak of) — dispatches to whichever single-row
/// implementation actually renders on this terminal; see
/// [`is_raw_console`].
fn gradient_sparkline(values: &[u64], peak: u64) -> Line<'static> {
    if is_raw_console() {
        shade_sparkline(values, peak)
    } else {
        braille_sparkline(values, peak)
    }
}

/// btop's real *multi-row* graph algorithm (`src/btop_draw.cpp`,
/// `Graph::_create`, the `height > 1` branch — verified against the
/// actual source, not approximated). This is what a btop CPU/network
/// history graph actually is, and it's structurally different from a
/// single-row sparkline in one important way: color is assigned **per
/// row**, not per data point. Each row represents a fixed vertical band
/// of the value range (row 0 = the top/highest band); a row's color
/// comes from its position in that gradient (top = hot/red, bottom =
/// cool/green) regardless of the data, while the braille glyph in each
/// row/column cell (still the same previous→current 2-value encoding as
/// [`braille_sparkline`]) shows how much of *that row's band* the value
/// reached. The net effect — the real btop look — is that a steady low
/// value only ever lights up the green bottom rows, and a spike visibly
/// climbs into hotter rows as it rises, rather than the whole graph
/// being one flat color.
fn braille_graph_rows(window: &[f64], height: usize) -> Vec<Line<'static>> {
    let max = window.iter().cloned().fold(0.0_f64, f64::max).max(1e-9);
    let norm = |v: f64| (v / max * 100.0).clamp(0.0, 100.0);

    let mut rows: Vec<Vec<Span<'static>>> = (0..height).map(|_| Vec::with_capacity(window.len())).collect();
    let mut prev = window.first().map(|&v| norm(v)).unwrap_or(0.0);

    for &raw in window {
        let cur = norm(raw);
        for (horizon, row) in rows.iter_mut().enumerate() {
            let cur_high = 100.0 * (height - horizon) as f64 / height as f64;
            let cur_low = 100.0 * (height - horizon - 1) as f64 / height as f64;
            let level_of = |v: f64| -> usize {
                if v >= cur_high {
                    4
                } else if v <= cur_low {
                    0
                } else {
                    (((v - cur_low) * 4.0 / (cur_high - cur_low)).round() as usize).clamp(0, 4)
                }
            };
            let glyph = BRAILLE_UP[level_of(prev)][level_of(cur)];
            // Row 0 is the top (hottest); the bottom row is the coolest —
            // matches btop's `100 - ((i - 1) * 100 / height)` exactly.
            let row_t = 1.0 - (horizon as f64 / (height as f64 - 1.0).max(1.0));
            row.push(Span::styled(glyph.to_string(), Style::default().fg(gradient_color_impl(row_t, false))));
        }
        prev = cur;
    }
    rows.into_iter().map(Line::from).collect()
}

/// [`is_raw_console`]-safe equivalent of [`braille_graph_rows`]: identical
/// per-row vertical-band coloring and previous→current transition packing,
/// via [`TTY_LEVELS`] instead of [`BRAILLE_UP`].
fn shade_graph_rows(window: &[f64], height: usize) -> Vec<Line<'static>> {
    let max = window.iter().cloned().fold(0.0_f64, f64::max).max(1e-9);
    let norm = |v: f64| (v / max * 100.0).clamp(0.0, 100.0);
    let mut prev = window.first().map(|&v| norm(v)).unwrap_or(0.0);

    let mut rows: Vec<Vec<Span<'static>>> = (0..height).map(|_| Vec::with_capacity(window.len())).collect();
    for &raw in window {
        let cur = norm(raw);
        for (horizon, row) in rows.iter_mut().enumerate() {
            let cur_high = 100.0 * (height - horizon) as f64 / height as f64;
            let cur_low = 100.0 * (height - horizon - 1) as f64 / height as f64;
            let level_of = |v: f64| -> usize {
                if v >= cur_high {
                    4
                } else if v <= cur_low {
                    0
                } else {
                    (((v - cur_low) * 4.0 / (cur_high - cur_low)).round() as usize).clamp(0, 4)
                }
            };
            let row_t = 1.0 - (horizon as f64 / (height as f64 - 1.0).max(1.0));
            let glyph = TTY_LEVELS[level_of(prev)][level_of(cur)];
            row.push(Span::styled(glyph.to_string(), Style::default().fg(gradient_color_impl(row_t, true))));
        }
        prev = cur;
    }
    rows.into_iter().map(Line::from).collect()
}

/// btop's `height == 1` case is a genuinely different algorithm, not just
/// this one with `height` set to 1 — a single row has no "vertical band"
/// to be colored by, so btop colors it by the data value instead (exactly
/// [`gradient_sparkline`]'s technique). This delegates to that rather than
/// running the banded math degenerately, which would color every glyph by
/// a meaningless single "row 0 of 1" position instead of by value.
/// Otherwise dispatches to whichever multi-row implementation actually
/// renders on this terminal — see [`is_raw_console`].
fn gradient_graph_rows(values: &[f64], width: usize, height: usize) -> Vec<Line<'static>> {
    let height = height.max(1);
    let width = width.max(1);
    let start = values.len().saturating_sub(width);
    let window = &values[start..];

    if height == 1 {
        let (scaled, peak) = spark(window);
        return vec![gradient_sparkline(&scaled, peak)];
    }

    if is_raw_console() {
        shade_graph_rows(window, height)
    } else {
        braille_graph_rows(window, height)
    }
}

fn draw_latency(frame: &mut Frame, app: &App, area: Rect) {
    let block = panel(" latency ");
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let rows = Layout::vertical([
        Constraint::Length(5),
        Constraint::Length(1),
        Constraint::Min(1),
    ])
    .split(inner);

    let snap = app.snapshot();
    let header = Row::new(["", "p50", "p99", "avg", "samples"])
        .style(
            Style::default()
                .fg(ratatui::style::Color::White)
                .bg(DIM)
                .add_modifier(Modifier::BOLD),
        )
        .height(1);

    let empty = crate::metrics::Histogram::default();
    let rows_data: [(&str, &crate::metrics::Histogram); 4] = match snap {
        Some(s) => [
            ("ttft", &s.ttft),
            ("queue", &s.queue),
            ("e2e", &s.e2e),
            ("itl", &s.itl),
        ],
        None => [
            ("ttft", &empty),
            ("queue", &empty),
            ("e2e", &empty),
            ("itl", &empty),
        ],
    };

    let table_rows: Vec<Row> = rows_data
        .iter()
        .map(|(name, h)| {
            Row::new([
                Span::styled(*name, Style::default().fg(ACCENT)),
                Span::raw(util::fmt_secs(h.p50)),
                Span::styled(
                    util::fmt_secs(h.p99),
                    Style::default().fg(color_for_p99(h.p99)),
                ),
                Span::raw(util::fmt_secs(h.avg)),
                Span::styled(
                    util::fmt_si(h.count),
                    Style::default().fg(ratatui::style::Color::Gray),
                ),
            ])
        })
        .collect();

    let table = Table::new(
        table_rows,
        [
            Constraint::Length(7),
            Constraint::Length(10),
            Constraint::Length(10),
            Constraint::Length(10),
            Constraint::Min(8),
        ],
    )
    .header(header)
    .column_spacing(1);
    frame.render_widget(table, rows[0]);

    frame.render_widget(
        Line::from(vec![
            Span::styled("e2e p99  ", Style::default().fg(DIM)),
            Span::styled(
                util::fmt_secs(app.histories().e2e_p99.last()),
                Style::default().fg(ratatui::style::Color::White),
            ),
            Span::styled("  ttft p99  ", Style::default().fg(DIM)),
            Span::styled(
                util::fmt_secs(app.histories().ttft_p99.last()),
                Style::default().fg(ratatui::style::Color::White),
            ),
        ]),
        rows[1],
    );

    if app.histories().e2e_p99.is_empty() {
        frame.render_widget(
            Paragraph::new(centered_note("history…")).alignment(Alignment::Center),
            rows[2],
        );
    } else {
        let values = app.histories().e2e_p99.values();
        let lines = gradient_graph_rows(&values, rows[2].width as usize, rows[2].height as usize);
        frame.render_widget(Paragraph::new(lines), rows[2]);
    }
}

/// Maps onto the same green(0s)/amber(2s)/red(10s+) thresholds the old
/// 3-bucket version used, but smoothly instead of stepping between them.
fn color_for_p99(seconds: f64) -> ratatui::style::Color {
    let t = if seconds <= 2.0 {
        (seconds / 2.0) * 0.5
    } else {
        0.5 + ((seconds - 2.0) / 8.0).min(1.0) * 0.5
    };
    gradient_color(t)
}

// ---------------------------------------------------------------------------
// instances table (btop's "procs" panel)
// ---------------------------------------------------------------------------

// Column widths for the instances table. Named so the truncation applied
// to each cell's text can match the column it's actually rendered into —
// truncating to the wrong length either wastes the column's width or lets
// ratatui's own hard clip (no ellipsis) kick in instead of ending cleanly.
const COL_NAME: usize = 12;
const COL_STATUS: usize = 16;
const COL_ENDPOINT: usize = 18;

/// A column header label, marked with a trailing `*` when it's the active
/// sort column — btop highlights its process list's active sort column
/// the same way (a plain ASCII marker rather than a Unicode arrow glyph,
/// so it renders identically in both the truecolor and console-safe
/// paths without needing its own glyph-safety check).
fn sort_header(app: &App, key: SortKey, label: &str) -> String {
    if app.sort_by == key {
        format!("{label}*")
    } else {
        label.to_string()
    }
}

fn draw_instances(frame: &mut Frame, app: &App, area: Rect) {
    let header = Row::new([
        "#".to_string(),
        sort_header(app, SortKey::Name, "instance"),
        "source".to_string(),
        "status".to_string(),
        "endpoint".to_string(),
        "model".to_string(),
        sort_header(app, SortKey::Running, "run"),
        sort_header(app, SortKey::Waiting, "wait"),
        sort_header(app, SortKey::Kv, "kv"),
        sort_header(app, SortKey::GenTps, "gen tok/s"),
        sort_header(app, SortKey::ReqPerS, "req/s"),
        sort_header(app, SortKey::TtftP99, "ttft p99"),
    ])
    .style(
        Style::default()
            .fg(ratatui::style::Color::White)
            .bg(DIM)
            .add_modifier(ratatui::style::Modifier::BOLD),
    )
    .height(1);

    // Filter first (by name, case-insensitive — btop's own `Proc::filter`),
    // then sort what's left. The "#" badge below always shows the
    // *original* 1-based index, not the sorted position, so the existing
    // 1-9 instance-select keys keep working exactly as before regardless
    // of how the table is currently sorted or filtered.
    let filter_lower = app.filter.to_lowercase();
    let mut order: Vec<usize> = (0..app.runtimes.len())
        .filter(|&i| filter_lower.is_empty() || app.runtimes[i].def.name.to_lowercase().contains(&filter_lower))
        .collect();
    order.sort_by(|&a, &b| {
        use std::cmp::Ordering;
        let da = &app.runtimes[a].derived;
        let db = &app.runtimes[b].derived;
        let ord = match app.sort_by {
            SortKey::Natural => Ordering::Equal,
            SortKey::Name => app.runtimes[a].def.name.to_lowercase().cmp(&app.runtimes[b].def.name.to_lowercase()),
            SortKey::Running => da.running.partial_cmp(&db.running).unwrap_or(Ordering::Equal),
            SortKey::Waiting => da.waiting.partial_cmp(&db.waiting).unwrap_or(Ordering::Equal),
            SortKey::Kv => da.kv.partial_cmp(&db.kv).unwrap_or(Ordering::Equal),
            SortKey::GenTps => da.gen_tps.partial_cmp(&db.gen_tps).unwrap_or(Ordering::Equal),
            SortKey::ReqPerS => da.req_per_s.partial_cmp(&db.req_per_s).unwrap_or(Ordering::Equal),
            SortKey::TtftP99 => da.ttft_p99.partial_cmp(&db.ttft_p99).unwrap_or(Ordering::Equal),
        };
        if app.sort_desc { ord.reverse() } else { ord }
    });

    let rows: Vec<Row> = order
        .iter()
        .map(|&i| {
            let rt = &app.runtimes[i];
            let h = rt.health(app.poll);
            let status_text = match (&rt.last_error, rt.snapshot.is_some()) {
                (Some(e), _) => truncate(e, COL_STATUS),
                (None, false) => "starting…".to_string(),
                (None, true) => "ok".to_string(),
            };
            let model = rt
                .snapshot
                .as_ref()
                .and_then(|s| s.model.clone())
                .unwrap_or_else(|| "-".into());
            let d = &rt.derived;
            let style = if app.view == View::Instance(i) {
                Style::default()
                    .fg(ACCENT)
                    .bg(ratatui::style::Color::Rgb(20, 30, 40))
                    .add_modifier(ratatui::style::Modifier::BOLD)
            } else {
                Style::default()
            };
            Row::new([
                Span::styled(format!("{}", i + 1), Style::default().fg(DIM)),
                Span::styled(truncate(&rt.def.name, COL_NAME), style),
                Span::styled(rt.def.kind.label(), Style::default().fg(DIM)),
                Span::styled(status_text, Style::default().fg(health_color(h))),
                Span::styled(truncate(&util::short_url(&rt.def.url), COL_ENDPOINT), Style::default().fg(DIM)),
                // The model column is the one field genuinely worth giving
                // extra width to (see the `Fill` constraint below) — cap
                // at a generous safety ceiling only (Table already clips
                // to the column's actual rendered width; this just bounds
                // how much text we build before that clipping happens).
                Span::styled(truncate(&model, 80), Style::default().fg(ratatui::style::Color::Gray)),
                Span::raw(format!("{:.0}", d.running)),
                Span::raw(format!("{:.0}", d.waiting)),
                Span::styled(
                    util::fmt_pct(d.kv),
                    Style::default().fg(gauge_color(d.kv)),
                ),
                Span::styled(
                    util::fmt_si(d.gen_tps),
                    Style::default().fg(GOOD),
                ),
                Span::raw(format!("{:.1}", d.req_per_s)),
                Span::styled(
                    util::fmt_secs(d.ttft_p99),
                    Style::default().fg(color_for_p99(d.ttft_p99)),
                ),
            ])
            .style(style)
        })
        .collect();

    // Bounded widths for fields with predictable content length (a
    // percentage of a 240-column terminal is a lot of blank padding
    // around a 5-character instance name); `Fill` for the one field that
    // actually benefits from extra room. Previously every text column was
    // `Percentage`-based, so it stretched linearly with terminal width
    // regardless of content — verified: at 240 cols the "instance" column
    // alone reserved ~30 cols for names that are typically 5-15 chars.
    let widths = [
        Constraint::Length(3),
        Constraint::Length(COL_NAME as u16),
        Constraint::Length(10),
        Constraint::Length(COL_STATUS as u16),
        Constraint::Length(COL_ENDPOINT as u16),
        Constraint::Fill(1),
        Constraint::Length(5),
        Constraint::Length(5),
        Constraint::Length(6),
        // "gen tok/s" is 9 chars, but the active-sort marker (`sort_header`)
        // appends a `*`, making it 10 — one column short and it silently
        // truncates the marker off every render, found by this column's
        // own sort-indicator test.
        Constraint::Length(10),
        Constraint::Length(7),
        Constraint::Length(9),
    ];

    let mut title_parts = vec!["instances".to_string()];
    if app.sort_by != SortKey::Natural {
        title_parts.push(format!("sort: {} {}", app.sort_by.label(), if app.sort_desc { "desc" } else { "asc" }));
    }
    if app.filter_editing {
        title_parts.push(format!("filter: {}_", app.filter));
    } else if !app.filter.is_empty() {
        title_parts.push(format!("filter: {}", app.filter));
    }
    let title = format!(" {} ", title_parts.join(" · "));

    let table = Table::new(rows, widths)
        .header(header)
        .block(panel(&title))
        .column_spacing(1);

    frame.render_widget(table, area);
}

// ---------------------------------------------------------------------------
// requests row (full width)
// ---------------------------------------------------------------------------

fn draw_requests(frame: &mut Frame, app: &App, area: Rect) {
    let d = app.derived();
    let hist = app.histories();
    let block = panel(" requests ");
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let rows = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(1),
        Constraint::Length(1),
        Constraint::Min(1),
    ])
    .split(inner);

    let total = (d.running + d.waiting).max(1.0);
    frame.render_widget(
        Paragraph::new(gradient_meter(&format!("running {:.0}", d.running), d.running / total, rows[0].width)),
        rows[0],
    );
    frame.render_widget(
        Paragraph::new(gradient_meter(&format!("waiting {:.0}", d.waiting), d.waiting / total, rows[1].width)),
        rows[1],
    );

    let info = Line::from(vec![
        Span::styled("completed ", Style::default().fg(DIM)),
        Span::styled(
            util::fmt_si(app.snapshot().map(|s| s.success_total).unwrap_or(0.0)),
            Style::default().fg(ratatui::style::Color::White),
        ),
        Span::styled("  rate ", Style::default().fg(DIM)),
        Span::styled(
            format!("{:.1}/s", d.req_per_s),
            Style::default().fg(GOOD),
        ),
        Span::styled("  preemptions ", Style::default().fg(DIM)),
        Span::raw(util::fmt_si(
            app.snapshot().map(|s| s.preemptions).unwrap_or(0.0),
        )),
    ]);
    frame.render_widget(Paragraph::new(info), rows[2]);

    // sparkline of running requests over history
    if hist.running.is_empty() {
        frame.render_widget(
            Paragraph::new(centered_note("history…")).alignment(Alignment::Center),
            rows[3],
        );
    } else {
        // overlay running and waiting: plot the larger of the two per sample
        let running = hist.running.values();
        let waiting = hist.waiting.values();
        let combined: Vec<f64> = running
            .iter()
            .zip(waiting.iter().chain(std::iter::repeat(&0.0)))
            .map(|(r, w)| (*r).max(*w))
            .collect();
        let lines = gradient_graph_rows(&combined, rows[3].width as usize, rows[3].height as usize);
        frame.render_widget(Paragraph::new(lines), rows[3]);
    }
}

// ---------------------------------------------------------------------------
// detail row: service/discovery | GPU | session statistics
// ---------------------------------------------------------------------------

/// Three panels, each with a distinct, non-overlapping concern (section 3.5
/// of the redesign brief): where the service/discovery/auth information
/// lives, where hardware state lives, and where monitor-lifetime
/// statistics live. Previously all three were interleaved into one
/// "stats" panel; splitting them out is what makes each legible instead
/// of crowded.
fn draw_detail_row(frame: &mut Frame, app: &App, area: Rect) {
    // The orchestrator column only appears once one is actually detected
    // (`App.orchestrator`, see `orchestrator.rs`) — most deployments won't
    // run one at all, so an always-present "orchestrator: unavailable"
    // column would be clutter rather than useful, unlike the GPU panel
    // (whose absence is itself informative on a box that should have one).
    if let Some(orch) = &app.orchestrator {
        let cols = Layout::horizontal([
            Constraint::Percentage(26),
            Constraint::Percentage(20),
            Constraint::Percentage(20),
            Constraint::Percentage(34),
        ])
        .split(area);
        draw_service_panel(frame, app, cols[0]);
        draw_gpu_panel(frame, app, cols[1]);
        draw_session_panel(frame, app, cols[2]);
        draw_orchestrator_panel(frame, app, orch, cols[3]);
    } else {
        let cols = Layout::horizontal([
            Constraint::Percentage(34),
            Constraint::Percentage(33),
            Constraint::Percentage(33),
        ])
        .split(area);
        draw_service_panel(frame, app, cols[0]);
        draw_gpu_panel(frame, app, cols[1]);
        draw_session_panel(frame, app, cols[2]);
    }
}

/// The orchestrator gateway's own view of itself: gateway/scheduler
/// status, per-worker health as *it* observes them (useful to cross-check
/// against vllm-top's own direct worker probing elsewhere on screen), and
/// a dispatch-rate history graph — the same `gradient_graph_rows`
/// btop-style multi-row graph used for throughput/latency/requests, not a
/// separate rendering technique.
fn draw_orchestrator_panel(frame: &mut Frame, app: &App, orch: &crate::orchestrator::Snapshot, area: Rect) {
    let block = panel(" orchestrator ");
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let h = &orch.health;
    // `ready` (not the `status` string) drives the color — it's the field
    // that actually distinguishes "can route" from "can't", robust to
    // whatever exact wording the gateway uses for a given failure mode.
    let gw_color = if h.ready { GOOD } else { BAD };
    let sched_color = if h.scheduler.ready { GOOD } else { WARN };

    let mut lines = vec![
        Line::from(vec![
            Span::styled("gateway   ", Style::default().fg(DIM)),
            Span::styled(h.status.clone(), Style::default().fg(gw_color)),
            // The process's own liveness, separate from the routing
            // verdict above — see `orchestrator::Gateway`'s doc comment.
            // A process that's "alive" but not "ready" is exactly the
            // idle-staleness failure mode this integration exists to
            // surface, so this must never collapse into one indicator.
            Span::styled(
                format!("  process {}", h.gateway.status),
                Style::default().fg(DIM),
            ),
            Span::styled(
                format!("  up {}", util::fmt_dur(std::time::Duration::from_secs_f64(h.gateway.uptime_seconds))),
                Style::default().fg(ratatui::style::Color::White),
            ),
        ]),
        Line::from(vec![
            Span::styled("scheduler ", Style::default().fg(DIM)),
            Span::styled(h.scheduler.status.clone(), Style::default().fg(sched_color)),
            Span::styled(
                format!(
                    "  {}/{} workers · queued {} · active {}",
                    h.scheduler.available_workers, h.scheduler.total_workers,
                    h.scheduler.queued_work as u64, h.scheduler.active_work as u64
                ),
                Style::default().fg(ratatui::style::Color::White),
            ),
        ]),
        Line::from(vec![
            Span::styled("dispatch  ", Style::default().fg(DIM)),
            Span::styled(format!("{:.1}/s", app.orch_dispatch_rate), Style::default().fg(GOOD)),
            Span::styled(
                format!("  fetch {}ms", orch.fetch_latency.as_millis()),
                Style::default().fg(DIM),
            ),
        ]),
    ];
    for (name, w) in &h.workers {
        let color = if w.healthy { GOOD } else { BAD };
        let mut spans = vec![
            Span::styled(format!("  {} ", truncate(name, 28)), Style::default().fg(DIM)),
            Span::styled(w.status.clone(), Style::default().fg(color)),
        ];
        // Only surfaced when nonzero — a worker with a clean record
        // shouldn't carry a "0 failures" caveat nobody needs to read.
        if w.consecutive_failures > 0 {
            spans.push(Span::styled(
                format!("  ({} consecutive failures)", w.consecutive_failures),
                Style::default().fg(WARN),
            ));
        }
        lines.push(Line::from(spans));
    }
    let header_height = lines.len() as u16;

    let rows = Layout::vertical([Constraint::Length(header_height), Constraint::Min(1)]).split(inner);
    frame.render_widget(Paragraph::new(lines), rows[0]);

    if app.orch_hist.is_empty() {
        frame.render_widget(
            Paragraph::new(centered_note("collecting samples…")).alignment(Alignment::Center),
            rows[1],
        );
    } else {
        let values = app.orch_hist.values();
        let graph_lines = gradient_graph_rows(&values, rows[1].width as usize, rows[1].height as usize);
        frame.render_widget(Paragraph::new(graph_lines), rows[1]);
    }
}

fn draw_service_panel(frame: &mut Frame, app: &App, area: Rect) {
    // Truncate to what this panel can actually show: border (2) + the
    // "label   " prefix (9) leaves this many columns for the value itself.
    // Long model identifiers must not spill into the neighboring panel.
    let value_budget = area.width.saturating_sub(11).max(8) as usize;
    let mut lines: Vec<Line> = Vec::new();

    match app.view {
        View::Aggregate => {
            lines.push(stat_line("source", &format!("aggregate of {} instances", app.runtimes.len()), DIM));
            let h = overall_health(app);
            lines.push(stat_line(
                "svc",
                &format!("{} ok · {} stale · {} down", h.ok, h.stale, h.down),
                if h.down > 0 { WARN } else { DIM },
            ));
        }
        View::Instance(i) => {
            if let Some(rt) = app.runtimes.get(i) {
                lines.push(stat_line(
                    "endpoint",
                    &truncate(&format!("{} · {}", rt.def.kind.label(), util::short_url(&rt.def.url)), value_budget),
                    DIM,
                ));

                // Discovery source and attribution confidence are shown on
                // separate lines rather than crammed onto one — with three
                // panels sharing the terminal width instead of two, one
                // combined line risked truncating the confidence label
                // mid-word at moderate widths (caught by
                // stats_panel_shows_discovery_auth_and_confidence_for_a_discovered_instance
                // at 140 cols). The confidence label is always shown in
                // full, verbatim (never collapsed to a generic checkmark),
                // specifically so "uid association" is never visually
                // implied to be as strong a signal as "verified".
                match &rt.def.discovered_via {
                    Some(via) => {
                        lines.push(stat_line("discovery", &truncate(&format!("via {via}"), value_budget), DIM));
                        let confidence = rt.def.confidence.as_ref().map(|c| c.label()).unwrap_or("unknown confidence");
                        lines.push(stat_line("confidence", &truncate(confidence, value_budget), DIM));
                    }
                    None => lines.push(stat_line("discovery", "explicit configuration", DIM)),
                }

                if let Some(auth) = &rt.def.auth {
                    lines.push(stat_line("auth", auth.label(), DIM));
                }

                // Distinguish "the process answers" from "we're actually
                // collecting metrics from it" — health() reflects the
                // latter, not merely that something is listening.
                let health = rt.health(app.poll);
                let metrics_desc = match health {
                    Health::Ok => rt
                        .last_ok
                        .map(|t| format!("ok · last collected {} ago", util::fmt_dur(t.elapsed())))
                        .unwrap_or_else(|| "ok".to_string()),
                    Health::Stale => rt
                        .last_ok
                        .map(|t| format!("stale · last collected {} ago", util::fmt_dur(t.elapsed())))
                        .unwrap_or_else(|| "stale".to_string()),
                    Health::Down => match &rt.last_error {
                        Some(err) => format!("down: {err}"),
                        None => "down".to_string(),
                    },
                };
                let metrics_color = match health {
                    Health::Ok => GOOD,
                    Health::Stale | Health::Down => WARN,
                };
                lines.push(stat_line("metrics", &truncate(&metrics_desc, value_budget), metrics_color));

                if matches!(rt.def.kind, crate::config::SourceKind::Direct) {
                    lines.push(stat_line("vllm", rt.vllm_version.as_deref().unwrap_or("unknown"), DIM));
                }

                if let Some(s) = &rt.snapshot {
                    let model = s.model.clone().unwrap_or_else(|| "-".into());
                    let ctx = rt
                        .max_model_len
                        .map(|n| format!("  ({} ctx)", util::fmt_si(n as f64)))
                        .unwrap_or_default();
                    lines.push(stat_line("model", &truncate(&format!("{model}{ctx}"), value_budget), DIM));
                }
            }
        }
    }

    frame.render_widget(Paragraph::new(lines).block(panel(" service ")), area);
}

fn draw_gpu_panel(frame: &mut Frame, app: &App, area: Rect) {
    let mut lines: Vec<Line> = Vec::new();

    if app.gpu_info.is_empty() && app.gpu.is_empty() {
        lines.push(Line::from(Span::styled(
            "unavailable (no GPU telemetry tool found)",
            Style::default().fg(DIM),
        )));
    } else {
        // Static identity (name, total memory) and live counters are
        // fetched separately (see src/gpu.rs) and matched by index here.
        // One device's probe failing must not blank out another's —
        // each row is built independently.
        let mut indices: Vec<u32> =
            app.gpu_info.iter().map(|g| g.index).chain(app.gpu.iter().map(|g| g.index)).collect();
        indices.sort_unstable();
        indices.dedup();

        for idx in indices {
            let info = app.gpu_info.iter().find(|g| g.index == idx);
            let live = app.gpu.iter().find(|g| g.index == idx);

            let name = info.and_then(|i| i.device_name.as_deref()).unwrap_or("GPU");
            let bdf = info.and_then(|i| i.pci_bdf.as_deref());
            // Truncate the whole "name (bdf)" line against the real panel
            // width (border + "gpuN " prefix) rather than truncating just
            // the name and letting the bdf suffix overflow — a Paragraph
            // doesn't wrap by default, so an untruncated line gets hard
            // clipped by the terminal buffer instead of ending cleanly.
            let prefix = format!("gpu{idx} ");
            let budget = (area.width as usize).saturating_sub(2 + prefix.chars().count()).max(6);
            let full_name = match bdf {
                Some(bdf) => format!("{name} ({bdf})"),
                None => name.to_string(),
            };
            lines.push(Line::from(vec![
                Span::styled(prefix, Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)),
                Span::styled(truncate(&full_name, budget), Style::default().fg(ratatui::style::Color::White)),
            ]));

            // Prefer xpu-smi's own reported utilization percentage over a
            // derived used/total ratio when both are available — it's the
            // more authoritative number (it can account for allocation
            // semantics a raw ratio can't).
            let mem = match (
                live.and_then(|l| l.mem_used_mib),
                info.and_then(|i| i.mem_total_mib),
                live.and_then(|l| l.mem_util_percent),
            ) {
                (Some(used), Some(total), Some(pct)) if total > 0.0 => {
                    format!("{:.1}/{:.1} GiB ({pct:.0}%)", used / 1024.0, total / 1024.0)
                }
                (Some(used), Some(total), None) if total > 0.0 => {
                    format!("{:.1}/{:.1} GiB ({:.0}%)", used / 1024.0, total / 1024.0, (used / total) * 100.0)
                }
                (Some(used), None, Some(pct)) => format!("{:.1} GiB used ({pct:.0}%, total n/a)", used / 1024.0),
                (Some(used), None, None) => format!("{:.1} GiB used (total n/a)", used / 1024.0),
                _ => "mem n/a".to_string(),
            };
            let power = live
                .and_then(|l| l.power_w)
                .map(|w| format!("{w:.1}W"))
                .unwrap_or_else(|| "power n/a".to_string());
            lines.push(Line::from(vec![
                Span::styled("  ", Style::default()),
                Span::styled(mem, Style::default().fg(ratatui::style::Color::White)),
                Span::raw("  ·  "),
                Span::styled(power, Style::default().fg(ratatui::style::Color::White)),
            ]));

            // Utilization and temperature are shown "n/a" whenever the
            // underlying tool doesn't report them — verified genuinely
            // absent from `xpu-smi`'s own output on the deployment this
            // was built against, never left implicitly zero.
            lines.push(Line::from(vec![
                Span::styled("  util n/a", Style::default().fg(DIM)),
                Span::raw("  ·  "),
                Span::styled("temp n/a", Style::default().fg(DIM)),
            ]));

            if let Some(i) = info {
                if i.pcie_generation.is_some() || i.pcie_max_link_width.is_some() {
                    let gen = i.pcie_generation.as_deref().unwrap_or("n/a");
                    let width = i.pcie_max_link_width.as_deref().unwrap_or("n/a");
                    lines.push(Line::from(Span::styled(
                        format!("  pcie gen {gen} x{width}"),
                        Style::default().fg(DIM),
                    )));
                }
            }
        }
    }

    frame.render_widget(Paragraph::new(lines).block(panel(" gpu ")), area);
}

fn draw_session_panel(frame: &mut Frame, app: &App, area: Rect) {
    let snap = app.snapshot();
    let d = app.derived();
    let session = app.session();
    let mut lines: Vec<Line> = Vec::new();

    lines.push(stat_line(
        "uptime",
        &format!("{}  ({} polls)", util::fmt_dur(app.uptime()), app.polls),
        DIM,
    ));

    if let Some(s) = snap {
        lines.push(stat_line(
            "prompt",
            &format!(
                "{} all-time · {} session  (+{}/s)",
                util::fmt_si(s.prompt_tokens),
                util::fmt_si(session.prompt_tokens),
                util::fmt_si(d.prompt_tps)
            ),
            GRAPH_2,
        ));
        lines.push(stat_line(
            "output",
            &format!(
                "{} all-time · {} session  (+{}/s)",
                util::fmt_si(s.generation_tokens),
                util::fmt_si(session.generation_tokens),
                util::fmt_si(d.gen_tps)
            ),
            GOOD,
        ));

        let reasons = s
            .success_by_reason
            .iter()
            .map(|(k, v)| format!("{} {}", k, util::fmt_si(*v)))
            .collect::<Vec<_>>()
            .join(" · ");
        let reason_part = if reasons.is_empty() { String::new() } else { format!("  ({reasons})") };
        lines.push(stat_line("done", &format!("{}{}", util::fmt_si(s.success_total), reason_part), WARN));

        let hit = d.prefix_hit_rate.map(util::fmt_pct).unwrap_or_else(|| "-".into());
        let cached = s.cached_ratio().map(util::fmt_pct).unwrap_or_else(|| "-".into());
        lines.push(stat_line("cache", &format!("hit {hit} · tokens {cached}"), ACCENT));
    } else {
        lines.push(stat_line("status", "waiting for first sample…", WARN));
    }

    frame.render_widget(Paragraph::new(lines).block(panel(" session ")), area);
}

fn stat_line(label: &str, value: &str, value_color: ratatui::style::Color) -> Line<'static> {
    // The trailing literal space guarantees a gap even for a label longer
    // than the padding width (`{:<8}` alone doesn't add one once the label
    // itself reaches or exceeds 8 characters, e.g. "discovery"/"connections").
    Line::from(vec![
        Span::styled(format!("{label:<8} "), Style::default().fg(DIM)),
        Span::styled(value.to_string(), Style::default().fg(value_color)),
    ])
}

// ---------------------------------------------------------------------------
// help overlay
// ---------------------------------------------------------------------------

fn draw_help(frame: &mut Frame, area: Rect) {
    let w = area.width.clamp(40, 72);
    let h = area.height.clamp(14, 20);
    let x = area.x + (area.width.saturating_sub(w)) / 2;
    let y = area.y + (area.height.saturating_sub(h)) / 2;
    let rect = Rect::new(x, y, w, h);

    let lines = vec![
        Line::from(""),
        Line::from(vec![
            Span::styled(" q ", Style::default().fg(ACCENT).bold()),
            Span::raw("quit            "),
            Span::styled(" tab ", Style::default().fg(ACCENT).bold()),
            Span::raw("cycle views"),
        ]),
        Line::from(vec![
            Span::styled(" 1-9 ", Style::default().fg(ACCENT).bold()),
            Span::raw("pick instance   "),
            Span::styled(" a ", Style::default().fg(ACCENT).bold()),
            Span::raw("aggregate view"),
        ]),
        Line::from(vec![
            Span::styled(" p ", Style::default().fg(ACCENT).bold()),
            Span::raw("pause history    "),
            Span::styled(" r ", Style::default().fg(ACCENT).bold()),
            Span::raw("poll now"),
        ]),
        Line::from(vec![
            Span::styled(" + ", Style::default().fg(ACCENT).bold()),
            Span::raw("faster interval  "),
            Span::styled(" - ", Style::default().fg(ACCENT).bold()),
            Span::raw("slower interval"),
        ]),
        Line::from(vec![
            Span::styled(" ? ", Style::default().fg(ACCENT).bold()),
            Span::raw("toggle this help "),
            Span::styled(" ←/→ ", Style::default().fg(ACCENT).bold()),
            Span::raw("cycle views"),
        ]),
        Line::from(vec![
            Span::styled(" F1-F5 ", Style::default().fg(ACCENT).bold()),
            Span::raw("toggle overview/graphs/detail/instances/requests"),
        ]),
        Line::from(vec![
            Span::styled(" s ", Style::default().fg(ACCENT).bold()),
            Span::raw("cycle sort column "),
            Span::styled(" S ", Style::default().fg(ACCENT).bold()),
            Span::raw("reverse sort"),
        ]),
        Line::from(vec![
            Span::styled(" / ", Style::default().fg(ACCENT).bold()),
            Span::raw("filter instances "),
            Span::styled(" enter/esc ", Style::default().fg(ACCENT).bold()),
            Span::raw("confirm/cancel"),
        ]),
        Line::from(""),
        Line::from(Span::styled(
            " sources: -u URL (vLLM /metrics) · -u URL --kind prometheus",
            Style::default().fg(DIM),
        )),
        Line::from(Span::styled(
            " metrics: vllm:num_requests_running, kv_cache_usage_perc, ttft…",
            Style::default().fg(DIM),
        )),
    ];

    let block = panel(" help ");
    frame.render_widget(Clear, rect);
    frame.render_widget(Paragraph::new(lines).block(block), rect);
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

fn centered_note(text: &str) -> Text<'static> {
    Text::from(vec![
        Line::from(""),
        Line::from(Span::styled(text.to_string(), Style::default().fg(DIM))),
    ])
}

fn truncate(text: &str, max: usize) -> String {
    let mut out = String::new();
    for (i, ch) in text.chars().enumerate() {
        if i + 1 >= max {
            out.push('…');
            break;
        }
        out.push(ch);
    }
    out
}

fn chrono_free_clock() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let day_secs = secs % 86_400;
    format!(
        "{:02}:{:02}:{:02}",
        day_secs / 3_600,
        (day_secs % 3_600) / 60,
        day_secs % 60
    )
}

// ---------------------------------------------------------------------------
// demo rendering (used by `--demo`)
// ---------------------------------------------------------------------------

/// Render one frame into a test backend and return it as plain text.
pub fn render_text(app: &App, width: u16, height: u16) -> Result<String> {
    let backend = TestBackend::new(width, height);
    let mut terminal: Terminal<TestBackend> = Terminal::new(backend)?;
    terminal.draw(|frame| draw(frame, app))?;

    let buffer = terminal.backend().buffer();
    let mut out = String::new();
    for y in 0..buffer.area.height {
        for x in 0..buffer.area.width {
            let cell = &buffer[Position::new(x, y)];
            out.push_str(cell.symbol());
        }
        out.push('\n');
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::app;
    use crate::config::{InstanceDef, Settings};
    use std::time::Duration;

    fn single_instance_app() -> App {
        let settings = Settings { poll: Duration::from_millis(200), history: 16 };
        let defs = vec![InstanceDef {
            name: "local".into(),
            kind: crate::config::SourceKind::Direct,
            url: "http://localhost:8000".into(),
            api_key: None,
            discovered_via: Some("systemd vllm.service".into()),
            auth: Some(crate::discover::AuthState::RequiredCredentialAccepted),
            confidence: Some(crate::discover::Confidence::UidAssociation),
        }];
        app::demo(&settings, defs).expect("demo app builds")
    }

    /// Regression test for a real bug: `stat_line`'s `{label:<8}` padding
    /// only guarantees a separating space for labels shorter than 8
    /// characters. "discovery" (9) and "confidence" (10) previously
    /// rendered (or would render, for any future 8+-char label) with no
    /// gap before the value at all, e.g. "confidenceuid association…".
    ///
    /// This must check the *service*/*confidence* panel content
    /// specifically, not just any occurrence of the substring — the
    /// footer's "1-9/a instance" keybind text also contains "instance ",
    /// which made an earlier version of this test pass without actually
    /// exercising the bug it claims to guard.
    #[test]
    fn stats_panel_labels_have_a_visible_gap_before_their_value() {
        let app = single_instance_app();
        let text = render_text(&app, 140, 42).expect("renders");
        let service_panel = panel_content(&text, "service");
        let confidence_line = service_panel
            .lines()
            .find(|l| l.contains("confidence"))
            .unwrap_or_else(|| panic!("no confidence line in service panel:\n{text}"));

        assert!(!confidence_line.contains("confidenceuid"), "label/value ran together: {confidence_line:?}");
        assert!(confidence_line.contains("confidence "), "expected a space after 'confidence': {confidence_line:?}");
    }

    /// Crops the rendered text to the columns spanned by a panel whose
    /// title contains `title_fragment`, from its header row to the next
    /// panel-header row (a line starting with '╭'). Used so assertions
    /// about one panel's content can't accidentally match text that
    /// happens to appear in a neighboring panel or the footer.
    fn panel_content(text: &str, title_fragment: &str) -> String {
        let lines: Vec<&str> = text.lines().collect();
        let frag_chars: Vec<char> = title_fragment.chars().collect();
        // Must be a bordered *header* line ('╭' present) — otherwise an
        // ordinary content line elsewhere that happens to contain the
        // fragment as plain text (e.g. "aggregate of 3 instances", padded
        // with trailing spaces, contains " instances ") would be matched
        // instead of the actual panel titled that way. Caught live: this
        // exact false match once made an "instances" search silently
        // return the service panel's content instead.
        let Some((header_idx, header_chars, frag_pos)) = lines.iter().enumerate().find_map(|(i, l)| {
            if !l.contains('╭') {
                return None;
            }
            let chars: Vec<char> = l.chars().collect();
            let pos = chars.windows(frag_chars.len().max(1)).position(|w| w == frag_chars.as_slice())?;
            Some((i, chars, pos))
        }) else {
            panic!("no panel titled like {title_fragment:?} found in:\n{text}");
        };
        // Several panels can share one physical terminal row (e.g. the
        // service/gpu/session row), so the header line contains multiple
        // '┌...┐' spans — find the specific one that actually contains
        // this fragment, not just the first '╭' in the line.
        let opens: Vec<usize> = header_chars.iter().enumerate().filter(|(_, &c)| c == '╭').map(|(i, _)| i).collect();
        let col_start = *opens.iter().rev().find(|&&o| o <= frag_pos).unwrap_or(&0);
        let col_end = header_chars[col_start..]
            .iter()
            .position(|&c| c == '╮')
            .map(|i| col_start + i + 1)
            .unwrap_or(header_chars.len());

        // The panel's own closing border ('╰' at the same column) marks
        // where its content ends — not just the next blank-ish line, which
        // doesn't reliably occur between adjacent bordered panels.
        let footer_idx = (header_idx + 1..lines.len())
            .find(|&i| lines[i].chars().nth(col_start) == Some('╰'))
            .unwrap_or(lines.len() - 1);

        lines[header_idx..=footer_idx]
            .iter()
            .map(|l| {
                let chars: Vec<char> = l.chars().collect();
                chars.get(col_start..col_end.min(chars.len())).map(|s| s.iter().collect::<String>()).unwrap_or_default()
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    #[test]
    fn stats_panel_shows_discovery_auth_and_confidence_for_a_discovered_instance() {
        let app = single_instance_app();
        let text = render_text(&app, 140, 42).expect("renders");

        assert!(text.contains("systemd vllm.service"), "missing discovery provenance:\n{text}");
        assert!(text.contains("uid association"), "missing confidence label:\n{text}");
        assert!(text.contains("credential accepted"), "missing auth label:\n{text}");
    }

    #[test]
    fn stats_panel_omits_discovery_line_for_explicit_configuration() {
        let settings = Settings { poll: Duration::from_millis(200), history: 16 };
        let defs = vec![InstanceDef {
            name: "explicit".into(),
            kind: crate::config::SourceKind::Direct,
            url: "http://10.0.9.21:8000".into(),
            api_key: None,
            discovered_via: None,
            auth: None,
            confidence: None,
        }];
        let app = app::demo(&settings, defs).expect("demo app builds");
        let text = render_text(&app, 140, 42).expect("renders");
        assert!(text.contains("explicit configuration"), "missing:\n{text}");
    }

    fn no_panel_row_is_corrupted(text: &str) {
        // A sound layout never has a border character appear where a
        // neighboring panel's content should be, and no line should be
        // longer than the rendered width implies (TestBackend already
        // enforces per-cell width, so this mainly guards the panel-slicing
        // assumption itself: every '╭' on a header row must have a
        // matching '╮' later on the same row).
        for line in text.lines() {
            let opens = line.matches('╭').count();
            let closes = line.matches('╮').count();
            assert_eq!(opens, closes, "unbalanced panel borders on line: {line:?}\nfull frame:\n{text}");
        }
    }

    #[test]
    fn renders_at_the_actual_tty1_dimensions_without_panicking() {
        // Measured directly on the real deployment this was built against
        // (`stty -F /dev/tty1 size` → 67 240). This is the size that
        // motivated the whole redesign: the previous fixed/Min()-based
        // layout let the latency panel balloon to ~37 rows of near-empty
        // space here.
        let app = single_instance_app();
        let text = render_text(&app, 240, 67).expect("renders at 240x67");
        no_panel_row_is_corrupted(&text);
        assert!(text.contains("overview"), "wide terminal should show the KPI strip:\n{text}");
        assert!(text.contains(" service "), "missing service panel:\n{text}");
        assert!(text.contains(" gpu "), "missing gpu panel:\n{text}");
        assert!(text.contains(" session "), "missing session panel:\n{text}");
    }

    #[test]
    fn layout_fills_the_full_terminal_height_leaving_no_dead_margin_before_the_footer() {
        // Regression test for a real defect (reported directly against the
        // live TTY1 console): `compute_layout` capped both the graphs and
        // detail rows independently, so their combined height could fall
        // short of the terminal's actual height, leaving the shortfall as
        // dead blank rows between the requests panel and the footer
        // instead of the footer sitting on the terminal's true last row.
        // Now the graphs row always absorbs whatever height the (capped)
        // detail row doesn't use, so the two sum to exactly the available
        // space at any size — verified here, not just at the one real
        // TTY1 size, since the bug scales with any tall-enough terminal.
        let app = single_instance_app();
        for (w, h) in [(240, 67), (140, 50), (90, 35), (110, 40)] {
            let text = render_text(&app, w, h).expect("renders");
            let lines: Vec<&str> = text.lines().collect();
            assert_eq!(lines.len(), h as usize, "render_text should produce exactly one line per terminal row at {w}x{h}");
            let footer_idx = lines
                .iter()
                .rposition(|l| l.contains("vllm-top") && l.contains("quit"))
                .unwrap_or_else(|| panic!("footer line not found at {w}x{h}:\n{text}"));
            assert_eq!(
                footer_idx,
                h as usize - 1,
                "footer should be the terminal's actual last row, not sit above a blank margin, at {w}x{h}:\n{text}"
            );
        }
    }

    #[test]
    fn f_keys_toggle_the_expected_box_visibility_flags() {
        use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
        let mut app = single_instance_app();
        assert_eq!(app.boxes, BoxVisibility::default());

        app.handle_key(KeyEvent::new(KeyCode::F(2), KeyModifiers::NONE));
        assert!(!app.boxes.graphs, "F2 should hide the graphs row");
        assert!(app.boxes.overview && app.boxes.detail && app.boxes.instances && app.boxes.requests, "F2 must not affect other boxes");

        app.handle_key(KeyEvent::new(KeyCode::F(2), KeyModifiers::NONE));
        assert!(app.boxes.graphs, "pressing F2 again should show it again");

        type BoxCheck = (KeyCode, fn(&App) -> bool);
        let checks: [BoxCheck; 4] = [
            (KeyCode::F(1), |a: &App| a.boxes.overview),
            (KeyCode::F(3), |a: &App| a.boxes.detail),
            (KeyCode::F(4), |a: &App| a.boxes.instances),
            (KeyCode::F(5), |a: &App| a.boxes.requests),
        ];
        for (key, get) in checks {
            let before = get(&app);
            app.handle_key(KeyEvent::new(key, KeyModifiers::NONE));
            assert_ne!(get(&app), before, "{key:?} should flip its box's visibility");
        }
    }

    #[test]
    fn hidden_boxes_disappear_from_the_render_and_graphs_absorbs_the_freed_height() {
        let mut app = single_instance_app();
        let baseline = render_text(&app, 140, 50).expect("renders");
        assert!(baseline.contains(" service "));
        assert!(baseline.contains("overview"));

        app.boxes.detail = false;
        let without_detail = render_text(&app, 140, 50).expect("renders");
        no_panel_row_is_corrupted(&without_detail);
        assert!(!without_detail.contains(" service "), "hidden detail row must not render:\n{without_detail}");
        assert!(!without_detail.contains(" gpu "));
        assert!(!without_detail.contains(" session "));
        // Its space must go somewhere, not vanish as a dead margin — the
        // throughput panel (part of the graphs row) should now be taller.
        let throughput_before = panel_content(&baseline, "throughput").lines().count();
        let throughput_after = panel_content(&without_detail, "throughput").lines().count();
        assert!(
            throughput_after > throughput_before,
            "hiding detail should give its space to graphs: {throughput_before} -> {throughput_after} rows"
        );

        app.boxes.overview = false;
        let without_overview = render_text(&app, 140, 50).expect("renders");
        no_panel_row_is_corrupted(&without_overview);
        assert!(!without_overview.contains("overview"), "hidden overview must not render:\n{without_overview}");
    }

    #[test]
    fn full_height_invariant_holds_with_boxes_hidden() {
        // The same "footer on the real last row" guarantee this layout
        // makes by default must keep holding once boxes can be hidden —
        // hiding a box must redistribute its height, never just drop it.
        let mut app = single_instance_app();
        app.boxes.overview = false;
        app.boxes.requests = false;
        for (w, h) in [(240, 67), (140, 50), (90, 35)] {
            let text = render_text(&app, w, h).expect("renders");
            let lines: Vec<&str> = text.lines().collect();
            assert_eq!(lines.len(), h as usize);
            let footer_idx = lines
                .iter()
                .rposition(|l| l.contains("vllm-top") && l.contains("quit"))
                .unwrap_or_else(|| panic!("footer line not found at {w}x{h}:\n{text}"));
            assert_eq!(footer_idx, h as usize - 1, "footer should still reach the last row with boxes hidden, at {w}x{h}:\n{text}");
        }
    }

    #[test]
    fn renders_at_80x24_as_too_small_without_panicking() {
        // Below the enforced minimum (90x35) — must show the clear
        // minimum-size message, not attempt the full dashboard, and must
        // not panic on the small/oddly-shaped area.
        let app = single_instance_app();
        let text = render_text(&app, 80, 24).expect("renders at 80x24");
        assert!(text.contains("too small"), "expected the too-small message:\n{text}");
        assert!(text.contains("80x24"), "expected the actual size to be reported:\n{text}");
    }

    #[test]
    fn renders_at_zero_size_without_panicking() {
        let app = single_instance_app();
        // Must not panic even for a degenerate 0x0 frame (e.g. a resize
        // event reporting an unready terminal).
        let _ = render_text(&app, 0, 0);
    }

    #[test]
    fn renders_at_standard_and_intermediate_sizes_without_panicking() {
        let app = single_instance_app();
        for (w, h) in [(90, 35), (80, 24), (110, 40), (140, 42), (200, 60)] {
            let text = render_text(&app, w, h).expect("renders");
            no_panel_row_is_corrupted(&text);
        }
    }

    #[test]
    fn resize_sequence_does_not_panic_and_stays_uncorrupted() {
        // Simulates a terminal resize: the same App state re-rendered at a
        // sequence of different sizes, as ratatui's real render loop would
        // do on a resize event.
        let app = single_instance_app();
        for (w, h) in [(240, 67), (90, 35), (140, 42), (80, 24), (240, 67)] {
            let text = render_text(&app, w, h).expect("renders");
            no_panel_row_is_corrupted(&text);
        }
    }

    #[test]
    fn long_model_identifier_does_not_corrupt_neighboring_panels() {
        let mut app = single_instance_app();
        let long_name = "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit-and-then-some-extra-suffix-that-keeps-going-well-past-any-reasonable-panel-width".to_string();
        if let Some(snap) = &mut app.runtimes[0].snapshot {
            snap.model = Some(long_name.clone());
        }
        for (w, h) in [(90, 35), (140, 42), (240, 67)] {
            let text = render_text(&app, w, h).expect("renders");
            no_panel_row_is_corrupted(&text);
            // The gpu/session panels to the right of service must still
            // show their own real content — not be blank or overwritten.
            let gpu_block = panel_content(&text, " gpu ");
            assert!(
                gpu_block.contains("gpu0") || gpu_block.contains("unavailable"),
                "gpu panel corrupted by long model name at {w}x{h}:\n{text}"
            );
        }
    }

    #[test]
    fn multiple_gpus_all_render_independently() {
        let mut app = single_instance_app();
        app.gpu_info = vec![
            crate::gpu::GpuInfo {
                index: 0,
                device_name: Some("Intel(R) Arc(TM) Pro B65 Graphics".into()),
                pci_bdf: Some("0000:51:00.0".into()),
                mem_total_mib: Some(32656.0),
                pcie_generation: None,
                pcie_max_link_width: None,
            },
            crate::gpu::GpuInfo {
                index: 1,
                device_name: Some("Intel(R) Arc(TM) Pro B65 Graphics".into()),
                pci_bdf: Some("0000:93:00.0".into()),
                mem_total_mib: Some(32656.0),
                pcie_generation: None,
                pcie_max_link_width: None,
            },
        ];
        app.gpu = vec![
            crate::gpu::GpuStats { index: 0, power_w: Some(6.8), mem_used_mib: Some(29582.0), mem_util_percent: Some(90.5) },
            // GPU 1's live probe "failed" (no dynamic entry) — must not
            // prevent GPU 0 from rendering, and must show GPU 1's static
            // identity with its live fields as unavailable rather than
            // dropping the device entirely.
        ];
        let text = render_text(&app, 240, 67).expect("renders");
        let gpu_block = panel_content(&text, " gpu ");
        assert!(gpu_block.contains("gpu0"), "missing gpu0:\n{gpu_block}");
        assert!(gpu_block.contains("gpu1"), "missing gpu1 despite its live probe failing:\n{gpu_block}");
        assert!(gpu_block.contains("6.8W") && gpu_block.contains("90%"), "gpu0's live stats missing:\n{gpu_block}");
        assert!(gpu_block.contains("power n/a"), "gpu1 should show power n/a, not be silently dropped:\n{gpu_block}");
    }

    #[test]
    fn missing_gpu_telemetry_shows_unavailable_not_blank() {
        let mut app = single_instance_app();
        app.gpu = Vec::new();
        app.gpu_info = Vec::new();
        let text = render_text(&app, 240, 67).expect("renders");
        let gpu_block = panel_content(&text, " gpu ");
        assert!(gpu_block.contains("unavailable"), "expected an explicit unavailable message:\n{gpu_block}");
    }

    fn sample_orchestrator_snapshot() -> crate::orchestrator::Snapshot {
        use crate::orchestrator::{Gateway, Health, MetricsTotals, Scheduler, Snapshot, WorkerHealth};
        use std::collections::BTreeMap;
        let mut workers = BTreeMap::new();
        workers.insert(
            "b0-live-tp1-worker1".to_string(),
            WorkerHealth { status: "healthy".into(), healthy: true, consecutive_failures: 0 },
        );
        workers.insert(
            "b0-live-tp1-worker2".to_string(),
            WorkerHealth { status: "stale".into(), healthy: false, consecutive_failures: 3 },
        );
        Snapshot {
            health: Health {
                status: "healthy".into(),
                ready: true,
                gateway: Gateway { status: "alive".into(), uptime_seconds: 120.0 },
                scheduler: Scheduler {
                    ready: true,
                    status: "ready".into(),
                    queued_work: 0.0,
                    active_work: 1.0,
                    available_workers: 2,
                    total_workers: 2,
                },
                workers,
            },
            metrics: MetricsTotals {
                dispatches_total: 10.0,
                completions_total: 9.0,
                http_requests_total: 50.0,
                authority_validations_total: 2.0,
            },
            fetch_latency: Duration::from_millis(8),
        }
    }

    #[test]
    fn orchestrator_panel_is_absent_by_default_and_detail_row_stays_three_columns() {
        // Regression guard: most deployments will never run one of these,
        // so its complete absence (not an "unavailable" placeholder like
        // the always-present GPU panel) must be the default, unchanged
        // behavior for every existing deployment.
        let app = single_instance_app();
        assert!(app.orchestrator.is_none());
        let text = render_text(&app, 240, 67).expect("renders");
        no_panel_row_is_corrupted(&text);
        assert!(!text.contains(" orchestrator "), "no orchestrator panel should render when none is detected:\n{text}");
    }

    #[test]
    fn orchestrator_panel_renders_gateway_scheduler_and_worker_health_when_detected() {
        let mut app = single_instance_app();
        app.orchestrator = Some(sample_orchestrator_snapshot());
        app.orch_dispatch_rate = 4.2;
        app.orch_hist.push(1.0);
        app.orch_hist.push(4.2);

        let text = render_text(&app, 240, 67).expect("renders");
        no_panel_row_is_corrupted(&text);
        let panel_text = panel_content(&text, " orchestrator ");
        assert!(panel_text.contains("healthy"), "overall gateway status missing:\n{panel_text}");
        assert!(panel_text.contains("process alive"), "gateway process liveness missing:\n{panel_text}");
        assert!(panel_text.contains("ready"), "scheduler status missing:\n{panel_text}");
        assert!(panel_text.contains("2/2 workers"), "worker availability missing:\n{panel_text}");
        assert!(panel_text.contains("4.2/s"), "dispatch rate missing:\n{panel_text}");
        assert!(panel_text.contains("b0-live-tp1-worker1"), "worker1 row missing:\n{panel_text}");
        assert!(panel_text.contains("stale"), "worker2's stale status missing:\n{panel_text}");
        assert!(panel_text.contains("3 consecutive failures"), "worker2's failure count missing:\n{panel_text}");

        // The rest of the detail row must still render alongside it (a
        // 4-column row, not orchestrator replacing the others).
        assert!(text.contains(" service "));
        assert!(text.contains(" gpu "));
        assert!(text.contains(" session "));
    }

    #[test]
    fn unavailable_inference_service_shows_down_not_equivalent_to_healthy() {
        let mut app = single_instance_app();
        app.runtimes[0].last_error = Some("connection refused".into());
        let text = render_text(&app, 240, 67).expect("renders");
        // The header's SVC indicator must reflect the down service...
        assert!(text.contains("SVC down"), "header should show the service as down:\n{text}");
        // ...while MON (the monitor's own render/poll loop) stays "ok" —
        // a healthy monitor correctly reporting a dead service must never
        // look like the monitor itself is broken.
        assert!(text.contains("MON ok"), "monitor health must stay distinct from service health:\n{text}");
        let service_block = panel_content(&text, " service ");
        assert!(service_block.contains("down"), "service panel should show the down state:\n{service_block}");
    }

    #[test]
    fn auth_failure_is_visible_and_distinct_from_metrics_health() {
        let mut app = single_instance_app();
        app.runtimes[0].def.auth = Some(crate::discover::AuthState::RequiredCredentialRejected);
        let text = render_text(&app, 240, 67).expect("renders");
        let service_block = panel_content(&text, " service ");
        assert!(service_block.contains("credential rejected"), "missing auth failure state:\n{service_block}");
        // Metrics collection itself is still fine in this scenario (the
        // rejected credential only affects the discovery-time /v1/models
        // check, not /metrics) — auth failure must not be conflated with
        // metrics failure.
        assert!(service_block.contains("ok"), "metrics health line should be unaffected:\n{service_block}");
    }

    #[test]
    fn aggregate_view_shows_a_connection_rollup_for_multiple_instances() {
        let settings = Settings { poll: Duration::from_millis(200), history: 16 };
        let defs = vec![
            InstanceDef {
                name: "one".into(),
                kind: crate::config::SourceKind::Direct,
                url: "http://10.0.0.1:8000".into(),
                api_key: None,
                discovered_via: None,
                auth: None,
                confidence: None,
            },
            InstanceDef {
                name: "two".into(),
                kind: crate::config::SourceKind::Direct,
                url: "http://10.0.0.2:8000".into(),
                api_key: None,
                discovered_via: None,
                auth: None,
                confidence: None,
            },
        ];
        let app = app::demo(&settings, defs).expect("demo app builds");
        assert_eq!(app.view, View::Aggregate, "2+ instances should default to aggregate view");
        let text = render_text(&app, 240, 67).expect("renders");
        let service_block = panel_content(&text, " service ");
        assert!(service_block.contains("aggregate of 2 instances"), "{service_block}");
        assert!(service_block.contains("svc"), "expected a connection roll-up line:\n{service_block}");
    }

    #[test]
    fn empty_graph_history_shows_a_placeholder_not_a_panic_or_blank_chart() {
        let settings = Settings { poll: Duration::from_millis(200), history: 16 };
        let defs = vec![InstanceDef {
            name: "fresh".into(),
            kind: crate::config::SourceKind::Direct,
            url: "http://127.0.0.1:8000".into(),
            api_key: None,
            discovered_via: None,
            auth: None,
            confidence: None,
        }];
        // App::new (not demo()) starts with genuinely empty history —
        // no polls have completed yet.
        let app = App::new(&settings, defs).expect("app builds");
        let text = render_text(&app, 240, 67).expect("renders");
        no_panel_row_is_corrupted(&text);
        assert!(
            text.contains("collecting samples") || text.contains("waiting for first sample"),
            "expected an explicit empty-history placeholder:\n{text}"
        );
    }

    // -- instances table: wide-terminal column-stretching defect -----------

    fn multi_instance_app_with(names_urls: &[(&str, &str)]) -> App {
        let settings = Settings { poll: Duration::from_millis(200), history: 16 };
        let defs = names_urls
            .iter()
            .map(|(name, url)| InstanceDef {
                name: (*name).into(),
                kind: crate::config::SourceKind::Direct,
                url: (*url).into(),
                api_key: None,
                discovered_via: None,
                auth: None,
                confidence: None,
            })
            .collect();
        app::demo(&settings, defs).expect("demo app builds")
    }

    /// Regression test for the reported defect: at wide terminals, the
    /// instances table's text columns (`Percentage`-based) stretched
    /// proportionally with terminal width, while the one field that
    /// actually benefits from more room (model) was hard-capped at 26
    /// characters regardless of the space available. Verified directly at
    /// 240 cols (the real TTY1 width) before this fix: a short 5-char
    /// instance name reserved ~30 columns of blank padding.
    #[test]
    fn instances_table_model_column_uses_extra_width_at_wide_terminals() {
        let mut app = multi_instance_app_with(&[("local", "http://localhost:8000")]);
        // Longer than the old hard-coded 26-char cap, short enough to fit
        // a 240-wide terminal's Fill column.
        let long_model = "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit";
        if let Some(snap) = &mut app.runtimes[0].snapshot {
            snap.model = Some(long_model.to_string());
        }
        let table = panel_content(&render_text(&app, 240, 67).expect("renders"), " instances ");
        assert!(
            table.contains(long_model),
            "model name should render in full at 240 cols, not truncated to 26 chars:\n{table}"
        );
    }

    fn row_containing<'a>(table: &'a str, needle: &str) -> &'a str {
        table.lines().find(|l| l.contains(needle)).unwrap_or_else(|| panic!("no row containing {needle:?} in:\n{table}"))
    }

    fn first_cell(row: &str) -> &str {
        row.trim_start_matches(['│', ' ']).split_whitespace().next().unwrap_or("")
    }

    #[test]
    fn sorting_orders_rows_by_the_chosen_column_but_keeps_original_index_badges() {
        // btop's own process list works the same way: sorting reorders
        // the rows, but each row still shows its own real identity (PID
        // there, the original 1-based instance index here) — otherwise
        // the existing 1-9 instance-select keys would silently start
        // pointing at the wrong row depending on sort order.
        let mut app = multi_instance_app_with(&[
            ("alpha", "http://localhost:8000"),
            ("bravo", "http://localhost:8001"),
            ("charlie", "http://localhost:8002"),
        ]);
        app.runtimes[0].derived.gen_tps = 10.0;
        app.runtimes[1].derived.gen_tps = 30.0;
        app.runtimes[2].derived.gen_tps = 20.0;
        app.sort_by = SortKey::GenTps;
        app.sort_desc = true;

        let text = render_text(&app, 240, 40).expect("renders");
        let table = panel_content(&text, " instances ");
        let bravo = table.find("bravo").expect("bravo row present");
        let charlie = table.find("charlie").expect("charlie row present");
        let alpha = table.find("alpha").expect("alpha row present");
        assert!(bravo < charlie && charlie < alpha, "expected descending gen_tps order bravo(30) > charlie(20) > alpha(10):\n{table}");

        assert_eq!(first_cell(row_containing(&table, "bravo")), "2", "bravo is originally instance #2");
        assert_eq!(first_cell(row_containing(&table, "charlie")), "3", "charlie is originally instance #3");
        assert_eq!(first_cell(row_containing(&table, "alpha")), "1", "alpha is originally instance #1");

        let header = table.lines().nth(1).expect("column header line");
        assert!(header.contains("gen tok/s*"), "active sort column header should be marked:\n{header}");
        assert!(table.contains("sort: gen tok/s desc"), "panel title should state the active sort:\n{table}");
    }

    #[test]
    fn filter_hides_non_matching_instances_and_shows_the_filter_in_the_title() {
        let mut app = multi_instance_app_with(&[
            ("alpha", "http://localhost:8000"),
            ("bravo", "http://localhost:8001"),
        ]);
        app.filter = "alp".to_string();
        let text = render_text(&app, 240, 40).expect("renders");
        let table = panel_content(&text, " instances ");
        assert!(table.contains("alpha"), "alpha matches the filter:\n{table}");
        assert!(!table.contains("bravo"), "bravo should be hidden by the filter:\n{table}");
        assert!(table.contains("filter: alp"), "panel title should show the active filter:\n{table}");
    }

    #[test]
    fn slash_key_enters_filter_editing_and_captures_typed_text_without_triggering_other_keys() {
        use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
        let mut app = single_instance_app();
        assert!(!app.filter_editing);

        app.handle_key(KeyEvent::new(KeyCode::Char('/'), KeyModifiers::NONE));
        assert!(app.filter_editing);

        for c in "abc".chars() {
            app.handle_key(KeyEvent::new(KeyCode::Char(c), KeyModifiers::NONE));
        }
        assert_eq!(app.filter, "abc");

        // 'q' while filtering must type a literal 'q', not quit — this is
        // the whole point of gating on `filter_editing` first.
        app.handle_key(KeyEvent::new(KeyCode::Char('q'), KeyModifiers::NONE));
        assert_eq!(app.filter, "abcq");
        assert!(!app.should_quit);

        app.handle_key(KeyEvent::new(KeyCode::Backspace, KeyModifiers::NONE));
        assert_eq!(app.filter, "abc");

        app.handle_key(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE));
        assert!(!app.filter_editing);
        assert_eq!(app.filter, "abc", "confirming with Enter should keep the typed text");
    }

    #[test]
    fn esc_while_filtering_discards_the_filter_and_exits_editing() {
        use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
        let mut app = single_instance_app();
        app.handle_key(KeyEvent::new(KeyCode::Char('/'), KeyModifiers::NONE));
        app.handle_key(KeyEvent::new(KeyCode::Char('x'), KeyModifiers::NONE));
        assert_eq!(app.filter, "x");

        app.handle_key(KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE));
        assert!(!app.filter_editing);
        assert!(app.filter.is_empty(), "Esc should discard the in-progress filter, not just stop editing it");
    }

    #[test]
    fn s_cycles_sort_column_and_shift_s_reverses_direction() {
        use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
        let mut app = single_instance_app();
        assert_eq!(app.sort_by, SortKey::Natural);
        assert!(!app.sort_desc);

        app.handle_key(KeyEvent::new(KeyCode::Char('s'), KeyModifiers::NONE));
        assert_eq!(app.sort_by, SortKey::Name);

        app.handle_key(KeyEvent::new(KeyCode::Char('S'), KeyModifiers::SHIFT));
        assert!(app.sort_desc);
        assert_eq!(app.sort_by, SortKey::Name, "reversing direction must not also change the column");
    }

    #[test]
    fn instances_table_bounds_short_fields_instead_of_stretching_them() {
        let app = multi_instance_app_with(&[("local", "http://localhost:8000")]);
        let narrow = panel_content(&render_text(&app, 90, 35).expect("renders"), " instances ");
        let wide = panel_content(&render_text(&app, 240, 67).expect("renders"), " instances ");
        // The header line's "source" column position should be roughly the
        // same distance from the left edge at both sizes — if the
        // preceding text columns were still `Percentage`-based, "source"
        // would drift much further right on the wide terminal.
        let narrow_pos = narrow.lines().next().and_then(|l| l.find("source"));
        let wide_pos = wide.lines().next().and_then(|l| l.find("source"));
        if let (Some(n), Some(w)) = (narrow_pos, wide_pos) {
            assert!(
                w.abs_diff(n) <= 6,
                "'source' column drifted from col {n} (90-wide) to col {w} (240-wide) — \
                 bounded columns shouldn't move much with terminal width"
            );
        }
    }

    #[test]
    fn instances_table_truncates_long_endpoint_cleanly() {
        let app = multi_instance_app_with(&[(
            "local",
            "http://a-very-long-hostname-that-would-otherwise-overflow-the-endpoint-column.example.internal:8000",
        )]);
        // At a size with enough absolute room for the declared column
        // widths (12 columns + spacing genuinely doesn't fit in 90 cols —
        // ratatui's own constraint solver then shrinks every column
        // proportionally, which can clip below the point our own ellipsis
        // was placed; that's graceful degradation under real space
        // pressure, not corruption, and is covered separately below), the
        // truncation must end with an explicit ellipsis rather than an
        // abrupt cut with no indication text was cut off.
        let text = render_text(&app, 240, 67).expect("renders");
        no_panel_row_is_corrupted(&text);
        let table = panel_content(&text, " instances ");
        assert!(table.contains('…'), "expected an ellipsis marking truncation:\n{table}");
        assert!(
            !table.contains("a-very-long-hostname-that-would-otherwise-overflow"),
            "endpoint should have been truncated, not shown in full:\n{table}"
        );
    }

    #[test]
    fn instances_table_does_not_corrupt_at_90_cols_even_with_a_very_long_endpoint() {
        // At the enforced minimum width, 12 columns plus spacing doesn't
        // fit its declared widths — ratatui's constraint solver shrinks
        // columns to fit, which can clip an already-truncated cell (with
        // its ellipsis) further still. That's acceptable degradation as
        // long as nothing panics, overlaps, or corrupts a neighboring
        // column; this deliberately does not assert on the ellipsis
        // surviving, unlike the 240-wide case above.
        let app = multi_instance_app_with(&[(
            "local",
            "http://a-very-long-hostname-that-would-otherwise-overflow-the-endpoint-column.example.internal:8000",
        )]);
        let text = render_text(&app, 90, 35).expect("renders");
        no_panel_row_is_corrupted(&text);
    }

    #[test]
    fn instances_table_handles_multiple_instances_without_overlap() {
        let app = multi_instance_app_with(&[
            ("alpha", "http://10.0.0.1:8000"),
            ("beta", "http://10.0.0.2:8000"),
            ("gamma", "http://10.0.0.3:8000"),
        ]);
        for (w, h) in [(90, 35), (140, 42), (240, 67)] {
            let text = render_text(&app, w, h).expect("renders");
            no_panel_row_is_corrupted(&text);
            let table = panel_content(&text, " instances ");
            for name in ["alpha", "beta", "gamma"] {
                assert!(table.contains(name), "missing instance {name:?} at {w}x{h}:\n{table}");
            }
        }
    }

    #[test]
    fn instances_table_with_zero_instances_does_not_panic() {
        let settings = Settings { poll: Duration::from_millis(200), history: 16 };
        let app = App::new(&settings, Vec::new()).expect("app builds with no instances");
        let text = render_text(&app, 240, 67).expect("renders");
        no_panel_row_is_corrupted(&text);
    }

    #[test]
    fn instances_table_renders_at_80x24_intermediate_and_240x67() {
        let app = multi_instance_app_with(&[("local", "http://localhost:8000")]);
        // 80x24 is below the enforced minimum (90x35) and shows the
        // too-small message instead of the table — included here to
        // confirm that path doesn't panic when reached from a
        // multi-instance app specifically, not just the single-instance
        // one already covered elsewhere.
        for (w, h) in [(80, 24), (110, 40), (240, 67)] {
            let text = render_text(&app, w, h).expect("renders");
            no_panel_row_is_corrupted(&text);
        }
    }

    // -- gradient rendering --------------------------------------------------

    fn as_rgb(c: ratatui::style::Color) -> (u8, u8, u8) {
        match c {
            ratatui::style::Color::Rgb(r, g, b) => (r, g, b),
            other => panic!("expected an Rgb color, got {other:?}"),
        }
    }

    #[test]
    fn gradient_color_goes_from_green_through_amber_to_red() {
        // Exercises the pure implementation directly with an explicit
        // mode, rather than the `gradient_color` wrapper, so this is
        // deterministic regardless of the test process's actual `TERM`.
        let (r0, g0, _) = as_rgb(gradient_color_impl(0.0, false));
        let (r1, g1, _) = as_rgb(gradient_color_impl(0.5, false));
        let (r2, g2, _) = as_rgb(gradient_color_impl(1.0, false));
        assert!(g0 > g2, "green channel should fall from t=0 to t=1: {g0} vs {g2}");
        assert!(r2 > r0, "red channel should rise from t=0 to t=1: {r0} vs {r2}");
        // Amber (the midpoint) has both a high red and a high green
        // channel — distinct from either pure endpoint.
        assert!(r1 > r0, "red channel should already be rising by the midpoint: {r0} vs {r1}");
        assert!(g1 > 0, "amber midpoint should still have a green component: {g1}");
    }

    #[test]
    fn gradient_color_clamps_out_of_range_input() {
        assert_eq!(gradient_color_impl(-1.0, false), gradient_color_impl(0.0, false));
        assert_eq!(gradient_color_impl(2.0, false), gradient_color_impl(1.0, false));
        assert_eq!(gradient_color_impl(-1.0, true), gradient_color_impl(0.0, true));
        assert_eq!(gradient_color_impl(2.0, true), gradient_color_impl(1.0, true));
    }

    #[test]
    fn gradient_color_console_safe_uses_only_named_ansi_colors_in_order() {
        // The raw-console fallback must never emit an Rgb value (the
        // kernel VT layer would just quantize it unpredictably anyway) —
        // only named colors, which map to fixed, correctly-ordered
        // palette slots on any terminal, console included.
        use ratatui::style::Color;
        let low = gradient_color_impl(0.0, true);
        let mid = gradient_color_impl(0.6, true);
        let high = gradient_color_impl(1.0, true);
        assert!(matches!(low, Color::Green));
        assert!(matches!(high, Color::Red));
        assert_ne!(low, mid);
        assert_ne!(mid, high);
        assert_ne!(low, high);
    }

    #[test]
    fn gradient_meter_fills_left_to_right_leaving_the_rest_dim() {
        // Regression-shaped test for the actual btop technique: a
        // half-full meter must show only the *first half* of the
        // gradient (green-to-amber), not the whole bar re-colored by its
        // overall level — i.e. per-column position drives the color, not
        // the ratio as a whole. Span 0 is the "label %" prefix text;
        // spans 1.. are the individual "■" glyph columns.
        let bar_width = 20;
        let line = gradient_meter("x", 0.5, bar_width);
        let glyphs = &line.spans[1..];
        assert!(glyphs.len() >= 10, "expected room for at least 10 bar columns, got {}", glyphs.len());
        let half = glyphs.len() / 2;
        for (i, glyph) in glyphs.iter().enumerate().take(half) {
            assert_ne!(glyph.style.fg, Some(METER_BG), "column {i} should be part of the fill");
        }
        for (i, glyph) in glyphs.iter().enumerate().skip(half) {
            assert_eq!(glyph.style.fg, Some(METER_BG), "column {i} should be unfilled");
        }
        // The filled portion itself must vary — proving a gradient, not a
        // single flat fill color repeated across every filled column.
        let filled_colors: std::collections::HashSet<_> = (0..half).map(|i| glyphs[i].style.fg).collect();
        assert!(filled_colors.len() > 1, "filled columns should show a gradient, not one flat color");
    }

    #[test]
    fn gradient_meter_at_zero_and_full_ratio_does_not_panic() {
        let empty = gradient_meter("x", 0.0, 20);
        let full = gradient_meter("x", 1.0, 20);
        assert!(empty.spans.len() > 1);
        assert!(full.spans.len() > 1);
    }

    #[test]
    fn gradient_meter_uses_the_real_btop_glyph() {
        let line = gradient_meter("x", 0.5, 20);
        for span in &line.spans[1..] {
            assert_eq!(span.content.as_ref(), METER_GLYPH, "meter bar columns should use btop's own glyph");
        }
    }

    #[test]
    fn gradient_meter_handles_a_width_too_narrow_for_any_bar_without_panicking() {
        // The label+percentage prefix alone can exceed a very narrow
        // width — must degrade gracefully (a minimum 1-column bar), not
        // underflow or panic.
        for width in [1, 2, 5] {
            let line = gradient_meter("a fairly long label", 0.5, width);
            assert!(!line.spans.is_empty());
        }
    }

    #[test]
    fn gradient_graph_rows_colors_by_row_position_not_by_value() {
        // btop's real multi-row rule: a row's color comes from its
        // vertical position (top hot, bottom cool), not from the data —
        // so even a perfectly flat series must still show different
        // colors on its top and bottom rows.
        let values = vec![50.0; 8];
        let lines = gradient_graph_rows(&values, 8, 4);
        assert_eq!(lines.len(), 4, "one Line per row of height");
        let top = lines[0].spans[0].style.fg;
        let bottom = lines[3].spans[0].style.fg;
        assert_ne!(top, bottom, "top and bottom rows must differ in color for a flat series");
    }

    #[test]
    fn gradient_graph_rows_height_one_colors_by_value_like_a_sparkline() {
        // btop's height==1 case is a different algorithm from the banded
        // one (there's no "row position" for a single row) — it colors by
        // the data value instead, same as gradient_sparkline.
        let lines = gradient_graph_rows(&[0.0, 0.0, 100.0, 100.0], 4, 1);
        assert_eq!(lines.len(), 1);
        assert_eq!(lines[0].spans.len(), 4);
        assert_ne!(
            lines[0].spans[0].style.fg, lines[0].spans[3].style.fg,
            "a low sample and a high sample must not share a color"
        );
    }

    #[test]
    fn gradient_graph_rows_windows_to_the_available_width() {
        // Only the most recent `width` samples should be drawn — an
        // oversized history shouldn't compress into the graph or panic.
        let values: Vec<f64> = (0..50).map(|i| i as f64).collect();
        let lines = gradient_graph_rows(&values, 10, 3);
        assert_eq!(lines.len(), 3);
        for line in &lines {
            assert_eq!(line.spans.len(), 10, "windowed to the requested width, not the full history");
        }
    }

    #[test]
    fn gradient_graph_rows_handles_empty_history_without_panicking() {
        let lines = gradient_graph_rows(&[], 10, 4);
        assert_eq!(lines.len(), 4);
        for line in &lines {
            assert!(line.spans.is_empty());
        }
    }

    // -- raw-console fallback (verified against a live TTY1's own screen
    // buffer — see `is_raw_console`) -----------------------------------------

    #[test]
    fn border_type_for_avoids_rounded_corners_on_the_raw_console() {
        // Rounded's corners collapse to a generic '+' on the console font
        // (verified); Plain's box-drawing set maps to its native CP437
        // slots correctly.
        assert_eq!(border_type_for(true), BorderType::Plain);
        assert_eq!(border_type_for(false), BorderType::Rounded);
    }

    #[test]
    fn shade_graph_rows_colors_by_row_position_not_by_value() {
        // Same rule as the truecolor version, verified independently for
        // the console-safe implementation.
        let values = vec![50.0; 8];
        let lines = shade_graph_rows(&values, 4);
        assert_eq!(lines.len(), 4);
        let top = lines[0].spans[0].style.fg;
        let bottom = lines[3].spans[0].style.fg;
        assert_ne!(top, bottom, "top and bottom rows must differ in color for a flat series");
    }

    /// The distinct glyphs [`TTY_LEVELS`] can ever produce — derived from
    /// the table itself so this doesn't drift from it, not a separately
    /// maintained list.
    fn tty_glyphs() -> std::collections::HashSet<char> {
        TTY_LEVELS.iter().flatten().copied().collect()
    }

    #[test]
    fn shade_graph_rows_only_emits_verified_safe_glyphs() {
        let glyphs = tty_glyphs();
        let values: Vec<f64> = (0..20).map(|i| i as f64 * 5.0).collect();
        let lines = shade_graph_rows(&values, 3);
        for line in &lines {
            for span in &line.spans {
                let ch = span.content.chars().next().expect("non-empty glyph");
                assert!(glyphs.contains(&ch), "glyph {ch:?} is not one of btop's own tty_mode glyphs");
            }
        }
    }

    #[test]
    fn shade_sparkline_colors_taller_bars_differently_than_shorter_ones() {
        let glyphs = tty_glyphs();
        let (values, peak) = spark(&[0.0, 0.0, 100.0, 100.0]);
        let line = shade_sparkline(&values, peak);
        assert_eq!(line.spans.len(), 4);
        assert_ne!(line.spans[0].style.fg, line.spans[3].style.fg);
        for span in &line.spans {
            let ch = span.content.chars().next().expect("non-empty glyph");
            assert!(glyphs.contains(&ch));
        }
    }

    #[test]
    fn shade_sparkline_packs_two_samples_per_character_like_real_btop_tty_mode() {
        // Verified against btop's actual source (src/btop_draw.cpp:
        // `tty_up`, byte-for-byte identical to `tty_down`): a low sample
        // followed by a high sample must produce btop's own documented
        // transition glyph for level 0 -> level 4, not a flattened
        // one-glyph-per-sample approximation.
        let line = shade_sparkline(&[0, 1000], 1000);
        assert_eq!(line.spans.len(), 2);
        assert_eq!(line.spans[1].content.as_ref(), "▒", "level 0->4 transition should be TTY_LEVELS[0][4]");
    }

    #[test]
    fn throughput_panel_fills_most_of_its_height_with_graph_not_a_thin_chart_line() {
        // Regression guard for the defect this replaced: ratatui's Chart
        // widget drew a couple of thin braille lines inside a much taller
        // panel, leaving most of the panel's height blank. Each series
        // now gets its own full-height gradient_graph_rows block, so most
        // rows of the throughput panel should contain drawn glyphs.
        let app = single_instance_app();
        let text = render_text(&app, 240, 67).expect("renders");
        let panel = panel_content(&text, "throughput");
        let content_rows: Vec<&str> = panel.lines().skip(1).collect();
        let non_blank = content_rows
            .iter()
            .filter(|l| l.trim_matches(['│', ' ']).chars().any(|c| c != ' '))
            .count();
        assert!(
            non_blank * 2 >= content_rows.len(),
            "expected most of the throughput panel's rows to carry graph content, got {non_blank} of {}:\n{panel}",
            content_rows.len()
        );
    }

    #[test]
    fn gradient_sparkline_colors_taller_bars_differently_than_shorter_ones() {
        let (values, peak) = spark(&[0.0, 0.0, 100.0, 100.0]);
        let line = gradient_sparkline(&values, peak);
        assert_eq!(line.spans.len(), 4);
        // The low-value and high-value samples must not render as the
        // same foreground color — that's the whole point of a gradient
        // history graph over a flat-colored one.
        assert_ne!(line.spans[0].style.fg, line.spans[3].style.fg);
    }

    #[test]
    fn gradient_meters_actually_reach_the_rendered_screen() {
        // End-to-end check (not just the pure functions in isolation):
        // renders a real frame and confirms multiple distinct gradient
        // colors actually appear on screen, proving the meters/sparklines
        // are wired into the real draw path, not just unit-tested in a
        // vacuum. Gradients are applied as *foreground* colors (matching
        // btop's own `Meter`/`Graph` — a colored glyph, not a colored
        // background cell), so this checks `fg`, not `bg`.
        let app = single_instance_app();
        let backend = TestBackend::new(240, 67);
        let mut terminal: Terminal<TestBackend> = Terminal::new(backend).expect("terminal");
        terminal.draw(|frame| draw(frame, &app)).expect("draws");
        let buffer = terminal.backend().buffer();
        let mut fgs = std::collections::HashSet::new();
        for y in 0..buffer.area.height {
            for x in 0..buffer.area.width {
                if let ratatui::style::Color::Rgb(r, g, b) = buffer[Position::new(x, y)].style().fg.unwrap_or(ratatui::style::Color::Reset) {
                    fgs.insert((r, g, b));
                }
            }
        }
        assert!(fgs.len() > 3, "expected several distinct gradient colors on screen, found {}", fgs.len());
    }
}
