//! Formatting helpers shared by the TUI and the `--once` text output.

use std::time::Duration;

/// Compact SI-style number: 950, 1.2k, 13.4M, 2.1G.
pub fn fmt_si(value: f64) -> String {
    if !value.is_finite() {
        return "n/a".into();
    }
    let abs = value.abs();
    let (num, suffix) = if abs < 1_000.0 {
        (value, "")
    } else if abs < 1e6 {
        (value / 1e3, "k")
    } else if abs < 1e9 {
        (value / 1e6, "M")
    } else if abs < 1e12 {
        (value / 1e9, "G")
    } else {
        (value / 1e12, "T")
    };
    if suffix.is_empty() {
        format!("{num:.0}")
    } else if num.abs() < 10.0 {
        format!("{num:.1}{suffix}")
    } else {
        format!("{num:.0}{suffix}")
    }
}

/// Latency in seconds, rendered at a human scale.
pub fn fmt_secs(seconds: f64) -> String {
    if !seconds.is_finite() || seconds < 0.0 {
        return "-".into();
    }
    if seconds < 1e-3 {
        format!("{:.0}µs", seconds * 1e6)
    } else if seconds < 1.0 {
        format!("{:.1}ms", seconds * 1e3)
    } else if seconds < 120.0 {
        format!("{:.2}s", seconds)
    } else {
        format!("{:.1}m", seconds / 60.0)
    }
}

/// Duration as `3d 04h 12m` / `12m 05s` / `7s`.
pub fn fmt_dur(d: Duration) -> String {
    let total = d.as_secs();
    let days = total / 86_400;
    let hours = (total % 86_400) / 3_600;
    let mins = (total % 3_600) / 60;
    let secs = total % 60;
    if days > 0 {
        format!("{days}d {hours:02}h {mins:02}m")
    } else if hours > 0 {
        format!("{hours}h {mins:02}m {secs:02}s")
    } else if mins > 0 {
        format!("{mins}m {secs:02}s")
    } else {
        format!("{secs}s")
    }
}

/// Fraction (0..1) as a percentage string.
pub fn fmt_pct(ratio: f64) -> String {
    if !ratio.is_finite() {
        return "-".into();
    }
    format!("{:.1}%", ratio * 100.0)
}

/// Duration as a compact interval label: `500ms`, `1.0s`, `10.0s`.
pub fn fmt_interval(d: Duration) -> String {
    let ms = d.as_millis();
    if ms < 1_000 {
        format!("{ms}ms")
    } else {
        format!("{:.1}s", d.as_secs_f64())
    }
}

/// Trim a URL down to something short enough for a table cell.
pub fn short_url(url: &str) -> String {
    url.trim_end_matches('/')
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .to_string()
}

/// Pull the useful end out of a reqwest error chain, e.g. keep
/// "Connection refused (os error 111)" instead of the whole URL preamble.
pub fn short_error(msg: &str) -> String {
    let short = match msg.rfind("): ") {
        Some(i) => &msg[i + 3..],
        None => msg,
    };
    truncate(short, 70)
}

/// Trim text to `max` chars, appending an ellipsis when cut.
pub fn truncate(text: &str, max: usize) -> String {
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

/// Alias used by the `--once` table.
pub fn truncate_for_cli(text: &str, max: usize) -> String {
    truncate(text, max)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn si_suffixes() {
        assert_eq!(fmt_si(950.0), "950");
        assert_eq!(fmt_si(1_260.0), "1.3k");
        assert_eq!(fmt_si(13_400_000.0), "13M");
    }

    #[test]
    fn latencies() {
        assert_eq!(fmt_secs(0.000_4), "400µs");
        assert_eq!(fmt_secs(0.042), "42.0ms");
        assert_eq!(fmt_secs(1.5), "1.50s");
    }
}
