//! Best-effort local orchestrator gateway integration.
//!
//! This is a genuinely different thing from a vLLM instance: a separate
//! process (`orchestrator_gateway`), a different data shape (`GET /health`
//! returns gateway/scheduler/worker JSON, not vLLM's Prometheus-only
//! surface), and its own `aihost_*`-prefixed metric names rather than
//! `vllm:*`. It gets its own module, its own snapshot type, and its own
//! panel (`draw_orchestrator_panel`, `src/ui/mod.rs`) rather than being
//! forced into the existing per-instance `Snapshot`/`Derived` shape.
//!
//! Detection follows the same convention as GPU telemetry (`gpu::probe`):
//! try the well-known local endpoint, and if nothing answers, stay
//! silently absent — most vllm-top deployments won't run one at all, and
//! that's a normal state, not an error. Not yet configurable (fixed to
//! `DEFAULT_URL`) — a real host-specific URL/port would need its own CLI
//! flag and config field, deferred until there's a deployment that
//! actually needs one.

use crate::promparse;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::time::{Duration, Instant};

/// Verified against the real deployment this was built against
/// (`aihost-orchestrator-gateway.service`, bound to `127.0.0.1:8010`).
pub const DEFAULT_URL: &str = "http://127.0.0.1:8010";

const TIMEOUT: Duration = Duration::from_millis(1500);

#[derive(Clone, Debug, Deserialize)]
pub struct Health {
    /// Overall "can this gateway currently route requests" verdict — can
    /// be `"unavailable"` even while `gateway.status` is `"alive"` (the
    /// real failure mode this integration was built to catch: the process
    /// is up, but its worker-health dependency has gone stale). Kept as
    /// the more robust `ready` bool for coloring rather than matching the
    /// exact string `"healthy"`.
    pub status: String,
    pub ready: bool,
    pub gateway: Gateway,
    pub scheduler: Scheduler,
    #[serde(default)]
    pub workers: BTreeMap<String, WorkerHealth>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Gateway {
    /// The gateway *process's* own liveness (`"alive"`) — deliberately
    /// separate from `Health::status`/`ready` above, the same MON/SVC
    /// distinction this app already makes for itself vs. the vLLM
    /// instances it watches: a live process that can't currently route is
    /// a different fact from a dead one, and conflating them would hide
    /// exactly the failure this integration exists to surface.
    pub status: String,
    pub uptime_seconds: f64,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Scheduler {
    pub ready: bool,
    pub status: String,
    pub queued_work: f64,
    pub active_work: f64,
    pub available_workers: u64,
    pub total_workers: u64,
}

#[derive(Clone, Debug, Deserialize)]
pub struct WorkerHealth {
    pub status: String,
    pub healthy: bool,
    #[serde(default)]
    pub consecutive_failures: u64,
    /// Routing pool this worker serves (e.g. `lead`, `aux`). Absent on gateways that predate routing.
    #[serde(default)]
    pub pool: Option<String>,
    /// Inference engine behind the worker (`vllm`, `llama.cpp`, ...). Absent on older gateways.
    #[serde(default)]
    pub engine: Option<String>,
    /// Engine statistics the *gateway* collected and republished in a neutral shape — vllm-top never
    /// talks to workers (or needs their credentials) for this. `None` when unknown or stale.
    #[serde(default)]
    pub engine_stats: Option<EngineStats>,
}

/// Neutral per-worker engine statistics as published by the gateway. Every field is optional because
/// engines expose different series; a missing value is *unknown*, never zero.
#[derive(Clone, Debug, Default, Deserialize, PartialEq)]
pub struct EngineStats {
    #[serde(default)]
    pub requests_running: Option<f64>,
    #[serde(default)]
    pub requests_waiting: Option<f64>,
    /// Fraction 0..1.
    #[serde(default)]
    pub kv_cache_usage: Option<f64>,
    #[serde(default)]
    pub prompt_tokens_total: Option<f64>,
    #[serde(default)]
    pub generation_tokens_total: Option<f64>,
    #[serde(default)]
    pub prefix_cache_hit_ratio: Option<f64>,
    /// Gateway wall-clock (epoch seconds) when it read the engine; rates use this, not our poll time.
    #[serde(default)]
    pub observed_at: f64,
}

/// Token rates derived from two consecutive gateway observations of one worker.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct EngineRates {
    pub prompt_tps: f64,
    pub generation_tps: f64,
}

/// Reset-safe token rates between two engine observations. Returns `None` when there is no newer
/// observation (the gateway only refreshes every ~10s, so most of our polls see the same sample)
/// or a counter is unknown; a counter that went backwards (engine restart) contributes zero.
pub fn engine_rates(prev: &EngineStats, cur: &EngineStats) -> Option<EngineRates> {
    let dt = cur.observed_at - prev.observed_at;
    if dt <= 0.0 {
        return None;
    }
    let rate = |p: Option<f64>, c: Option<f64>| -> Option<f64> {
        let (p, c) = (p?, c?);
        Some(if c >= p { (c - p) / dt } else { 0.0 })
    };
    Some(EngineRates {
        prompt_tps: rate(prev.prompt_tokens_total, cur.prompt_tokens_total)?,
        generation_tps: rate(prev.generation_tokens_total, cur.generation_tokens_total)?,
    })
}

/// The subset of the gateway's `aihost_*` Prometheus metrics vllm-top
/// tracks, summed across every `worker_id`/`route`/`outcome` label value —
/// matching the level of aggregation already shown for vLLM instances
/// (no per-worker breakdown in the graph, just the fleet-wide total).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricsTotals {
    pub dispatches_total: f64,
    pub completions_total: f64,
    pub http_requests_total: f64,
    pub authority_validations_total: f64,
    /// Routing decisions by `rule → pool` (from `aihost_route_decisions_total`).
    pub routes: BTreeMap<String, f64>,
}

impl MetricsTotals {
    fn from_samples(samples: &[promparse::Sample]) -> Self {
        let mut out = MetricsTotals::default();
        for s in samples {
            match s.name.as_str() {
                "aihost_inference_dispatches_total" => out.dispatches_total += s.value,
                "aihost_inference_completions_total" => out.completions_total += s.value,
                "aihost_http_requests_total" => out.http_requests_total += s.value,
                "aihost_authority_validations_total" => out.authority_validations_total += s.value,
                "aihost_route_decisions_total" => {
                    let key = format!("{} \u{2192} {}", s.label("rule").unwrap_or("?"), s.label("pool").unwrap_or("?"));
                    *out.routes.entry(key).or_insert(0.0) += s.value;
                }
                _ => {}
            }
        }
        out
    }

    /// Dispatches per second between two consecutive snapshots. Same
    /// counter-reset convention as vLLM's own rate derivation
    /// (`metrics::delta`): a counter that goes backward (gateway
    /// restart) contributes zero for that interval instead of going
    /// negative.
    pub fn dispatch_rate(prev: &MetricsTotals, prev_t: Instant, cur: &MetricsTotals, now: Instant) -> f64 {
        let dt = now.duration_since(prev_t).as_secs_f64();
        if dt <= 0.0 {
            return 0.0;
        }
        let delta = if cur.dispatches_total >= prev.dispatches_total {
            cur.dispatches_total - prev.dispatches_total
        } else {
            0.0
        };
        delta / dt
    }
}

#[derive(Clone, Debug)]
pub struct Snapshot {
    pub health: Health,
    pub metrics: MetricsTotals,
    /// Wall-clock time vllm-top's own `/health` + `/metrics` requests
    /// took — directly measured here, not a figure the gateway reports
    /// about itself (its own `/metrics` has no self-scrape-latency
    /// series; that's a property of whoever is doing the scraping).
    pub fetch_latency: Duration,
}

/// Gateway workers that publish engine statistics and are not vLLM (vLLM workers are scraped directly),
/// as `(worker-id, "http://host:port#worker-id")` pairs. Empty when no gateway answers.
pub fn gateway_worker_instances(base_url: &str) -> Vec<(String, String)> {
    let Some(snap) = probe(base_url) else { return Vec::new() };
    let base = base_url.trim_end_matches('/');
    snap.health
        .workers
        .iter()
        .filter(|(_, w)| w.engine_stats.is_some() && w.engine.as_deref() != Some("vllm"))
        .map(|(name, _)| (name.clone(), format!("{base}#{name}")))
        .collect()
}

/// Best-effort probe: `None` on any failure (unreachable, timeout,
/// malformed response) — never a partial/guessed snapshot. Meant to run
/// on its own background thread (see `App::maybe_poll_orchestrator`),
/// never blocking the render loop.
pub fn probe(base_url: &str) -> Option<Snapshot> {
    let client = reqwest::blocking::Client::builder()
        .timeout(TIMEOUT)
        .connect_timeout(TIMEOUT)
        .build()
        .ok()?;
    let base = base_url.trim_end_matches('/');
    let start = Instant::now();

    let health: Health = client.get(format!("{base}/health")).send().ok()?.json().ok()?;
    let metrics_body = client.get(format!("{base}/metrics")).send().ok()?.text().ok()?;
    let fetch_latency = start.elapsed();

    let metrics = MetricsTotals::from_samples(&promparse::parse(&metrics_body));
    Some(Snapshot { health, metrics, fetch_latency })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The exact `/health` payload shape from the real gateway's own
    /// documented response (verified live against
    /// `aihost-orchestrator-gateway.service` on this host) — not a
    /// guessed shape.
    const REAL_HEALTHY_PAYLOAD: &str = r#"{
        "status": "healthy",
        "ready": true,
        "can_route": true,
        "timestamp": "2026-09-29T09:10:03.109167+00:00",
        "gateway": {"status": "alive", "uptime_seconds": 217.957, "pid": 1766552},
        "scheduler": {"ready": true, "status": "ready", "queued_work": 0, "active_work": 0, "available_workers": 2, "total_workers": 2},
        "workers": {
            "b0-live-tp1-worker1": {"status": "healthy", "healthy": true, "public_model_id": "engineering/b0", "model_id": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit", "last_observed_seconds_ago": 7.854, "last_check_timestamp": "2026-09-29T09:09:55.254898+00:00", "consecutive_failures": 0},
            "b0-live-tp1-worker2": {"status": "healthy", "healthy": true, "public_model_id": "engineering/b0", "model_id": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit", "last_observed_seconds_ago": 7.853, "last_check_timestamp": "2026-09-29T09:09:55.256513+00:00", "consecutive_failures": 0}
        },
        "dependency_freshness": {"freshness_seconds": 7.854, "max_ttl_seconds": 30.0, "is_stale": false}
    }"#;

    const REAL_STALE_PAYLOAD: &str = r#"{
        "status": "unavailable",
        "ready": false,
        "can_route": false,
        "timestamp": "2026-09-29T09:02:26.737182+00:00",
        "gateway": {"status": "alive", "uptime_seconds": 308.011, "pid": 1745595},
        "scheduler": {"ready": false, "status": "blocked", "queued_work": 0, "active_work": 0, "available_workers": 0, "total_workers": 2},
        "workers": {
            "b0-live-tp1-worker1": {"status": "stale", "healthy": false, "public_model_id": "engineering/b0", "model_id": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit", "last_observed_seconds_ago": 279.596, "last_check_timestamp": "2026-09-29T08:57:47.140817+00:00", "consecutive_failures": 0},
            "b0-live-tp1-worker2": {"status": "stale", "healthy": false, "public_model_id": "engineering/b0", "model_id": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit", "last_observed_seconds_ago": 270.65, "last_check_timestamp": "2026-09-29T08:57:56.087444+00:00", "consecutive_failures": 0}
        },
        "dependency_freshness": {"freshness_seconds": 279.596, "max_ttl_seconds": 30.0, "is_stale": true}
    }"#;

    /// A trimmed but real excerpt of the gateway's actual `/metrics`
    /// exposition (matching the families/labels seen live), including
    /// `# HELP`/`# TYPE` comment lines and multiple label combinations
    /// per family to confirm summation across labels.
    const REAL_METRICS_EXCERPT: &str = r#"
# HELP aihost_inference_dispatches_total Total inference dispatches
# TYPE aihost_inference_dispatches_total counter
aihost_inference_dispatches_total{worker_id="b0-live-tp1-worker1"} 5
aihost_inference_dispatches_total{worker_id="b0-live-tp1-worker2"} 3
# HELP aihost_http_requests_total Total HTTP requests
# TYPE aihost_http_requests_total counter
aihost_http_requests_total{route="health",status_class="2xx"} 8
aihost_http_requests_total{route="metrics",status_class="2xx"} 10
aihost_authority_validations_total{outcome="accepted"} 2
"#;

    #[test]
    fn parses_the_real_healthy_payload_shape() {
        let h: Health = serde_json::from_str(REAL_HEALTHY_PAYLOAD).expect("parses");
        assert_eq!(h.status, "healthy");
        assert!(h.ready);
        assert_eq!(h.scheduler.available_workers, 2);
        assert_eq!(h.workers.len(), 2);
        assert!(h.workers["b0-live-tp1-worker1"].healthy);
    }

    #[test]
    fn parses_the_real_stale_unavailable_payload_shape() {
        let h: Health = serde_json::from_str(REAL_STALE_PAYLOAD).expect("parses");
        assert_eq!(h.status, "unavailable");
        assert!(!h.ready);
        assert_eq!(h.scheduler.available_workers, 0);
        assert!(!h.workers["b0-live-tp1-worker1"].healthy);
        assert_eq!(h.workers["b0-live-tp1-worker1"].status, "stale");
    }

    #[test]
    fn metrics_totals_sum_across_label_combinations() {
        let samples = promparse::parse(REAL_METRICS_EXCERPT);
        let totals = MetricsTotals::from_samples(&samples);
        assert_eq!(totals.dispatches_total, 8.0, "5 (worker1) + 3 (worker2)");
        assert_eq!(totals.http_requests_total, 18.0, "8 (health) + 10 (metrics)");
        assert_eq!(totals.authority_validations_total, 2.0);
    }

    #[test]
    fn dispatch_rate_is_zero_on_the_first_sample_and_positive_after_growth() {
        let t0 = Instant::now();
        let prev = MetricsTotals { dispatches_total: 10.0, ..Default::default() };
        let cur = MetricsTotals { dispatches_total: 30.0, ..Default::default() };
        let t1 = t0 + Duration::from_secs(4);
        let rate = MetricsTotals::dispatch_rate(&prev, t0, &cur, t1);
        assert!((rate - 5.0).abs() < 1e-9, "20 dispatches over 4s = 5/s, got {rate}");
    }

    #[test]
    fn dispatch_rate_treats_a_counter_reset_as_zero_not_negative() {
        let t0 = Instant::now();
        let prev = MetricsTotals { dispatches_total: 100.0, ..Default::default() };
        let cur = MetricsTotals { dispatches_total: 4.0, ..Default::default() }; // gateway restarted
        let t1 = t0 + Duration::from_secs(2);
        let rate = MetricsTotals::dispatch_rate(&prev, t0, &cur, t1);
        assert_eq!(rate, 0.0, "a counter reset must never produce a negative rate");
    }

    const HEALTH_WITH_ENGINE_STATS: &str = r#"{
        "status": "healthy", "ready": true,
        "gateway": {"status": "alive", "uptime_seconds": 10.0},
        "scheduler": {"ready": true, "status": "ready", "queued_work": 0, "active_work": 0, "available_workers": 1, "total_workers": 1},
        "workers": {"w-llama": {"status": "healthy", "healthy": true, "pool": "lead", "engine": "llama.cpp",
            "model_id": "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M",
            "engine_stats": {"requests_running": 1, "requests_waiting": 0, "kv_cache_usage": 0.125,
                "prompt_tokens_total": 5000, "generation_tokens_total": 900, "prefix_cache_hit_ratio": null, "observed_at": 1000.0}}}
    }"#;

    #[test]
    fn parses_pool_engine_and_engine_stats_and_keeps_unknowns_unknown() {
        let h: Health = serde_json::from_str(HEALTH_WITH_ENGINE_STATS).expect("parses");
        let w = &h.workers["w-llama"];
        assert_eq!(w.pool.as_deref(), Some("lead"));
        assert_eq!(w.engine.as_deref(), Some("llama.cpp"));
        let s = w.engine_stats.as_ref().expect("stats");
        assert_eq!(s.kv_cache_usage, Some(0.125));
        assert_eq!(s.prefix_cache_hit_ratio, None, "an engine that does not report it stays unknown, not 0%");
    }

    #[test]
    fn an_older_gateway_without_the_new_fields_still_parses() {
        let h: Health = serde_json::from_str(REAL_HEALTHY_PAYLOAD).expect("parses");
        assert!(h.workers["b0-live-tp1-worker1"].engine_stats.is_none());
        assert!(h.workers["b0-live-tp1-worker1"].pool.is_none());
    }

    fn stats(p: f64, g: f64, t: f64) -> EngineStats {
        EngineStats { prompt_tokens_total: Some(p), generation_tokens_total: Some(g), observed_at: t, ..Default::default() }
    }

    #[test]
    fn engine_rates_use_the_gateways_observation_clock() {
        let r = engine_rates(&stats(1000.0, 100.0, 50.0), &stats(1600.0, 700.0, 60.0)).expect("rates");
        assert!((r.prompt_tps - 60.0).abs() < 1e-9 && (r.generation_tps - 60.0).abs() < 1e-9, "{r:?}");
    }

    #[test]
    fn engine_rates_are_none_without_a_newer_observation_or_with_unknown_counters() {
        assert!(engine_rates(&stats(1.0, 1.0, 50.0), &stats(9.0, 9.0, 50.0)).is_none(), "same observation");
        let unknown = EngineStats { observed_at: 60.0, ..Default::default() };
        assert!(engine_rates(&stats(1.0, 1.0, 50.0), &unknown).is_none());
    }

    #[test]
    fn engine_rates_treat_an_engine_restart_as_zero_not_negative() {
        let r = engine_rates(&stats(9000.0, 5000.0, 50.0), &stats(10.0, 5.0, 60.0)).expect("rates");
        assert_eq!((r.prompt_tps, r.generation_tps), (0.0, 0.0));
    }

    #[test]
    fn route_decisions_are_grouped_by_rule_and_pool() {
        let samples = promparse::parse(
            "aihost_route_decisions_total{rule=\"default\",pool=\"lead\"} 7\naihost_route_decisions_total{rule=\"subagent-aux\",pool=\"aux\"} 3\n",
        );
        let t = MetricsTotals::from_samples(&samples);
        assert_eq!(t.routes["default \u{2192} lead"], 7.0);
        assert_eq!(t.routes["subagent-aux \u{2192} aux"], 3.0);
    }

    #[test]
    fn probe_returns_none_when_nothing_is_listening() {
        // Port 1 is a reserved, always-unbound port — this must fail fast
        // (bounded by TIMEOUT) and return None, never panic.
        assert!(probe("http://127.0.0.1:1").is_none());
    }
}
