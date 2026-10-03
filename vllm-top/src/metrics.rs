//! Turn a flat list of Prometheus samples into a typed snapshot, and derive
//! per-second rates from consecutive snapshots.

use crate::promparse::Sample;
use std::collections::BTreeMap;
use std::time::Instant;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Histogram {
    pub count: f64,
    pub sum: f64,
    pub p50: f64,
    pub p99: f64,
    pub avg: f64,
}

/// Which signal families a source actually publishes. Derived from series presence, never from the engine's
/// name: an engine that exports no KV gauge or no latency histograms must show "n/a", not 0.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Has {
    pub kv: bool,
    pub prefix: bool,
    pub ttft: bool,
    pub queue: bool,
    pub e2e: bool,
    pub itl: bool,
}

impl Has {
    pub fn all() -> Has {
        Has { kv: true, prefix: true, ttft: true, queue: true, e2e: true, itl: true }
    }

    /// A family is available in a cluster view when any instance publishes it.
    pub fn or(self, other: Has) -> Has {
        Has {
            kv: self.kv || other.kv,
            prefix: self.prefix || other.prefix,
            ttft: self.ttft || other.ttft,
            queue: self.queue || other.queue,
            e2e: self.e2e || other.e2e,
            itl: self.itl || other.itl,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Snapshot {
    pub has: Has,
    pub model: Option<String>,
    pub running: f64,
    pub waiting: f64,
    pub kv_cache_usage: f64,
    pub prompt_tokens: f64,
    pub generation_tokens: f64,
    pub prompt_tokens_cached: f64,
    pub success_total: f64,
    pub success_by_reason: BTreeMap<String, f64>,
    pub preemptions: f64,
    pub prefix_hits: f64,
    pub prefix_queries: f64,
    pub ttft: Histogram,
    pub queue: Histogram,
    pub e2e: Histogram,
    pub itl: Histogram,
    pub raw_samples: usize,
}

/// Work observed *by this monitor process*, since it started watching this
/// instance — distinct from `Snapshot`'s counters, which are vLLM's own
/// server-lifetime totals (reset only when the vLLM server itself
/// restarts, not when `vllm-top` does). Accumulated as the sum of
/// reset-safe per-poll deltas (via [`delta`]), so a vLLM server restart
/// mid-session degrades gracefully (one interval undercounted, exactly
/// like the existing rate derivation) rather than going negative or
/// crediting the server's pre-existing total as work done this session.
#[derive(Clone, Debug, Default)]
pub struct SessionTotals {
    pub prompt_tokens: f64,
    pub generation_tokens: f64,
    pub requests_completed: f64,
}

impl SessionTotals {
    /// Fold in one more observed transition. Call once per successful poll,
    /// with the same `(prev, cur)` pair used for rate derivation — never on
    /// the first sample (no prior baseline) or a failed poll (nothing new
    /// was actually observed).
    pub fn accumulate(&mut self, prev: &Snapshot, cur: &Snapshot) {
        self.prompt_tokens += delta(prev.prompt_tokens, cur.prompt_tokens);
        self.generation_tokens += delta(prev.generation_tokens, cur.generation_tokens);
        self.requests_completed += delta(prev.success_total, cur.success_total);
    }

    /// Cluster-wide session totals: a plain sum is the correct semantics
    /// here (unlike KV-cache/latency, "tokens processed" is additive
    /// across independent instances).
    pub fn merge(parts: &[&SessionTotals]) -> SessionTotals {
        let mut out = SessionTotals::default();
        for p in parts {
            out.prompt_tokens += p.prompt_tokens;
            out.generation_tokens += p.generation_tokens;
            out.requests_completed += p.requests_completed;
        }
        out
    }
}

/// Everything shown on screen that needs history or rates behind it.
#[derive(Clone, Debug, Default)]
pub struct Derived {
    pub has: Has,
    pub gen_tps: f64,
    pub prompt_tps: f64,
    pub req_per_s: f64,
    pub kv: f64,
    pub running: f64,
    pub waiting: f64,
    pub prefix_hit_rate: Option<f64>,
    pub ttft_p99: f64,
    pub queue_p99: f64,
    pub e2e_p99: f64,
    pub itl_p99: f64,
}

// ---------------------------------------------------------------------------
// sample lookup helpers
// ---------------------------------------------------------------------------

/// vLLM has renamed counters over time (`vllm:prompt_tokens` vs
/// `vllm:prompt_tokens_total`), so accept either spelling.
fn matches(name: &str, base: &str) -> bool {
    name == base || name.strip_suffix("_total") == Some(base)
}

fn sum(samples: &[Sample], base: &str) -> f64 {
    samples
        .iter()
        .filter(|s| matches(&s.name, base))
        .map(|s| s.value)
        .sum()
}

/// True when the family `base` is exported at all (the bare name, `_total`, `_bucket`, `_count`, `_sum`).
fn present(samples: &[Sample], base: &str) -> bool {
    let prefix = format!("{base}_");
    samples.iter().any(|s| s.name == base || s.name.starts_with(&prefix))
}

/// Gauges such as KV cache usage may be exported per rank; take the worst one.
fn max_gauge(samples: &[Sample], base: &str) -> f64 {
    samples
        .iter()
        .filter(|s| matches(&s.name, base))
        .map(|s| s.value)
        .fold(0.0_f64, f64::max)
}

/// Sum a labelled counter per value of `label`, e.g. `finished_reason`.
fn group_sum(samples: &[Sample], base: &str, label: &str) -> BTreeMap<String, f64> {
    let mut out: BTreeMap<String, f64> = BTreeMap::new();
    for s in samples.iter().filter(|s| matches(&s.name, base)) {
        let key = s.label(label).unwrap_or("total").to_string();
        *out.entry(key).or_insert(0.0) += s.value;
    }
    out
}

fn histogram(samples: &[Sample], base: &str) -> Histogram {
    let mut buckets: Vec<(f64, f64)> = Vec::new();
    let mut count = 0.0_f64;
    let mut sum = 0.0_f64;

    for s in samples {
        if let Some(rest) = s.name.strip_suffix("_bucket") {
            if matches(rest, base) {
                let Some(le) = s.label("le").and_then(|v| v.parse::<f64>().ok()) else {
                    continue;
                };
                match buckets.iter_mut().find(|(l, _)| *l == le) {
                    Some((_, v)) => *v += s.value,
                    None => buckets.push((le, s.value)),
                }
            }
        } else if let Some(rest) = s.name.strip_suffix("_count") {
            if matches(rest, base) {
                count += s.value;
            }
        } else if let Some(rest) = s.name.strip_suffix("_sum") {
            if matches(rest, base) {
                sum += s.value;
            }
        }
    }

    buckets.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    if count == 0.0 {
        if let Some((_, last)) = buckets.last() {
            count = *last;
        }
    }

    Histogram {
        count,
        sum,
        p50: quantile(&buckets, count, 0.5),
        p99: quantile(&buckets, count, 0.99),
        avg: if count > 0.0 { sum / count } else { 0.0 },
    }
}

/// Linear interpolation inside cumulative histogram buckets.
fn quantile(buckets: &[(f64, f64)], count: f64, q: f64) -> f64 {
    if buckets.is_empty() || count <= 0.0 {
        return 0.0;
    }
    let target = q * count;
    let mut cumulative = 0.0;
    let mut lower = 0.0;
    for (le, bucket_count) in buckets {
        if *bucket_count <= 0.0 {
            continue;
        }
        let next = cumulative + bucket_count;
        if target <= next {
            if !le.is_finite() {
                // Landed in the +Inf bucket: the previous bound is the best guess.
                return if lower > 0.0 { lower } else { 0.0 };
            }
            let span = next - cumulative;
            if span <= 0.0 {
                return *le;
            }
            let frac = (target - cumulative) / span;
            return lower + (le - lower) * frac;
        }
        cumulative = next;
        lower = if le.is_finite() { *le } else { lower };
    }
    lower
}

// ---------------------------------------------------------------------------
// extraction
// ---------------------------------------------------------------------------

impl Snapshot {
    pub fn extract(samples: &[Sample]) -> Snapshot {
        let model = samples
            .iter()
            .find_map(|s| s.label("model_name"))
            .map(str::to_string);

        let success_by_reason = group_sum(samples, "vllm:request_success", "finished_reason");
        let success_total = if success_by_reason.is_empty() {
            sum(samples, "vllm:request_success")
        } else {
            success_by_reason.values().sum()
        };

        Snapshot {
            has: Has {
                kv: present(samples, "vllm:kv_cache_usage_perc"),
                prefix: present(samples, "vllm:prefix_cache_queries"),
                ttft: present(samples, "vllm:time_to_first_token_seconds"),
                queue: present(samples, "vllm:request_queue_time_seconds"),
                e2e: present(samples, "vllm:e2e_request_latency_seconds"),
                itl: present(samples, "vllm:inter_token_latency_seconds"),
            },
            model,
            running: sum(samples, "vllm:num_requests_running"),
            waiting: sum(samples, "vllm:num_requests_waiting"),
            kv_cache_usage: max_gauge(samples, "vllm:kv_cache_usage_perc"),
            prompt_tokens: sum(samples, "vllm:prompt_tokens"),
            generation_tokens: sum(samples, "vllm:generation_tokens"),
            prompt_tokens_cached: sum(samples, "vllm:prompt_tokens_cached"),
            success_total,
            success_by_reason,
            preemptions: sum(samples, "vllm:num_preemptions"),
            prefix_hits: sum(samples, "vllm:prefix_cache_hits"),
            prefix_queries: sum(samples, "vllm:prefix_cache_queries"),
            ttft: histogram(samples, "vllm:time_to_first_token_seconds"),
            queue: histogram(samples, "vllm:request_queue_time_seconds"),
            e2e: histogram(samples, "vllm:e2e_request_latency_seconds"),
            itl: histogram(samples, "vllm:inter_token_latency_seconds"),
            raw_samples: samples.len(),
        }
    }

    /// Rough cluster-wide view: counters and gauges add up, KV cache usage and
    /// latency quantiles are averaged (weighted by request count) because
    /// summing them would be meaningless.
    pub fn merge(parts: &[&Snapshot]) -> Snapshot {
        let mut out = Snapshot::default();
        let n = parts.len() as f64;
        if parts.is_empty() {
            return out;
        }
        out.model = parts.iter().find_map(|p| p.model.clone());
        out.has = parts.iter().fold(Has::default(), |acc, p| acc.or(p.has));
        for p in parts {
            out.running += p.running;
            out.waiting += p.waiting;
            out.prompt_tokens += p.prompt_tokens;
            out.generation_tokens += p.generation_tokens;
            out.prompt_tokens_cached += p.prompt_tokens_cached;
            out.success_total += p.success_total;
            out.preemptions += p.preemptions;
            out.prefix_hits += p.prefix_hits;
            out.prefix_queries += p.prefix_queries;
            out.raw_samples += p.raw_samples;
            out.kv_cache_usage += p.kv_cache_usage / n;
            for (k, v) in &p.success_by_reason {
                *out.success_by_reason.entry(k.clone()).or_insert(0.0) += v;
            }
        }
        out.ttft = merge_hist(parts.iter().map(|p| &p.ttft));
        out.queue = merge_hist(parts.iter().map(|p| &p.queue));
        out.e2e = merge_hist(parts.iter().map(|p| &p.e2e));
        out.itl = merge_hist(parts.iter().map(|p| &p.itl));
        out
    }

    /// Fraction of prompt tokens that were served from cache.
    pub fn cached_ratio(&self) -> Option<f64> {
        if self.prompt_tokens <= 0.0 {
            None
        } else {
            Some((self.prompt_tokens_cached / self.prompt_tokens).clamp(0.0, 1.0))
        }
    }
}

fn merge_hist<'a>(iter: impl Iterator<Item = &'a Histogram>) -> Histogram {
    let mut out = Histogram::default();
    let mut weight = 0.0_f64;
    for h in iter {
        out.count += h.count;
        out.sum += h.sum;
        if h.count > 0.0 {
            out.p50 += h.p50 * h.count;
            out.p99 += h.p99 * h.count;
            weight += h.count;
        }
    }
    if weight > 0.0 {
        out.p50 /= weight;
        out.p99 /= weight;
    }
    out.avg = if out.count > 0.0 { out.sum / out.count } else { 0.0 };
    out
}

// ---------------------------------------------------------------------------
// rates between two snapshots
// ---------------------------------------------------------------------------

fn delta(prev: f64, cur: f64) -> f64 {
    // Counters reset (server restart) or report out of order: ignore it.
    if cur >= prev {
        (cur - prev).max(0.0)
    } else {
        0.0
    }
}

/// Returns the derived view plus an updated prefix-cache hit rate.
pub fn derive(
    prev: &Snapshot,
    t_prev: Instant,
    cur: &Snapshot,
    now: Instant,
    prev_hit_rate: Option<f64>,
) -> (Derived, Option<f64>) {
    let dt = now.duration_since(t_prev).as_secs_f64();
    let hit_rate = if dt > 0.0 {
        let dq = delta(prev.prefix_queries, cur.prefix_queries);
        if dq > 0.0 {
            Some((delta(prev.prefix_hits, cur.prefix_hits) / dq).clamp(0.0, 1.0))
        } else {
            prev_hit_rate
        }
    } else {
        prev_hit_rate
    };

    let inv_dt = if dt > 0.0 { 1.0 / dt } else { 0.0 };
    let d = Derived {
        has: cur.has,
        gen_tps: delta(prev.generation_tokens, cur.generation_tokens) * inv_dt,
        prompt_tps: delta(prev.prompt_tokens, cur.prompt_tokens) * inv_dt,
        req_per_s: delta(prev.success_total, cur.success_total) * inv_dt,
        kv: cur.kv_cache_usage.clamp(0.0, 1.0),
        running: cur.running,
        waiting: cur.waiting,
        prefix_hit_rate: hit_rate,
        ttft_p99: cur.ttft.p99,
        queue_p99: cur.queue.p99,
        e2e_p99: cur.e2e.p99,
        itl_p99: cur.itl.p99,
    };
    (d, hit_rate)
}

/// First sample: no rates yet, gauges are already valid.
pub fn initial(cur: &Snapshot) -> Derived {
    Derived {
        has: cur.has,
        kv: cur.kv_cache_usage.clamp(0.0, 1.0),
        running: cur.running,
        waiting: cur.waiting,
        ttft_p99: cur.ttft.p99,
        queue_p99: cur.queue.p99,
        e2e_p99: cur.e2e.p99,
        itl_p99: cur.itl.p99,
        ..Derived::default()
    }
}

/// Combine per-instance derived values into a cluster-wide view.
pub fn merge_derived(parts: &[&Derived]) -> Derived {
    let mut out = Derived::default();
    if parts.is_empty() {
        return out;
    }
    let n = parts.len() as f64;
    let mut rate_weight = 0.0_f64;
    let mut lat_weight = 0.0_f64;
    for p in parts {
        out.has = out.has.or(p.has);
        out.gen_tps += p.gen_tps;
        out.prompt_tps += p.prompt_tps;
        out.req_per_s += p.req_per_s;
        out.running += p.running;
        out.waiting += p.waiting;
        out.kv += p.kv;
        out.ttft_p99 += p.ttft_p99;
        out.e2e_p99 += p.e2e_p99;
        out.queue_p99 += p.queue_p99;
        out.itl_p99 += p.itl_p99;
        if let Some(r) = p.prefix_hit_rate {
            rate_weight += r;
            out.prefix_hit_rate = Some(1.0);
        }
        lat_weight += 1.0;
    }
    out.kv /= n;
    if lat_weight > 0.0 {
        out.ttft_p99 /= lat_weight;
        out.e2e_p99 /= lat_weight;
        out.queue_p99 /= lat_weight;
        out.itl_p99 /= lat_weight;
    }
    if out.prefix_hit_rate.is_some() {
        out.prefix_hit_rate = Some(rate_weight / n);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::promparse;

    #[test]
    fn quantile_interpolates() {
        let buckets = vec![(0.1, 5.0), (0.2, 5.0), (f64::INFINITY, 0.0)];
        let q = quantile(&buckets, 10.0, 0.5);
        assert!((q - 0.1).abs() < 1e-9, "{q}");
    }

    #[test]
    fn extract_reads_vllm_metrics() {
        let text = "\
vllm:num_requests_running 3.0
vllm:num_requests_waiting 7.0
vllm:kv_cache_usage_perc 0.42
vllm:prompt_tokens_total 1000.0
vllm:generation_tokens_total 5000.0
vllm:request_success_total{finished_reason=\"stop\",model_name=\"m\"} 10.0
vllm:prefix_cache_hits 80.0
vllm:prefix_cache_queries 100.0
vllm:time_to_first_token_seconds_bucket{le=\"0.5\"} 8.0
vllm:time_to_first_token_seconds_bucket{le=\"+Inf\"} 10.0
vllm:time_to_first_token_seconds_sum 2.0
vllm:time_to_first_token_seconds_count 10.0
";
        let snap = Snapshot::extract(&promparse::parse(text));
        assert_eq!(snap.running, 3.0);
        assert_eq!(snap.waiting, 7.0);
        assert!((snap.kv_cache_usage - 0.42).abs() < 1e-9);
        assert_eq!(snap.success_total, 10.0);
        assert_eq!(snap.success_by_reason["stop"], 10.0);
        assert_eq!(snap.model.as_deref(), Some("m"));
        assert_eq!(snap.ttft.count, 10.0);
        assert!(snap.ttft.p50 <= 0.5);
    }

    #[test]
    fn counter_reset_yields_zero_rate() {
        let prev = Snapshot {
            generation_tokens: 100.0,
            ..Snapshot::default()
        };
        let cur = Snapshot::default();
        let (d, _) = derive(&prev, Instant::now(), &cur, Instant::now(), None);
        assert_eq!(d.gen_tps, 0.0);
    }

    #[test]
    fn session_totals_accumulate_across_polls() {
        let mut session = SessionTotals::default();
        let a = Snapshot { prompt_tokens: 100.0, ..Snapshot::default() };
        let b = Snapshot { prompt_tokens: 150.0, ..Snapshot::default() };
        let c = Snapshot { prompt_tokens: 220.0, ..Snapshot::default() };
        session.accumulate(&a, &b);
        session.accumulate(&b, &c);
        assert_eq!(session.prompt_tokens, 120.0);
    }

    #[test]
    fn session_totals_ignore_server_restart_but_keep_accumulating_after() {
        // vLLM server restarts mid-session: its counter drops back to a
        // small value. The interval spanning the restart is undercounted
        // (same accepted tradeoff as rate derivation), but the server's
        // pre-restart total must never be credited as new session work,
        // and accumulation must resume correctly afterwards.
        let mut session = SessionTotals::default();
        let before_restart = Snapshot { prompt_tokens: 5_000.0, ..Snapshot::default() };
        let just_after_restart = Snapshot { prompt_tokens: 3.0, ..Snapshot::default() };
        let later = Snapshot { prompt_tokens: 10.0, ..Snapshot::default() };
        session.accumulate(&before_restart, &just_after_restart);
        assert_eq!(session.prompt_tokens, 0.0, "must not credit the server's old total");
        session.accumulate(&just_after_restart, &later);
        assert_eq!(session.prompt_tokens, 7.0);
    }

    #[test]
    fn session_totals_merge_sums_across_instances() {
        let a = SessionTotals { prompt_tokens: 10.0, generation_tokens: 20.0, requests_completed: 1.0 };
        let b = SessionTotals { prompt_tokens: 5.0, generation_tokens: 7.0, requests_completed: 2.0 };
        let merged = SessionTotals::merge(&[&a, &b]);
        assert_eq!(merged.prompt_tokens, 15.0);
        assert_eq!(merged.generation_tokens, 27.0);
        assert_eq!(merged.requests_completed, 3.0);
    }

    #[test]
    fn availability_is_derived_from_series_presence_and_merged_as_any() {
        let vllm = promparse::parse(
            "vllm:kv_cache_usage_perc 0.1\nvllm:prefix_cache_queries_total 5\nvllm:e2e_request_latency_seconds_count 3\n\
             vllm:time_to_first_token_seconds_bucket{le=\"1\"} 1\n",
        );
        let a = Snapshot::extract(&vllm);
        assert!(a.has.kv && a.has.prefix && a.has.e2e && a.has.ttft);
        assert!(!a.has.itl && !a.has.queue, "series that are not exported are not available");
        let bare = Snapshot::extract(&promparse::parse("vllm:num_requests_running 1\n"));
        assert_eq!(bare.has, Has::default());
        let merged = Snapshot::merge(&[&a, &bare]);
        assert!(merged.has.kv && merged.has.ttft, "a cluster view has a family when any instance publishes it");
        assert!(!merged.has.itl);
        let d = derive(&bare, Instant::now(), &a, Instant::now(), None).0;
        assert_eq!(d.has, a.has, "derived values carry the snapshot's availability");
    }
}
