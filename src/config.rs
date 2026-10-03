use crate::cli::Cli;
use crate::discover::{self, AuthState, Confidence};
use anyhow::{bail, Context, Result};
use clap::ValueEnum;
use serde::Deserialize;
use std::collections::HashSet;
use std::path::PathBuf;
use std::time::Duration;

/// Where samples come from.
#[derive(Copy, Clone, Debug, PartialEq, Eq, ValueEnum, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceKind {
    /// Scrape a vLLM server's own `/metrics` endpoint.
    Direct,
    /// Query a Prometheus server's `/api/v1/query`.
    Prometheus,
    /// One worker's engine statistics as republished by the orchestrator gateway (`GET /health`).
    /// Engine-agnostic (vLLM, llama.cpp, ...) and needs no worker credential. The url is
    /// `http://host:port#<worker-id>`.
    Gateway,
}

impl SourceKind {
    pub fn label(self) -> &'static str {
        match self {
            SourceKind::Direct => "direct",
            SourceKind::Prometheus => "prometheus",
            SourceKind::Gateway => "gateway",
        }
    }
}

/// One monitored endpoint.
#[derive(Debug, Clone)]
pub struct InstanceDef {
    pub name: String,
    pub kind: SourceKind,
    pub url: String,
    pub api_key: Option<String>,
    /// How this instance was found, e.g. "systemd vllm.service" — set only
    /// for instances filled in by local discovery, never for `--url`/TOML
    /// entries the user gave explicitly.
    pub discovered_via: Option<String>,
    /// Auth requirement observed during discovery, for display only. Never
    /// set for explicitly configured instances (we don't probe those).
    pub auth: Option<AuthState>,
    /// How confident discovery is that this endpoint belongs to the
    /// process it looks like it does — see [`discover::Confidence`]. Never
    /// set for explicitly configured instances.
    pub confidence: Option<Confidence>,
}

/// Runtime settings after merging CLI flags with the config file.
#[derive(Debug, Clone)]
pub struct Settings {
    pub poll: Duration,
    pub history: usize,
}

#[derive(Debug, Default, Deserialize)]
struct FileConfig {
    poll_ms: Option<u64>,
    history: Option<usize>,
    #[serde(default)]
    instances: Vec<FileInstance>,
}

#[derive(Debug, Clone, Deserialize)]
struct FileInstance {
    name: Option<String>,
    url: String,
    #[serde(default)]
    kind: Option<SourceKind>,
    #[serde(default)]
    api_key: Option<String>,
}

/// Merge CLI flags and the config file into a concrete instance list.
pub fn resolve(cli: &Cli) -> Result<(Settings, Vec<InstanceDef>)> {
    let file = load_file(cli.config.as_deref())?;

    // The credential for the local vLLM instance: an explicit --api-key
    // wins, otherwise the same VLLM_API_KEY environment variable vLLM
    // itself reads — but from vllm-top's own environment, never by
    // reading another process's. See src/discover.rs for why.
    let configured_api_key = cli
        .api_key
        .clone()
        .or_else(|| std::env::var("VLLM_API_KEY").ok());

    let mut defs: Vec<InstanceDef> = Vec::new();
    for url in &cli.urls {
        defs.push(InstanceDef {
            name: String::new(),
            kind: cli.kind,
            url: url.clone(),
            api_key: configured_api_key.clone(),
            discovered_via: None,
            auth: None,
            confidence: None,
        });
    }
    for inst in file.instances {
        defs.push(InstanceDef {
            name: inst.name.unwrap_or_default(),
            kind: inst.kind.unwrap_or(cli.kind),
            url: inst.url,
            api_key: inst.api_key,
            discovered_via: None,
            auth: None,
            confidence: None,
        });
    }

    if defs.is_empty() {
        let discovered = discover::discover(configured_api_key.as_deref());
        if discovered.is_empty() {
            defs.push(InstanceDef {
                name: String::new(),
                kind: SourceKind::Direct,
                url: "http://localhost:8000".to_string(),
                api_key: configured_api_key.clone(),
                discovered_via: None,
                auth: None,
                confidence: None,
            });
        } else {
            // Every candidate here already passed an independent /health
            // probe; if more than one shares an identity (e.g. two
            // processes under the same uid, indistinguishable without
            // exact-fd attribution) they're surfaced as separate instances
            // rather than one being silently dropped — nothing here picks
            // one arbitrarily. See discover::resolve_unique for the one
            // place that *does* need to refuse an ambiguous pick (runtime
            // reconnection, in app.rs).
            for inst in discovered {
                defs.push(InstanceDef {
                    name: String::new(),
                    kind: SourceKind::Direct,
                    url: inst.url,
                    api_key: configured_api_key.clone(),
                    discovered_via: Some(inst.discovered_via),
                    auth: Some(inst.auth),
                    confidence: Some(inst.confidence),
                });
            }
        }
        // Workers behind a local orchestrator gateway that are not vLLM (vLLM workers are monitored
        // directly, which gives richer latency data) become gateway instances. When no vLLM was
        // discovered the localhost:8000 placeholder above is dropped if the gateway covers it.
        let gateway_workers = crate::orchestrator::gateway_worker_instances(crate::orchestrator::DEFAULT_URL);
        if !gateway_workers.is_empty() {
            let have_real_direct = defs.iter().any(|d| d.discovered_via.is_some());
            if !have_real_direct {
                defs.retain(|d| d.kind != SourceKind::Direct);
            }
            for (worker, url) in gateway_workers {
                defs.push(InstanceDef {
                    name: worker,
                    kind: SourceKind::Gateway,
                    url,
                    api_key: None,
                    discovered_via: Some("orchestrator gateway".to_string()),
                    auth: None,
                    confidence: None,
                });
            }
        }
    } else {
        // A --url/TOML instance that explicitly points at the local
        // loopback but didn't set its own key still gets the configured
        // one — the common case of `-u http://localhost:8000` plus
        // VLLM_API_KEY in vllm-top's own environment. Non-loopback file
        // instances are left alone: we don't assume a remote server wants
        // the local key.
        if let Some(key) = &configured_api_key {
            for def in defs.iter_mut() {
                if def.api_key.is_none() && is_loopback_url(&def.url) {
                    def.api_key = Some(key.clone());
                }
            }
        }
    }

    let mut seen = HashSet::new();
    for (idx, def) in defs.iter_mut().enumerate() {
        if def.name.is_empty() {
            def.name = default_name(&def.url, idx);
        }
        let mut candidate = def.name.clone();
        let mut n = 2;
        while !seen.insert(candidate.clone()) {
            candidate = format!("{}#{}", def.name, n);
            n += 1;
        }
        def.name = candidate;
    }

    let poll_ms = cli.poll_ms.or(file.poll_ms).unwrap_or(1_000).max(200);
    let history = cli.history.or(file.history).unwrap_or(240).max(16);

    Ok((
        Settings {
            poll: Duration::from_millis(poll_ms),
            history,
        },
        defs,
    ))
}

/// `http://host:8000/v1` -> `host:8000`
fn default_name(url: &str, idx: usize) -> String {
    let trimmed = url
        .trim_end_matches('/')
        .trim_start_matches("https://")
        .trim_start_matches("http://");
    let host = trimmed.split('/').next().unwrap_or("").trim();
    if host.is_empty() {
        format!("instance-{}", idx + 1)
    } else {
        host.to_string()
    }
}

fn load_file(explicit: Option<&str>) -> Result<FileConfig> {
    let path: Option<PathBuf> = match explicit {
        Some(p) => Some(PathBuf::from(p)),
        None => {
            let local = PathBuf::from("vllm-top.toml");
            if local.exists() {
                Some(local)
            } else {
                std::env::var_os("HOME")
                    .map(|home| PathBuf::from(home).join(".config/vllm-top/config.toml"))
                    .filter(|p| p.exists())
            }
        }
    };

    let Some(path) = path else {
        return Ok(FileConfig::default());
    };

    let text = std::fs::read_to_string(&path)
        .with_context(|| format!("reading config file {}", path.display()))?;
    toml::from_str(&text).with_context(|| format!("parsing config file {}", path.display()))
}

/// Does this URL point at the local machine? Used to decide whether an
/// ambient (env-var/CLI) credential is safe to apply automatically.
fn is_loopback_url(url: &str) -> bool {
    let trimmed = url.trim_start_matches("https://").trim_start_matches("http://");
    if let Some(rest) = trimmed.strip_prefix('[') {
        return rest.split(']').next() == Some("::1");
    }
    let host = trimmed.split(['/', ':']).next().unwrap_or("");
    host == "localhost" || host == "127.0.0.1"
}

/// Validate a raw URL before we hand it to the HTTP client.
pub fn check_url(kind: SourceKind, url: &str) -> Result<()> {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        bail!(
            "{} endpoint must start with http:// or https:// (got {url:?})",
            kind.label()
        );
    }
    Ok(())
}
