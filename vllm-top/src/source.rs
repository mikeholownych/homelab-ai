use crate::config::SourceKind;
use crate::promparse::{self, Sample};
use anyhow::{bail, Context, Result};
use std::sync::Arc;
use std::time::Duration;

/// A place samples can be pulled from.
pub trait MetricsSource: Send + Sync {
    fn fetch(&self) -> Result<Vec<Sample>>;
}

pub fn build(kind: SourceKind, url: &str, api_key: Option<&str>) -> Result<Arc<dyn MetricsSource>> {
    crate::config::check_url(kind, url)?;
    let client = client()?;
    let api_key = api_key.map(|s| s.to_string());
    Ok(match kind {
        SourceKind::Direct => Arc::new(DirectSource {
            url: url.to_string(),
            client,
            api_key,
        }),
        SourceKind::Limited => Arc::new(LimitedSource { url: url.to_string(), client }),
        SourceKind::Ollama => Arc::new(OllamaSource { url: url.to_string(), client }),
        SourceKind::Gateway => {
            let (base, worker) = url.split_once('#').unwrap_or((url, ""));
            Arc::new(GatewaySource { base: base.to_string(), worker: worker.to_string(), client })
        }
        SourceKind::Prometheus => Arc::new(PrometheusSource {
            url: url.to_string(),
            client,
            api_key,
        }),
    })
}

/// A discovered OpenAI-compatible server without a recognized metrics schema.
/// Poll only its model-list endpoint and report liveness with all metrics absent.
struct LimitedSource {
    url: String,
    client: reqwest::blocking::Client,
}

impl MetricsSource for LimitedSource {
    fn fetch(&self) -> Result<Vec<Sample>> {
        let endpoint = format!("{}/v1/models", self.url.trim_end_matches('/'));
        let response = self.client.get(&endpoint).send().with_context(|| format!("GET {endpoint}"))?;
        if response.status().is_success() || response.status().as_u16() == 401 || response.status().as_u16() == 403 {
            return Ok(Vec::new());
        }
        response.error_for_status().with_context(|| format!("GET {endpoint}"))?;
        Ok(Vec::new())
    }
}

/// An Ollama server. `/api/ps` is the only live state it publishes: which models are loaded and
/// how much of each sits in GPU memory. There are no request or token counters, so every rate stays
/// absent (`n/a`), never zero.
struct OllamaSource {
    url: String,
    client: reqwest::blocking::Client,
}

impl MetricsSource for OllamaSource {
    fn fetch(&self) -> Result<Vec<Sample>> {
        let endpoint = format!("{}/api/ps", self.url.trim_end_matches('/'));
        let body: serde_json::Value = self
            .client
            .get(&endpoint)
            .send()
            .and_then(|r| r.error_for_status())
            .with_context(|| format!("GET {endpoint}"))?
            .json()
            .with_context(|| format!("decode {endpoint}"))?;
        Ok(samples_from_ollama_ps(&body))
    }
}

pub fn samples_from_ollama_ps(body: &serde_json::Value) -> Vec<Sample> {
    let mut out = Vec::new();
    for model in body.get("models").and_then(serde_json::Value::as_array).into_iter().flatten() {
        let Some(name) = model.get("name").or_else(|| model.get("model")).and_then(serde_json::Value::as_str) else {
            continue;
        };
        let labels = std::collections::BTreeMap::from([("model_name".to_string(), name.to_string())]);
        out.push(Sample { name: "ollama:model_loaded".into(), labels: labels.clone(), value: 1.0 });
        for (field, series) in [("size", "ollama:model_size_bytes"), ("size_vram", "ollama:model_vram_bytes")] {
            if let Some(value) = model.get(field).and_then(serde_json::Value::as_f64) {
                out.push(Sample { name: series.into(), labels: labels.clone(), value });
            }
        }
    }
    out
}

/// One-time, best-effort metadata for a Direct-kind instance: vLLM's own
/// reported version (`/version`, unauthenticated on every vLLM deployment
/// observed) and the served model's configured context length
/// (`/v1/models`, which — like every `/v1` endpoint — needs a credential
/// when the server requires one). Never retried on a poll cadence; called
/// once at startup. Both fields are `None` on any failure, missing
/// credential, or unexpected response shape — never guessed.
pub fn probe_direct_info(url: &str, api_key: Option<&str>) -> (Option<String>, Option<u64>) {
    let Ok(client) = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(1500))
        .connect_timeout(Duration::from_millis(1500))
        .build()
    else {
        return (None, None);
    };
    let base = url.trim_end_matches('/');

    #[derive(serde::Deserialize)]
    struct VersionResponse {
        version: String,
    }
    let version = client
        .get(format!("{base}/version"))
        .send()
        .ok()
        .filter(|r| r.status().is_success())
        .and_then(|r| r.json::<VersionResponse>().ok())
        .map(|v| v.version);

    #[derive(serde::Deserialize)]
    struct ModelsResponse {
        data: Vec<ModelInfo>,
    }
    #[derive(serde::Deserialize)]
    struct ModelInfo {
        #[serde(default)]
        max_model_len: Option<u64>,
    }
    let mut req = client.get(format!("{base}/v1/models"));
    if let Some(key) = api_key {
        req = req.bearer_auth(key);
    }
    let max_model_len = req
        .send()
        .ok()
        .filter(|r| r.status().is_success())
        .and_then(|r| r.json::<ModelsResponse>().ok())
        .and_then(|m| m.data.first().and_then(|d| d.max_model_len));

    (version, max_model_len)
}

fn client() -> Result<reqwest::blocking::Client> {
    Ok(reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .connect_timeout(Duration::from_secs(3))
        .user_agent(concat!("vllm-top/", env!("CARGO_PKG_VERSION")))
        .build()?)
}

/// Scrapes a vLLM server's own Prometheus-format endpoint.
pub struct DirectSource {
    url: String,
    client: reqwest::blocking::Client,
    api_key: Option<String>,
}

impl MetricsSource for DirectSource {
    fn fetch(&self) -> Result<Vec<Sample>> {
        let endpoint = format!("{}/metrics", self.url.trim_end_matches('/'));
        let mut req = self.client.get(&endpoint);
        if let Some(key) = &self.api_key {
            req = req.bearer_auth(key);
        }
        let resp = req
            .send()
            .with_context(|| format!("GET {endpoint}"))?
            .error_for_status()
            .with_context(|| format!("GET {endpoint}"))?;
        let body = resp.text().context("reading /metrics body")?;
        Ok(promparse::parse(&body))
    }
}

/// One worker's engine statistics, republished by the orchestrator gateway in a neutral shape and mapped
/// here onto the `vllm:*` series the rest of the app understands. Series the engine does not report are
/// simply absent (shown as unavailable), never emitted as zero.
pub struct GatewaySource {
    base: String,
    worker: String,
    client: reqwest::blocking::Client,
}

impl MetricsSource for GatewaySource {
    fn fetch(&self) -> Result<Vec<Sample>> {
        let base = self.base.trim_end_matches('/');
        let endpoint = format!("{base}/health");
        let body: serde_json::Value = self
            .client
            .get(&endpoint)
            .send()
            .with_context(|| format!("GET {endpoint}"))?
            .error_for_status()
            .with_context(|| format!("GET {endpoint}"))?
            .json()
            .context("parsing gateway /health")?;
        let mut samples = samples_from_gateway_health(&body, &self.worker)?;
        // Gateway-measured request latency and completions (best effort: engine stats stand on their own).
        if let Ok(text) = self.client.get(format!("{base}/metrics")).send().and_then(|r| r.text()) {
            samples.extend(samples_from_gateway_metrics(&promparse::parse(&text), &self.worker));
        }
        Ok(samples)
    }
}

/// Pure mapping of one worker's republished engine statistics onto the `vllm:*` series the rest of the app
/// reads. A series the engine does not report is absent (the UI shows n/a), never emitted as zero.
///
/// Token counters prefer the gateway's `*_tokens_live` values (completed plus in-flight): llama.cpp only
/// bumps its own counters when a request finishes, which would make throughput a single-poll spike.
/// Prompt tokens follow vLLM's meaning (cached tokens included) so the cached ratio is cached / all.
pub fn samples_from_gateway_health(body: &serde_json::Value, worker: &str) -> Result<Vec<Sample>> {
    let w = body
        .get("workers")
        .and_then(|ws| ws.get(worker))
        .with_context(|| format!("gateway does not list worker {worker:?}"))?;
    if w.get("status").and_then(|s| s.as_str()) == Some("stopped") {
        // The registry entry is intentionally retained for configuration and
        // routing identity, but it is not a running inference service.
        return Ok(Vec::new());
    }
    if w.get("healthy").and_then(|h| h.as_bool()) == Some(false) {
        bail!("gateway reports worker {worker:?} {}", w.get("status").and_then(|s| s.as_str()).unwrap_or("unhealthy"));
    }
    let stats = w
        .get("engine_stats")
        .filter(|v| v.is_object())
        .with_context(|| format!("gateway publishes no engine statistics for {worker:?}"))?;
    let model = w.get("model_id").and_then(|m| m.as_str()).unwrap_or("").to_string();
    let num = |key: &str| stats.get(key).and_then(|v| v.as_f64());
    let mut out = Vec::new();
    let mut push = |name: &str, value: Option<f64>| {
        if let Some(v) = value {
            let mut labels = std::collections::BTreeMap::new();
            if !model.is_empty() {
                labels.insert("model_name".to_string(), model.clone());
            }
            out.push(Sample { name: name.to_string(), labels, value: v });
        }
    };
    push("vllm:num_requests_running", num("requests_running"));
    push("vllm:num_requests_waiting", num("requests_waiting"));
    push("vllm:kv_cache_usage_perc", num("kv_cache_usage"));
    push("vllm:generation_tokens_total", num("generation_tokens_live").or_else(|| num("generation_tokens_total")));
    let processed = num("prompt_tokens_live").or_else(|| num("prompt_tokens_total"));
    match (processed, num("prompt_tokens_cached_total")) {
        (Some(p), Some(c)) => {
            push("vllm:prompt_tokens_total", Some(p + c));
            push("vllm:prompt_tokens_cached_total", Some(c));
            push("vllm:prefix_cache_queries_total", Some(p + c));
            push("vllm:prefix_cache_hits_total", Some(c));
        }
        (p, _) => push("vllm:prompt_tokens_total", p),
    }
    if out.is_empty() {
        bail!("gateway engine statistics for {worker:?} are empty");
    }
    Ok(out)
}

/// The gateway's own per-worker request metrics, renamed onto the series vllm-top already understands:
/// end-to-end latency (time the gateway spent on the worker call) and completed requests. These are
/// gateway-side measurements; TTFT, queue time and inter-token latency are not observable there.
pub fn samples_from_gateway_metrics(samples: &[Sample], worker: &str) -> Vec<Sample> {
    let mut out = Vec::new();
    for s in samples.iter().filter(|s| s.label("worker_id") == Some(worker)) {
        let renamed = match s.name.as_str() {
            "aihost_inference_duration_seconds_bucket" => Some("vllm:e2e_request_latency_seconds_bucket"),
            "aihost_inference_duration_seconds_sum" => Some("vllm:e2e_request_latency_seconds_sum"),
            "aihost_inference_duration_seconds_count" => Some("vllm:e2e_request_latency_seconds_count"),
            "aihost_inference_completions_total" if s.label("outcome") == Some("completed") => Some("vllm:request_success_total"),
            _ => None,
        };
        let Some(name) = renamed else { continue };
        let mut labels = std::collections::BTreeMap::new();
        if let Some(le) = s.label("le") {
            labels.insert("le".to_string(), le.to_string());
        }
        if name == "vllm:request_success_total" {
            labels.insert("finished_reason".to_string(), "completed".to_string());
        }
        out.push(Sample { name: name.to_string(), labels, value: s.value });
    }
    out
}

/// Runs an instant vector query against Prometheus for every `vllm:` metric.
pub struct PrometheusSource {
    url: String,
    client: reqwest::blocking::Client,
    api_key: Option<String>,
}

#[derive(serde::Deserialize)]
struct PromResponse {
    status: String,
    error: Option<String>,
    data: PromData,
}

#[derive(serde::Deserialize)]
struct PromData {
    #[serde(default)]
    result: Vec<PromResult>,
}

#[derive(serde::Deserialize)]
struct PromResult {
    #[serde(default)]
    metric: std::collections::BTreeMap<String, String>,
    value: (f64, String),
}

impl MetricsSource for PrometheusSource {
    fn fetch(&self) -> Result<Vec<Sample>> {
        let endpoint = format!("{}/api/v1/query", self.url.trim_end_matches('/'));
        let mut req = self
            .client
            .get(&endpoint)
            .query(&[("query", "{__name__=~\"vllm:.*\"}")]);
        if let Some(key) = &self.api_key {
            req = req.bearer_auth(key);
        }
        let resp = req
            .send()
            .with_context(|| format!("GET {endpoint}"))?
            .error_for_status()
            .with_context(|| format!("GET {endpoint}"))?;

        let body = resp.text().context("reading Prometheus response body")?;
        parse_prometheus_response(&body)
    }
}

/// Decode a Prometheus `/api/v1/query` JSON body into flat samples. Split
/// out from `fetch` so it's testable without a live server.
fn parse_prometheus_response(body: &str) -> Result<Vec<Sample>> {
    let parsed: PromResponse = serde_json::from_str(body).context("decoding Prometheus response")?;
    if parsed.status != "success" {
        bail!(
            "prometheus query failed: {}",
            parsed.error.unwrap_or_else(|| "unknown error".into())
        );
    }

    let mut out = Vec::with_capacity(parsed.data.result.len());
    for series in parsed.data.result {
        let Some(name) = series.metric.get("__name__").cloned() else {
            continue;
        };
        let Ok(value) = series.value.1.parse::<f64>() else {
            continue;
        };
        let labels = series
            .metric
            .into_iter()
            .filter(|(k, _)| k != "__name__")
            .collect();
        out.push(Sample { name, labels, value });
    }
    if out.is_empty() {
        bail!("no vllm: metrics found (is this the right Prometheus?)");
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_successful_prometheus_response() {
        let body = r#"{
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"__name__": "vllm:num_requests_running", "model_name": "m"}, "value": [1700000000, "3"]},
                    {"metric": {"__name__": "vllm:num_requests_waiting"}, "value": [1700000000, "7"]}
                ]
            }
        }"#;
        let samples = parse_prometheus_response(body).expect("parses");
        assert_eq!(samples.len(), 2);
        assert_eq!(samples[0].name, "vllm:num_requests_running");
        assert_eq!(samples[0].value, 3.0);
        assert_eq!(samples[0].label("model_name"), Some("m"));
        assert_eq!(samples[1].name, "vllm:num_requests_waiting");
        assert_eq!(samples[1].value, 7.0);
    }

    #[test]
    fn rejects_non_success_status_with_the_reported_error() {
        let body = r#"{"status": "error", "error": "bad query", "data": {"result": []}}"#;
        let err = parse_prometheus_response(body).unwrap_err();
        assert!(err.to_string().contains("bad query"), "{err}");
    }

    #[test]
    fn rejects_an_empty_but_successful_result_as_the_wrong_prometheus() {
        let body = r#"{"status": "success", "data": {"result": []}}"#;
        assert!(parse_prometheus_response(body).is_err());
    }

    #[test]
    fn skips_series_with_unparseable_values_rather_than_failing_the_whole_batch() {
        let body = r#"{
            "status": "success",
            "data": {
                "result": [
                    {"metric": {"__name__": "vllm:ok"}, "value": [1700000000, "5"]},
                    {"metric": {"__name__": "vllm:bad"}, "value": [1700000000, "not-a-number"]}
                ]
            }
        }"#;
        let samples = parse_prometheus_response(body).expect("parses");
        assert_eq!(samples.len(), 1);
        assert_eq!(samples[0].name, "vllm:ok");
    }
}

#[cfg(test)]
mod gateway_tests {
    use super::*;
    use crate::metrics::Snapshot;

    fn health(worker_json: &str) -> serde_json::Value {
        serde_json::from_str(&format!(r#"{{"workers": {{"w-llama": {worker_json}}}}}"#)).unwrap()
    }

    #[test]
    fn maps_neutral_engine_stats_onto_the_series_the_app_understands() {
        let body = health(r#"{"status":"healthy","healthy":true,"model_id":"Qwen3-Coder-Q4","engine_stats":{
            "requests_running":1,"requests_waiting":2,"kv_cache_usage":0.25,
            "prompt_tokens_total":5000,"generation_tokens_total":900,"prefix_cache_hit_ratio":null,"observed_at":1.0}}"#);
        let samples = samples_from_gateway_health(&body, "w-llama").expect("samples");
        let snap = Snapshot::extract(&samples);
        assert_eq!((snap.running, snap.waiting, snap.kv_cache_usage), (1.0, 2.0, 0.25));
        assert_eq!((snap.prompt_tokens, snap.generation_tokens), (5000.0, 900.0));
        assert_eq!(snap.model.as_deref(), Some("Qwen3-Coder-Q4"));
    }

    #[test]
    fn an_unreported_series_is_absent_not_zero() {
        let body = health(r#"{"healthy":true,"engine_stats":{"requests_running":3,"kv_cache_usage":null}}"#);
        let samples = samples_from_gateway_health(&body, "w-llama").expect("samples");
        assert!(samples.iter().any(|s| s.name == "vllm:num_requests_running"));
        assert!(!samples.iter().any(|s| s.name == "vllm:kv_cache_usage_perc"), "unknown kv usage must not be emitted as 0");
    }

    #[test]
    fn missing_unhealthy_or_stats_less_workers_are_errors_not_fake_data() {
        let body = health(r#"{"healthy":true,"engine_stats":null}"#);
        assert!(samples_from_gateway_health(&body, "w-llama").is_err(), "no stats published");
        assert!(samples_from_gateway_health(&body, "nope").is_err(), "unknown worker");
        let down = health(r#"{"healthy":false,"status":"stale","engine_stats":{"requests_running":1}}"#);
        assert!(samples_from_gateway_health(&down, "w-llama").is_err(), "an unhealthy worker is not shown as live");
    }

    #[test]
    fn stopped_worker_is_not_a_metrics_failure_or_fake_live_instance() {
        let body = health(r#"{"healthy":false,"status":"stopped","expected_state":"stopped","engine_stats":null}"#);
        let samples = samples_from_gateway_health(&body, "w-llama").expect("intentional stop is not a scrape failure");
        assert!(samples.is_empty(), "stopped worker must not publish fabricated metrics");
    }

    const GATEWAY_METRICS: &str = r#"aihost_inference_completions_total{worker_id="w-llama",outcome="completed"} 418
aihost_inference_completions_total{worker_id="w-llama",outcome="failed"} 1
aihost_inference_completions_total{worker_id="other",outcome="completed"} 99
aihost_inference_duration_seconds_bucket{worker_id="w-llama",model="m",le="1.0"} 100
aihost_inference_duration_seconds_bucket{worker_id="w-llama",model="m",le="10.0"} 400
aihost_inference_duration_seconds_bucket{worker_id="w-llama",model="m",le="+Inf"} 418
aihost_inference_duration_seconds_sum{worker_id="w-llama",model="m"} 2090.0
aihost_inference_duration_seconds_count{worker_id="w-llama",model="m"} 418
aihost_inference_duration_seconds_count{worker_id="other",model="m"} 7
"#;

    #[test]
    fn live_counters_and_cached_tokens_follow_vllm_semantics() {
        let body = health(r#"{"healthy":true,"model_id":"m","engine_stats":{
            "requests_running":1,"requests_waiting":0,"kv_cache_usage":0.2,
            "generation_tokens_total":400,"generation_tokens_live":450,
            "prompt_tokens_total":1000,"prompt_tokens_live":1020,"prompt_tokens_cached_total":9000}}"#);
        let snap = Snapshot::extract(&samples_from_gateway_health(&body, "w-llama").unwrap());
        assert_eq!(snap.generation_tokens, 450.0, "in-flight tokens must be counted so throughput is not a completion spike");
        assert_eq!(snap.prompt_tokens, 10_020.0, "vLLM semantics: processed + cached");
        assert_eq!(snap.prompt_tokens_cached, 9000.0);
        assert!((snap.cached_ratio().unwrap() - 9000.0 / 10_020.0).abs() < 1e-9);
        assert_eq!((snap.prefix_hits, snap.prefix_queries), (9000.0, 10_020.0));
        assert!(snap.has.kv && snap.has.prefix);
    }

    #[test]
    fn ollama_loaded_models_name_the_instance_and_leave_rates_absent() {
        let body: serde_json::Value = serde_json::from_str(include_str!("../tests/fixtures/ollama/ps.json")).unwrap();
        let samples = samples_from_ollama_ps(&body);
        let snap = crate::metrics::Snapshot::extract(&samples);
        assert_eq!(snap.model.as_deref(), Some("qwen3:8b"));
        assert!(samples.iter().any(|s| s.name == "ollama:model_vram_bytes" && s.value == 6_260_000_000.0));
        assert!(samples.iter().all(|s| !s.name.starts_with("vllm:")), "no fabricated vLLM series");
        assert!(samples_from_ollama_ps(&serde_json::json!({"models": []})).is_empty(), "nothing loaded is nothing");
    }

    #[test]
    fn availability_follows_what_the_engine_reports() {
        let body = health(r#"{"healthy":true,"engine_stats":{"requests_running":0,"kv_cache_usage":null,
            "generation_tokens_total":5,"prompt_tokens_total":7}}"#);
        let snap = Snapshot::extract(&samples_from_gateway_health(&body, "w-llama").unwrap());
        assert!(!snap.has.kv, "no KV figure: n/a, not 0%");
        assert!(!snap.has.prefix, "no cached-token series: n/a, not 0%");
        assert!(!snap.has.ttft && !snap.has.queue && !snap.has.e2e && !snap.has.itl);
        assert_eq!((snap.generation_tokens, snap.prompt_tokens), (5.0, 7.0), "falls back to the completed totals");
    }

    #[test]
    fn gateway_request_metrics_become_e2e_latency_and_completions_for_one_worker_only() {
        let samples = samples_from_gateway_metrics(&promparse::parse(GATEWAY_METRICS), "w-llama");
        let snap = Snapshot::extract(&samples);
        assert!(snap.has.e2e && !snap.has.ttft && !snap.has.queue && !snap.has.itl, "only e2e is measurable at the gateway");
        assert_eq!(snap.e2e.count, 418.0);
        assert!((snap.e2e.avg - 5.0).abs() < 1e-9, "avg = sum/count = 2090/418");
        assert!(snap.e2e.p99 > 1.0, "p99 comes from the real bucket layout incl. +Inf, got {}", snap.e2e.p99);
        assert_eq!(snap.success_total, 418.0, "only outcome=completed counts as a success");
        assert!(samples_from_gateway_metrics(&promparse::parse(GATEWAY_METRICS), "nobody").is_empty());
    }
}
