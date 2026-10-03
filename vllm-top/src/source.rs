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
        let endpoint = format!("{}/health", self.base.trim_end_matches('/'));
        let body: serde_json::Value = self
            .client
            .get(&endpoint)
            .send()
            .with_context(|| format!("GET {endpoint}"))?
            .error_for_status()
            .with_context(|| format!("GET {endpoint}"))?
            .json()
            .context("parsing gateway /health")?;
        samples_from_gateway_health(&body, &self.worker)
    }
}

/// Pure mapping, separated for testing.
pub fn samples_from_gateway_health(body: &serde_json::Value, worker: &str) -> Result<Vec<Sample>> {
    let w = body
        .get("workers")
        .and_then(|ws| ws.get(worker))
        .with_context(|| format!("gateway does not list worker {worker:?}"))?;
    if w.get("healthy").and_then(|h| h.as_bool()) == Some(false) {
        bail!("gateway reports worker {worker:?} {}", w.get("status").and_then(|s| s.as_str()).unwrap_or("unhealthy"));
    }
    let stats = w
        .get("engine_stats")
        .filter(|v| v.is_object())
        .with_context(|| format!("gateway publishes no engine statistics for {worker:?}"))?;
    let model = w.get("model_id").and_then(|m| m.as_str()).unwrap_or("").to_string();
    let mut out = Vec::new();
    let mut push = |name: &str, key: &str| {
        if let Some(v) = stats.get(key).and_then(|v| v.as_f64()) {
            let mut labels = std::collections::BTreeMap::new();
            if !model.is_empty() {
                labels.insert("model_name".to_string(), model.clone());
            }
            out.push(Sample { name: name.to_string(), labels, value: v });
        }
    };
    push("vllm:num_requests_running", "requests_running");
    push("vllm:num_requests_waiting", "requests_waiting");
    push("vllm:kv_cache_usage_perc", "kv_cache_usage");
    push("vllm:prompt_tokens_total", "prompt_tokens_total");
    push("vllm:generation_tokens_total", "generation_tokens_total");
    if out.is_empty() {
        bail!("gateway engine statistics for {worker:?} are empty");
    }
    Ok(out)
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
}
