//! A small parser for the Prometheus text exposition format.
//!
//! vLLM serves this format on `/metrics`, and it is also what a Prometheus
//! server returns from `/api/v1/query` once serialised back to text. Only the
//! parts a monitor needs are handled: sample names, labels and values.
//! `# HELP` / `# TYPE` comment lines are skipped.

use std::collections::BTreeMap;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Sample {
    pub name: String,
    pub labels: BTreeMap<String, String>,
    pub value: f64,
}

impl Sample {
    pub fn label(&self, key: &str) -> Option<&str> {
        self.labels.get(key).map(String::as_str)
    }
}

/// Parse a whole exposition payload into samples.
pub fn parse(text: &str) -> Vec<Sample> {
    let mut out = Vec::new();
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some(sample) = parse_line(line) {
            out.push(sample);
        }
    }
    out
}

fn parse_line(line: &str) -> Option<Sample> {
    let bytes = line.as_bytes();
    let mut i = 0;

    // metric name
    while i < bytes.len() && !bytes[i].is_ascii_whitespace() && bytes[i] != b'{' {
        i += 1;
    }
    let name = line[..i].to_string();
    if name.is_empty() {
        return None;
    }

    let mut labels = BTreeMap::new();

    // optional label block, quoted values may contain braces
    if i < bytes.len() && bytes[i] == b'{' {
        let start = i + 1;
        let mut j = start;
        let mut in_quote = false;
        let mut escaped = false;
        while j < bytes.len() {
            let c = bytes[j];
            if escaped {
                escaped = false;
            } else if c == b'\\' && in_quote {
                escaped = true;
            } else if c == b'"' {
                in_quote = !in_quote;
            } else if c == b'}' && !in_quote {
                break;
            }
            j += 1;
        }
        if j >= bytes.len() {
            return None;
        }
        parse_labels(&line[start..j], &mut labels);
        i = j + 1;
    }

    while i < bytes.len() && bytes[i].is_ascii_whitespace() {
        i += 1;
    }
    let vstart = i;
    while i < bytes.len() && !bytes[i].is_ascii_whitespace() {
        i += 1;
    }
    let value: f64 = line[vstart..i].parse().ok()?;

    Some(Sample { name, labels, value })
}

/// Split `k="v",k2="v2"` honouring quoted values, unescaping as we go.
fn parse_labels(text: &str, out: &mut BTreeMap<String, String>) {
    let mut key = String::new();
    let mut value = String::new();
    let mut in_key = true;
    let mut in_quote = false;
    let mut escaped = false;

    for c in text.chars() {
        if escaped {
            let pushed = match c {
                'n' => '\n',
                't' => '\t',
                'r' => '\r',
                other => other,
            };
            if in_key {
                key.push(pushed);
            } else {
                value.push(pushed);
            }
            escaped = false;
            continue;
        }
        match c {
            '\\' if in_quote => escaped = true,
            '"' => {
                in_quote = !in_quote;
                if in_key {
                    key.push('"');
                }
            }
            '=' if in_key && !in_quote => in_key = false,
            ',' if !in_quote => {
                if !in_key {
                    let k = key.trim().to_string();
                    if !k.is_empty() {
                        out.insert(k, std::mem::take(&mut value));
                    }
                }
                key.clear();
                value.clear();
                in_key = true;
            }
            other => {
                if in_key {
                    key.push(other);
                } else {
                    value.push(other);
                }
            }
        }
    }

    if !in_key {
        let k = key.trim().to_string();
        if !k.is_empty() {
            out.insert(k, value);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_simple_sample() {
        let out = parse("vllm:num_requests_running 3.0\n");
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].name, "vllm:num_requests_running");
        assert_eq!(out[0].value, 3.0);
    }

    #[test]
    fn parses_labels_and_comments() {
        let text = "\
# HELP vllm:request_success Count of successfully processed requests.
# TYPE vllm:request_success counter
vllm:request_success{finished_reason=\"stop\",model_name=\"a/b\"} 1.0
vllm:request_success{finished_reason=\"length\",model_name=\"a/b\"} 131.0
";
        let out = parse(text);
        assert_eq!(out.len(), 2);
        assert_eq!(out[0].label("finished_reason"), Some("stop"));
        assert_eq!(out[1].value, 131.0);
    }

    #[test]
    fn parses_histogram_buckets() {
        let text = "\
vllm:time_to_first_token_seconds_bucket{le=\"0.1\"} 4.0
vllm:time_to_first_token_seconds_bucket{le=\"+Inf\"} 9.0
vllm:time_to_first_token_seconds_sum 2.5
vllm:time_to_first_token_seconds_count 9.0
";
        let out = parse(text);
        assert_eq!(out.len(), 4);
        assert_eq!(out[1].label("le"), Some("+Inf"));
        assert_eq!(out[1].value, 9.0);
    }

    #[test]
    fn handles_escaped_label_values() {
        let out = parse(r#"vllm:x{msg="a\"b,c\n"} 1"#);
        assert_eq!(out[0].label("msg"), Some("a\"b,c\n"));
        let out = parse(r#"vllm:x{msg="back\\slash"} 1"#);
        assert_eq!(out[0].label("msg"), Some(r"back\slash"));
    }
}
