//! Application state: one runtime per instance, an aggregate view, and the
//! polling/ingest machinery. Fetches happen on short-lived threads so the UI
//! never blocks on HTTP.

use crate::config::{InstanceDef, Settings};
use crate::gpu::{GpuInfo, GpuStats};
use crate::history::{Histories, Ring};
use crate::metrics::{self, Derived, SessionTotals, Snapshot};
use crate::orchestrator;
use crate::promparse::Sample;
use crate::source::{self, MetricsSource};
use anyhow::Result;
use crossterm::event::{KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::sync::Arc;
use std::time::{Duration, Instant};

type FetchResult = std::result::Result<Vec<Sample>, String>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum View {
    Aggregate,
    Instance(usize),
}

/// Sortable columns of the instances table — btop's own process list
/// supports exactly this (cycle sort column, reverse direction; verified
/// against `src/btop_input.cpp`'s `proc_sorting`/`Proc::sort_vector`).
/// `Natural` (the default) is the original config/discovery order, not a
/// column — so a fleet with no sort applied looks exactly as it always
/// has, and cycling through columns always returns to that starting point.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SortKey {
    Natural,
    Name,
    Running,
    Waiting,
    Kv,
    GenTps,
    ReqPerS,
    TtftP99,
}

impl SortKey {
    const ORDER: [SortKey; 8] = [
        SortKey::Natural,
        SortKey::Name,
        SortKey::Running,
        SortKey::Waiting,
        SortKey::Kv,
        SortKey::GenTps,
        SortKey::ReqPerS,
        SortKey::TtftP99,
    ];

    fn cycle(self, step: isize) -> Self {
        let pos = Self::ORDER.iter().position(|&k| k == self).unwrap_or(0) as isize;
        let len = Self::ORDER.len() as isize;
        Self::ORDER[(pos + step).rem_euclid(len) as usize]
    }

    pub fn label(self) -> &'static str {
        match self {
            SortKey::Natural => "natural",
            SortKey::Name => "name",
            SortKey::Running => "run",
            SortKey::Waiting => "wait",
            SortKey::Kv => "kv",
            SortKey::GenTps => "gen tok/s",
            SortKey::ReqPerS => "req/s",
            SortKey::TtftP99 => "ttft p99",
        }
    }
}

/// Which top-level panel rows are shown — btop's own box-toggle feature
/// (digit keys 1-4 hide/show its cpu/mem/net/proc boxes; `src/btop_input.cpp`,
/// verified against the real source). vllm-top's digits are already taken
/// for instance selection, so this uses F1-F5 instead (`App::handle_key`).
/// All true by default; hiding a row lets `compute_layout` give its space
/// to the graphs row instead of leaving it blank, the same "no dead
/// margin" rule the base layout already follows.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BoxVisibility {
    pub overview: bool,
    pub graphs: bool,
    pub detail: bool,
    pub instances: bool,
    pub requests: bool,
}

impl Default for BoxVisibility {
    fn default() -> Self {
        BoxVisibility { overview: true, graphs: true, detail: true, instances: true, requests: true }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Health {
    Ok,
    Stale,
    Down,
}

pub struct Runtime {
    pub def: InstanceDef,
    pub source: Arc<dyn MetricsSource>,
    rx: Receiver<FetchResult>,
    pub in_flight: bool,
    pub snapshot: Option<Snapshot>,
    pub prev: Option<(Snapshot, Instant)>,
    pub derived: Derived,
    pub hist: Histories,
    pub prefix_hit_rate: Option<f64>,
    pub last_error: Option<String>,
    pub last_ok: Option<Instant>,
    pub started: Instant,
    pub polls: u64,
    last_rediscovery: Option<Instant>,
    /// Work observed since this monitor process started watching this
    /// instance — see [`SessionTotals`]. Distinct from the absolute totals
    /// in `snapshot`, which are vLLM's own server-lifetime counters.
    pub session: SessionTotals,
    /// One-time, best-effort metadata fetched at startup (not re-polled):
    /// vLLM's own reported version, and the served model's configured
    /// context length. `None` when unreachable, unauthenticated for a
    /// server that requires a credential, or not a Direct-kind source
    /// (Prometheus servers don't expose these endpoints themselves).
    pub vllm_version: Option<String>,
    pub max_model_len: Option<u64>,
}

/// Don't re-run discovery (systemctl calls, /proc scans, HTTP probes) on
/// every poll tick while an instance is down — only this often.
const REDISCOVERY_INTERVAL: Duration = Duration::from_secs(30);

impl Runtime {
    /// If this is a locally-discovered instance that's currently down,
    /// see if it reappeared (same identity, e.g. the same systemd unit)
    /// at a different address, and re-point at it. The next poll then
    /// revalidates it for real; this never assumes success on its own.
    fn maybe_rediscover(&mut self) {
        let Some(via) = self.def.discovered_via.clone() else {
            return;
        };
        let due = self
            .last_rediscovery
            .map(|t| t.elapsed() >= REDISCOVERY_INTERVAL)
            .unwrap_or(true);
        if !due {
            return;
        }
        self.last_rediscovery = Some(Instant::now());

        let candidates = crate::discover::discover(self.def.api_key.as_deref());
        let found = match crate::discover::resolve_unique(&candidates, &via) {
            Ok(Some(found)) => found,
            // Nothing currently claims this identity — still down, try
            // again next interval.
            Ok(None) => return,
            // More than one live candidate claims the same identity right
            // now: refuse to guess which one is the real replacement
            // rather than silently reconnecting to an arbitrary one.
            Err(_) => {
                self.last_error = Some(format!(
                    "rediscovery ambiguous: multiple candidates match '{via}'"
                ));
                return;
            }
        };
        if found.url == self.def.url {
            return;
        }
        let url = found.url.clone();
        let auth = found.auth.clone();
        let confidence = found.confidence;
        if let Ok(src) = source::build(self.def.kind, &url, self.def.api_key.as_deref()) {
            self.def.url = url;
            self.def.auth = Some(auth);
            self.def.confidence = Some(confidence);
            self.source = src;
            self.last_error = None;
        }
    }

    pub fn health(&self, poll: Duration) -> Health {
        if self.last_error.is_some() {
            return Health::Down;
        }
        if self.snapshot.is_none() {
            return Health::Stale;
        }
        match self.last_ok {
            Some(t) if t.elapsed() > poll.mul_f32(3.0) => Health::Stale,
            _ => Health::Ok,
        }
    }

    fn ingest(&mut self, result: FetchResult, paused: bool) {
        self.in_flight = false;
        match result {
            Ok(samples) => {
                let snap = Snapshot::extract(&samples);
                let now = Instant::now();
                if !paused {
                    let (derived, rate) = match &self.prev {
                        Some((prev, t_prev)) => {
                            self.session.accumulate(prev, &snap);
                            metrics::derive(prev, *t_prev, &snap, now, self.prefix_hit_rate)
                        }
                        None => (metrics::initial(&snap), self.prefix_hit_rate),
                    };
                    self.prefix_hit_rate = rate;
                    self.derived = derived;
                    self.hist.push(&self.derived);
                    self.prev = Some((snap.clone(), now));
                }
                self.snapshot = Some(snap);
                self.last_ok = Some(now);
                self.last_error = None;
            }
            Err(err) => self.last_error = Some(crate::util::short_error(&err)),
        }
    }
}

pub struct Aggregate {
    pub snapshot: Option<Snapshot>,
    pub derived: Derived,
    pub hist: Histories,
    pub dirty: bool,
    /// Sum of every reporting instance's session totals — see
    /// [`SessionTotals::merge`] for why a plain sum is the right semantics
    /// here (unlike KV-cache/latency, which are averaged in `Snapshot::merge`).
    pub session: SessionTotals,
}

impl Default for Aggregate {
    fn default() -> Self {
        Self {
            snapshot: None,
            derived: Derived::default(),
            hist: Histories::new(60),
            dirty: false,
            session: SessionTotals::default(),
        }
    }
}

impl Aggregate {
    fn new(cap: usize) -> Self {
        Self {
            hist: Histories::new(cap),
            ..Self::default()
        }
    }
}

pub struct App {
    pub runtimes: Vec<Runtime>,
    pub view: View,
    pub paused: bool,
    pub poll: Duration,
    pub started: Instant,
    pub last_poll: Instant,
    pub show_help: bool,
    pub should_quit: bool,
    pub polls: u64,
    pub boxes: BoxVisibility,
    pub sort_by: SortKey,
    pub sort_desc: bool,
    /// Live substring filter (case-insensitive, matched against instance
    /// name) applied to the instances table — btop's own `Proc::filter`.
    pub filter: String,
    /// Whether `/` has put the app into filter-text-entry mode: while
    /// true, ordinary keystrokes are appended to `filter` instead of
    /// triggering their usual action (see `handle_key`).
    pub filter_editing: bool,
    pub agg: Aggregate,
    /// Host-level GPU telemetry, refreshed on its own slow cadence (see
    /// `GPU_POLL_INTERVAL`) — not tied to any single vLLM instance, so it's
    /// not part of `Runtime`/`Aggregate`.
    pub gpu: Vec<GpuStats>,
    /// Static device identity/capacity (name, total memory, PCIe link
    /// state) — fetched once at startup, matched to `gpu` by `index` at
    /// render time. See `gpu::discover_static`.
    pub gpu_info: Vec<GpuInfo>,
    gpu_rx: Option<Receiver<Vec<GpuStats>>>,
    last_gpu_poll: Instant,
    /// Best-effort local orchestrator gateway (see `orchestrator.rs`) — a
    /// separate host-level service, not a vLLM instance. `None` whenever
    /// none is detected (the common case for most deployments), never a
    /// guessed or partial value.
    pub orchestrator: Option<orchestrator::Snapshot>,
    /// Dispatch-rate history, for `draw_orchestrator_panel`'s graph.
    pub orch_hist: Ring,
    pub orch_dispatch_rate: f64,
    orch_prev: Option<(orchestrator::MetricsTotals, Instant)>,
    /// Latest engine observation per worker, and the token rates derived from the last two *distinct*
    /// gateway observations (the gateway refreshes every ~10s, so most polls see the same sample).
    orch_prev_engine: std::collections::BTreeMap<String, orchestrator::EngineStats>,
    pub orch_worker_rates: std::collections::BTreeMap<String, orchestrator::EngineRates>,
    orch_rx: Option<Receiver<Option<orchestrator::Snapshot>>>,
    last_orch_poll: Instant,
}

/// `xpu-smi` takes a few hundred ms per device; polling it every 1s tick
/// like metrics would add needless overhead for data that doesn't change
/// that fast. Refreshed on a background thread either way, so it never
/// blocks rendering regardless of cadence.
const GPU_POLL_INTERVAL: Duration = Duration::from_secs(5);

/// Matches the orchestrator's own background health-poll cadence
/// (10s, per its `HealthManagerPoller`) closely enough that vllm-top's
/// view of it doesn't lag meaningfully behind, without polling more
/// often than the data actually changes.
const ORCH_POLL_INTERVAL: Duration = Duration::from_secs(5);

impl App {
    pub fn new(settings: &Settings, defs: Vec<InstanceDef>) -> Result<App> {
        let mut runtimes = Vec::with_capacity(defs.len());
        for def in defs {
            let src = source::build(def.kind, &def.url, def.api_key.as_deref())?;
            // Best-effort, one-time metadata — never re-fetched, never
            // required. Only meaningful for a Direct-kind vLLM endpoint;
            // a Prometheus server doesn't expose /version or /v1/models
            // itself.
            let (vllm_version, max_model_len) = match def.kind {
                crate::config::SourceKind::Direct => {
                    source::probe_direct_info(&def.url, def.api_key.as_deref())
                }
                crate::config::SourceKind::Prometheus | crate::config::SourceKind::Gateway => (None, None),
            };
            // Sender is created per poll round; the placeholder receiver just
            // sits empty until the first fetch starts.
            let (_tx, rx) = mpsc::channel::<FetchResult>();
            runtimes.push(Runtime {
                source: src,
                def,
                rx,
                in_flight: false,
                snapshot: None,
                prev: None,
                derived: Derived::default(),
                hist: Histories::new(settings.history),
                prefix_hit_rate: None,
                last_error: None,
                last_ok: None,
                started: Instant::now(),
                polls: 0,
                last_rediscovery: None,
                session: SessionTotals::default(),
                vllm_version,
                max_model_len,
            });
        }
        let view = if runtimes.len() == 1 {
            View::Instance(0)
        } else {
            View::Aggregate
        };
        Ok(App {
            agg: Aggregate::new(settings.history),
            runtimes,
            view,
            paused: false,
            poll: settings.poll,
            started: Instant::now(),
            last_poll: Instant::now(),
            show_help: false,
            should_quit: false,
            polls: 0,
            boxes: BoxVisibility::default(),
            sort_by: SortKey::Natural,
            sort_desc: false,
            filter: String::new(),
            filter_editing: false,
            gpu: Vec::new(),
            gpu_info: crate::gpu::discover_static(),
            gpu_rx: None,
            // Fire the first GPU probe on the next tick rather than
            // waiting a full interval.
            last_gpu_poll: Instant::now() - GPU_POLL_INTERVAL,
            orchestrator: None,
            orch_hist: Ring::new(settings.history),
            orch_dispatch_rate: 0.0,
            orch_prev: None,
            orch_prev_engine: Default::default(),
            orch_worker_rates: Default::default(),
            orch_rx: None,
            last_orch_poll: Instant::now() - ORCH_POLL_INTERVAL,
        })
    }

    // -- view selection ----------------------------------------------------

    pub fn title(&self) -> String {
        match self.view {
            View::Aggregate => "aggregate".to_string(),
            View::Instance(i) => self
                .runtimes
                .get(i)
                .map(|r| r.def.name.clone())
                .unwrap_or_default(),
        }
    }

    pub fn snapshot(&self) -> Option<&Snapshot> {
        match self.view {
            View::Aggregate => self.agg.snapshot.as_ref(),
            View::Instance(i) => self.runtimes.get(i)?.snapshot.as_ref(),
        }
    }

    pub fn derived(&self) -> &Derived {
        match self.view {
            View::Aggregate => &self.agg.derived,
            View::Instance(i) => self
                .runtimes
                .get(i)
                .map(|r| &r.derived)
                .unwrap_or(&self.agg.derived),
        }
    }

    pub fn histories(&self) -> &Histories {
        match self.view {
            View::Aggregate => &self.agg.hist,
            View::Instance(i) => self
                .runtimes
                .get(i)
                .map(|r| &r.hist)
                .unwrap_or(&self.agg.hist),
        }
    }

    /// Tokens/requests observed since this monitor started watching —
    /// distinct from `snapshot()`'s absolute, server-lifetime counters.
    pub fn session(&self) -> &SessionTotals {
        match self.view {
            View::Aggregate => &self.agg.session,
            View::Instance(i) => self
                .runtimes
                .get(i)
                .map(|r| &r.session)
                .unwrap_or(&self.agg.session),
        }
    }

    pub fn error(&self) -> Option<String> {
        match self.view {
            View::Aggregate => self
                .runtimes
                .iter()
                .find_map(|r| r.last_error.clone()),
            View::Instance(i) => self.runtimes.get(i)?.last_error.clone(),
        }
    }

    // -- polling -----------------------------------------------------------

    /// Drain finished fetches, refresh the aggregate, maybe start new fetches.
    pub fn tick(&mut self) {
        let paused = self.paused;
        let poll = self.poll;
        let mut ingested = false;
        for rt in &mut self.runtimes {
            if rt.health(poll) == Health::Down {
                rt.maybe_rediscover();
            }
            if !rt.in_flight {
                continue;
            }
            match rt.rx.try_recv() {
                Ok(result) => {
                    rt.ingest(result, paused);
                    ingested = true;
                }
                Err(TryRecvError::Empty) => {}
                Err(TryRecvError::Disconnected) => {
                    rt.in_flight = false;
                    rt.last_error = Some("metrics thread exited unexpectedly".into());
                }
            }
        }

        if ingested {
            self.agg.dirty = true;
        }
        if self.agg.dirty && !self.paused {
            self.refresh_aggregate();
            self.agg.dirty = false;
        }

        if !self.paused && self.last_poll.elapsed() >= self.poll {
            self.start_poll();
        }

        self.maybe_poll_gpu();
        self.maybe_poll_orchestrator();
    }

    fn start_poll(&mut self) {
        for rt in &mut self.runtimes {
            if rt.in_flight {
                continue;
            }
            let (tx, rx) = mpsc::channel::<FetchResult>();
            let src = Arc::clone(&rt.source);
            std::thread::spawn(move || {
                let result = src.fetch().map_err(|e| format!("{e:#}"));
                let _ = tx.send(result);
            });
            // Swap in the receiver belonging to this round's thread.
            rt.rx = rx;
            rt.in_flight = true;
            rt.polls += 1;
        }
        self.last_poll = Instant::now();
        self.polls += 1;
    }

    fn refresh_aggregate(&mut self) {
        // Only instances that have actually reported take part in the roll-up.
        let reporting: Vec<usize> = self
            .runtimes
            .iter()
            .enumerate()
            .filter(|(_, r)| r.snapshot.is_some())
            .map(|(i, _)| i)
            .collect();
        if reporting.is_empty() {
            return;
        }
        let snaps: Vec<&Snapshot> = reporting
            .iter()
            .map(|&i| self.runtimes[i].snapshot.as_ref().unwrap())
            .collect();
        self.agg.snapshot = Some(Snapshot::merge(&snaps));

        let derived: Vec<&Derived> = reporting.iter().map(|&i| &self.runtimes[i].derived).collect();
        self.agg.derived = metrics::merge_derived(&derived);
        self.agg.hist.push(&self.agg.derived);

        let sessions: Vec<&SessionTotals> = reporting.iter().map(|&i| &self.runtimes[i].session).collect();
        self.agg.session = SessionTotals::merge(&sessions);
    }

    /// Kick off a GPU probe on its own bounded background thread if one
    /// isn't already in flight and the interval has elapsed. Never blocks;
    /// results are picked up in `tick()` on a later frame.
    fn maybe_poll_gpu(&mut self) {
        if let Some(rx) = &self.gpu_rx {
            match rx.try_recv() {
                Ok(stats) => {
                    self.gpu = stats;
                    self.gpu_rx = None;
                }
                Err(TryRecvError::Disconnected) => self.gpu_rx = None,
                Err(TryRecvError::Empty) => {}
            }
        }
        if self.gpu_rx.is_none() && self.last_gpu_poll.elapsed() >= GPU_POLL_INTERVAL {
            let (tx, rx) = mpsc::channel();
            let targets: Vec<(u32, Option<String>)> =
                self.gpu_info.iter().map(|i| (i.index, i.pci_bdf.clone())).collect();
            std::thread::spawn(move || {
                let _ = tx.send(crate::gpu::probe(&targets));
            });
            self.gpu_rx = Some(rx);
            self.last_gpu_poll = Instant::now();
        }
    }

    /// Same pattern as `maybe_poll_gpu`: a bounded background probe,
    /// never blocking the render loop, picked up on a later tick. On a
    /// successful snapshot, also derives the dispatch-rate history the
    /// orchestrator panel graphs — the same reset-safe delta-over-time
    /// technique `metrics::derive` uses for vLLM's own rates.
    fn maybe_poll_orchestrator(&mut self) {
        if let Some(rx) = &self.orch_rx {
            match rx.try_recv() {
                Ok(snap) => {
                    if let Some(snap) = &snap {
                        let now = Instant::now();
                        if let Some((prev_metrics, prev_t)) = &self.orch_prev {
                            self.orch_dispatch_rate =
                                orchestrator::MetricsTotals::dispatch_rate(prev_metrics, *prev_t, &snap.metrics, now);
                            self.orch_hist.push(self.orch_dispatch_rate);
                        }
                        self.orch_prev = Some((snap.metrics.clone(), now));
                        self.update_engine_rates(snap);
                    }
                    self.orchestrator = snap;
                    self.orch_rx = None;
                }
                Err(TryRecvError::Disconnected) => self.orch_rx = None,
                Err(TryRecvError::Empty) => {}
            }
        }
        if self.orch_rx.is_none() && self.last_orch_poll.elapsed() >= ORCH_POLL_INTERVAL {
            let (tx, rx) = mpsc::channel();
            std::thread::spawn(move || {
                let _ = tx.send(orchestrator::probe(orchestrator::DEFAULT_URL));
            });
            self.orch_rx = Some(rx);
            self.last_orch_poll = Instant::now();
        }
    }

    /// Derive per-worker token rates from the gateway's engine observations. A worker whose stats
    /// disappear (unknown/stale) drops out so a stale rate is never shown as current.
    fn update_engine_rates(&mut self, snap: &orchestrator::Snapshot) {
        let present: std::collections::BTreeSet<&String> = snap
            .health
            .workers
            .iter()
            .filter(|(_, w)| w.engine_stats.is_some())
            .map(|(name, _)| name)
            .collect();
        self.orch_worker_rates.retain(|name, _| present.contains(name));
        self.orch_prev_engine.retain(|name, _| present.contains(name));
        for (name, worker) in &snap.health.workers {
            let Some(cur) = &worker.engine_stats else { continue };
            match self.orch_prev_engine.get(name) {
                Some(prev) if cur.observed_at > prev.observed_at => {
                    if let Some(rates) = orchestrator::engine_rates(prev, cur) {
                        self.orch_worker_rates.insert(name.clone(), rates);
                    }
                    self.orch_prev_engine.insert(name.clone(), cur.clone());
                }
                Some(_) => {} // same observation as last time: keep the rates we already derived
                None => {
                    self.orch_prev_engine.insert(name.clone(), cur.clone());
                }
            }
        }
    }

    pub fn force_poll(&mut self) {
        self.last_poll = Instant::now() - self.poll;
        self.tick();
    }

    // -- input -------------------------------------------------------------

    pub fn handle_key(&mut self, key: KeyEvent) {
        if key.kind == KeyEventKind::Release {
            return;
        }
        if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('c') {
            self.should_quit = true;
            return;
        }
        // While typing a filter, every ordinary key is text input, not a
        // command — btop's own `Proc::filter` text entry works the same
        // way (`src/btop_input.cpp`: filtering intercepts the input loop
        // until Enter/Esc). This must be checked before the normal match
        // below, or e.g. 'q' while filtering would quit instead of typing.
        if self.filter_editing {
            match key.code {
                KeyCode::Esc => {
                    self.filter.clear();
                    self.filter_editing = false;
                }
                KeyCode::Enter => self.filter_editing = false,
                KeyCode::Backspace => {
                    self.filter.pop();
                }
                KeyCode::Char(c) => self.filter.push(c),
                _ => {}
            }
            return;
        }
        match key.code {
            KeyCode::Char('q') | KeyCode::Esc => {
                if self.show_help {
                    self.show_help = false;
                } else {
                    self.should_quit = true;
                }
            }
            KeyCode::Char('?') => self.show_help = !self.show_help,
            KeyCode::Char('p') => self.paused = !self.paused,
            KeyCode::Char('r') => self.force_poll(),
            KeyCode::Char('a') => self.view = View::Aggregate,
            KeyCode::Tab => self.cycle(1),
            KeyCode::BackTab => self.cycle(-1),
            KeyCode::Right if !self.show_help => self.cycle(1),
            KeyCode::Left if !self.show_help => self.cycle(-1),
            KeyCode::Char('+') | KeyCode::Char('=') => self.adjust_poll(1),
            KeyCode::Char('-') | KeyCode::Char('_') => self.adjust_poll(-1),
            KeyCode::F(1) => self.boxes.overview = !self.boxes.overview,
            KeyCode::F(2) => self.boxes.graphs = !self.boxes.graphs,
            KeyCode::F(3) => self.boxes.detail = !self.boxes.detail,
            KeyCode::F(4) => self.boxes.instances = !self.boxes.instances,
            KeyCode::F(5) => self.boxes.requests = !self.boxes.requests,
            KeyCode::Char('/') => self.filter_editing = true,
            KeyCode::Char('s') => self.sort_by = self.sort_by.cycle(1),
            KeyCode::Char('S') => self.sort_desc = !self.sort_desc,
            KeyCode::Char(c) if c.is_ascii_digit() && c != '0' => {
                let idx = c as usize - '1' as usize;
                if idx < self.runtimes.len() {
                    self.view = View::Instance(idx);
                }
            }
            _ => {}
        }
    }

    fn cycle(&mut self, step: isize) {
        let slots = self.runtimes.len() + 1; // aggregate + each instance
        if slots <= 1 {
            return;
        }
        let current = match self.view {
            View::Aggregate => 0isize,
            View::Instance(i) => i as isize + 1,
        };
        let next = (current + step).rem_euclid(slots as isize) as usize;
        self.view = if next == 0 {
            View::Aggregate
        } else {
            View::Instance(next - 1)
        };
    }

    fn adjust_poll(&mut self, direction: i32) {
        let ms = self.poll.as_millis() as i64;
        let next = (ms + direction as i64 * 250).clamp(250, 10_000);
        self.poll = Duration::from_millis(next as u64);
        self.last_poll = Instant::now() - self.poll;
    }

    pub fn uptime(&self) -> Duration {
        self.started.elapsed()
    }
}

// ---------------------------------------------------------------------------
// synthetic data for `--demo`
// ---------------------------------------------------------------------------

/// Build an app pre-filled with plausible history so one frame can be
/// rendered without a live server.
pub fn demo(settings: &Settings, defs: Vec<InstanceDef>) -> Result<App> {
    let mut app = App::new(settings, defs)?;
    let now = Instant::now();
    let count = app.runtimes.len();
    let last = count.saturating_sub(1);
    let show_one_broken = count > 1;

    // Generate each healthy instance's history, keeping the per-step values so
    // the aggregate series can be rolled up sample by sample.
    let mut series: Vec<Vec<Derived>> = Vec::with_capacity(count);
    for (i, rt) in app.runtimes.iter_mut().enumerate() {
        if i == last && show_one_broken {
            rt.last_error = Some("connection refused".into());
            series.push(Vec::new());
            continue;
        }
        let steps: Vec<Derived> = (0..settings.history)
            .map(|step| demo_derived(i, step))
            .collect();
        for d in &steps {
            rt.hist.push(d);
        }
        rt.derived = steps.last().cloned().unwrap_or_default();

        let snap = Snapshot::extract(&demo_samples(i));
        rt.snapshot = Some(snap.clone());
        rt.prev = Some((snap, now));
        rt.last_ok = Some(now);
        rt.started = now - Duration::from_secs(4 * 3_600 + i as u64 * 600);
        rt.polls = settings.history as u64;
        series.push(steps);
    }

    for step in 0..settings.history {
        let parts: Vec<&Derived> = series.iter().filter_map(|s| s.get(step)).collect();
        let merged = metrics::merge_derived(&parts);
        app.agg.hist.push(&merged);
    }

    app.started = now - Duration::from_secs(5 * 3_600);
    app.polls = settings.history as u64;
    app.refresh_aggregate();
    Ok(app)
}

/// Synthetic per-sample values for instance `i` at history index `step`.
fn demo_derived(i: usize, step: usize) -> Derived {
    let base = 900.0 + i as f64 * 260.0;
    let t = step as f64;
    Derived {
        has: crate::metrics::Has::all(),
        gen_tps: (base + (t * 0.11).sin() * base * 0.35 + t * 1.4).max(0.0),
        prompt_tps: (base * 0.45 + (t * 0.07).cos() * base * 0.2).max(0.0),
        req_per_s: (2.5 + (t * 0.19).sin() * 1.8).max(0.0),
        kv: (0.35 + i as f64 * 0.18 + (t * 0.035).sin() * 0.07).clamp(0.0, 1.0),
        running: (6.0 + (t * 0.13).sin() * 5.0).max(0.0),
        waiting: (3.0 + (t * 0.08).cos() * 3.0).max(0.0),
        prefix_hit_rate: Some((0.7 + (t * 0.02).sin() * 0.15).clamp(0.0, 1.0)),
        ttft_p99: 0.42 + (t * 0.05).sin() * 0.12,
        queue_p99: 0.09 + (t * 0.04).cos() * 0.03,
        e2e_p99: 6.4 + (t * 0.03).sin() * 1.6,
        itl_p99: 0.031 + (t * 0.06).cos() * 0.009,
    }
}

/// Realistic looking exposition payload for the demo frame.
fn demo_samples(idx: usize) -> Vec<Sample> {
    let model = match idx % 3 {
        0 => "unsloth/Llama-3.2-1B-Instruct",
        1 => "meta-llama/Llama-3.1-8B-Instruct",
        _ => "Qwen/Qwen2.5-72B-Instruct",
    };
    let running = 4.0 + idx as f64 * 3.0;
    let waiting = 2.0 + idx as f64;
    let kv = 0.35 + idx as f64 * 0.18;
    let text = format!(
        "\
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{{model_name=\"{model}\"}} {running}
vllm:num_requests_waiting{{model_name=\"{model}\"}} {waiting}
vllm:kv_cache_usage_perc{{model_name=\"{model}\"}} {kv}
vllm:prompt_tokens{{model_name=\"{model}\"}} {}
vllm:generation_tokens{{model_name=\"{model}\"}} {}
vllm:prompt_tokens_cached{{model_name=\"{model}\"}} {}
vllm:request_success{{finished_reason=\"stop\",model_name=\"{model}\"}} {}
vllm:request_success{{finished_reason=\"length\",model_name=\"{model}\"}} {}
vllm:request_success{{finished_reason=\"abort\",model_name=\"{model}\"}} {}
vllm:num_preemptions{{model_name=\"{model}\"}} {}
vllm:prefix_cache_hits{{model_name=\"{model}\"}} 48231
vllm:prefix_cache_queries{{model_name=\"{model}\"}} 61002
vllm:time_to_first_token_seconds_bucket{{le=\"0.1\",model_name=\"{model}\"}} 214
vllm:time_to_first_token_seconds_bucket{{le=\"0.5\",model_name=\"{model}\"}} 908
vllm:time_to_first_token_seconds_bucket{{le=\"1\",model_name=\"{model}\"}} 997
vllm:time_to_first_token_seconds_bucket{{le=\"+Inf\",model_name=\"{model}\"}} 1000
vllm:time_to_first_token_seconds_sum{{model_name=\"{model}\"}} 141.2
vllm:time_to_first_token_seconds_count{{model_name=\"{model}\"}} 1000
vllm:request_queue_time_seconds_bucket{{le=\"0.05\",model_name=\"{model}\"}} 700
vllm:request_queue_time_seconds_bucket{{le=\"0.5\",model_name=\"{model}\"}} 960
vllm:request_queue_time_seconds_bucket{{le=\"+Inf\",model_name=\"{model}\"}} 1000
vllm:request_queue_time_seconds_sum{{model_name=\"{model}\"}} 58.4
vllm:request_queue_time_seconds_count{{model_name=\"{model}\"}} 1000
vllm:e2e_request_latency_seconds_bucket{{le=\"2\",model_name=\"{model}\"}} 320
vllm:e2e_request_latency_seconds_bucket{{le=\"8\",model_name=\"{model}\"}} 830
vllm:e2e_request_latency_seconds_bucket{{le=\"+Inf\",model_name=\"{model}\"}} 1000
vllm:e2e_request_latency_seconds_sum{{model_name=\"{model}\"}} 4120.0
vllm:e2e_request_latency_seconds_count{{model_name=\"{model}\"}} 1000
vllm:inter_token_latency_seconds_bucket{{le=\"0.02\",model_name=\"{model}\"}} 510
vllm:inter_token_latency_seconds_bucket{{le=\"0.06\",model_name=\"{model}\"}} 940
vllm:inter_token_latency_seconds_bucket{{le=\"+Inf\",model_name=\"{model}\"}} 1000
vllm:inter_token_latency_seconds_sum{{model_name=\"{model}\"}} 31.7
vllm:inter_token_latency_seconds_count{{model_name=\"{model}\"}} 1000
",
        820_000.0 + idx as f64 * 41_000.0,
        2_400_000.0 + idx as f64 * 133_000.0,
        512_000.0 + idx as f64 * 9_000.0,
        612.0 + idx as f64 * 77.0,
        381.0 + idx as f64 * 22.0,
        7.0 + idx as f64,
        3.0 + idx as f64,
    );
    crate::promparse::parse(&text)
}
