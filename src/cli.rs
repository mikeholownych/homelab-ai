use crate::config::SourceKind;
use clap::Parser;

/// btop-style terminal monitor for vLLM usage and performance.
#[derive(Parser, Debug)]
#[command(name = "vllm-top", version, about, long_about = None)]
pub struct Cli {
    /// Endpoint to monitor: a vLLM server URL (direct) or a Prometheus base URL.
    /// Repeat the flag to monitor several instances.
    #[arg(short = 'u', long = "url", value_name = "URL")]
    pub urls: Vec<String>,

    /// Source kind for every --url given on the command line
    #[arg(long, value_enum, default_value_t = SourceKind::Direct)]
    pub kind: SourceKind,

    /// API key for every --url given on the command line, and for a
    /// locally discovered instance. Falls back to VLLM_API_KEY if unset.
    #[arg(long, value_name = "KEY")]
    pub api_key: Option<String>,

    /// TOML config file. Defaults to ./vllm-top.toml then
    /// ~/.config/vllm-top/config.toml when omitted.
    #[arg(short, long, value_name = "FILE")]
    pub config: Option<String>,

    /// Poll interval in milliseconds (min 200)
    #[arg(long, value_name = "MS")]
    pub poll_ms: Option<u64>,

    /// Number of history samples kept per graph (min 16)
    #[arg(long, value_name = "N")]
    pub history: Option<usize>,

    /// Fetch once, print a text summary and exit (no TUI)
    #[arg(long)]
    pub once: bool,

    /// Render a single frame with synthetic data to stdout (UI preview)
    #[arg(long)]
    pub demo: bool,
}
