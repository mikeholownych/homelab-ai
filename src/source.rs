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
