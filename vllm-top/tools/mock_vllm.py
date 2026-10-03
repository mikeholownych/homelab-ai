#!/usr/bin/env python3
"""A tiny stand-in for a vLLM server, for developing vllm-top without a GPU.

Serves:
  GET /metrics         Prometheus text exposition (what `--kind direct` scrapes)
  GET /api/v1/query    Prometheus instant-vector API   (what `--kind prometheus` queries)

Counters grow over time so rates and graphs move. Usage:
    python3 tools/mock_vllm.py [port]
"""

import json
import math
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

START = time.time()
MODEL = "unsloth/Llama-3.2-1B-Instruct"

# histogram bucket edges (seconds) for the latency metrics we care about
EDGES = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
# relative weights approximating a right-skewed latency distribution
WEIGHTS = [8, 14, 22, 20, 15, 10, 6, 3, 2]


def elapsed():
    return time.time() - START


def gauge_series(seconds):
    """A couple of overlapping slow sines, clamped to a sensible range."""
    return 0.5 + 0.4 * math.sin(seconds / 37.0) + 0.1 * math.sin(seconds / 7.0)


def hist(base, total, mean_scale):
    """Emit _bucket/_sum/_count lines for a fake histogram."""
    lines = []
    cum = 0
    total_weight = sum(WEIGHTS)
    for i, (edge, weight) in enumerate(zip(EDGES, WEIGHTS)):
        cum += weight
        if i == len(EDGES) - 1:
            le = "+Inf"
            count = total
        else:
            le = edge
            count = total * cum / total_weight
        lines.append(f'{base}_bucket{{le="{le}",model_name="{MODEL}"}} {count:.1f}')
    mean = mean_scale * 1.6
    lines.append(f"{base}_sum{{model_name=\"{MODEL}\"}} {total * mean:.1f}")
    lines.append(f"{base}_count{{model_name=\"{MODEL}\"}} {total:.1f}")
    return lines


def metrics():
    e = elapsed()
    running = max(0.0, 4 + 3 * math.sin(e / 9.0))
    waiting = max(0.0, 2 + 2 * math.sin(e / 13.0 + 1.0))
    kv = min(1.0, max(0.05, 0.55 + 0.35 * math.sin(e / 23.0)))
    prompt_tokens = 820_000 + e * 850
    gen_tokens = 2_400_000 + e * 2_400
    cached = prompt_tokens * (0.6 + 0.05 * math.sin(e / 41.0))
    finished = 1_000 + e * 4.3
    prefix_queries = 61_000 + e * 30
    prefix_hits = prefix_queries * (0.78 + 0.05 * math.sin(e / 31.0))

    lines = [
        f"# TYPE vllm:num_requests_running gauge",
        f'vllm:num_requests_running{{model_name="{MODEL}"}} {running:.1f}',
        f'vllm:num_requests_waiting{{model_name="{MODEL}"}} {waiting:.1f}',
        f'vllm:kv_cache_usage_perc{{model_name="{MODEL}"}} {kv:.4f}',
        f'vllm:prompt_tokens{{model_name="{MODEL}"}} {prompt_tokens:.1f}',
        f'vllm:generation_tokens{{model_name="{MODEL}"}} {gen_tokens:.1f}',
        f'vllm:prompt_tokens_cached{{model_name="{MODEL}"}} {cached:.1f}',
        f'vllm:request_success{{finished_reason="stop",model_name="{MODEL}"}} {finished * 0.61:.1f}',
        f'vllm:request_success{{finished_reason="length",model_name="{MODEL}"}} {finished * 0.38:.1f}',
        f'vllm:request_success{{finished_reason="abort",model_name="{MODEL}"}} {finished * 0.01:.1f}',
        f'vllm:num_preemptions{{model_name="{MODEL}"}} {max(0.0, e / 600.0 - 1):.1f}',
        f'vllm:prefix_cache_hits{{model_name="{MODEL}"}} {prefix_hits:.1f}',
        f'vllm:prefix_cache_queries{{model_name="{MODEL}"}} {prefix_queries:.1f}',
    ]
    lines += hist("vllm:time_to_first_token_seconds", finished, 0.31)
    lines += hist("vllm:request_queue_time_seconds", finished, 0.055)
    lines += hist("vllm:e2e_request_latency_seconds", finished, 2.6)
    lines += hist("vllm:inter_token_latency_seconds", finished * 100, 0.031)
    return "\n".join(lines) + "\n"


def samples():
    """(name, labels, value) triples — the JSON form used by /api/v1/query."""
    out = []
    for line in metrics().splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.match(r'^(\w[\w:]*)(?:\{(.*)\})?\s+([^\s]+)$', line)
        if not match:
            continue
        name, raw_labels, value = match.groups()
        labels = {}
        if raw_labels:
            for part in re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', raw_labels):
                labels[part[0]] = part[1].replace('\\"', '"').replace("\\n", "\n")
        labels["__name__"] = name
        out.append((labels, float(value)))
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _send(self, body, content_type):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/metrics":
            self._send(metrics(), "text/plain; version=0.0.4")
        elif url.path == "/api/v1/query":
            query = parse_qs(url.query).get("query", [""])[0]
            matcher = None
            found = re.search(r'__name__=~"([^"]+)"', query)
            if found:
                matcher = re.compile("^" + found.group(1).replace(".*", ".*") + "$")
            now = time.time()
            result = [
                {"metric": labels, "value": [now, f"{value:.6f}"]}
                for labels, value in samples()
                if matcher is None or matcher.match(labels["__name__"])
            ]
            payload = {"status": "success", "data": {"resultType": "vector", "result": result}}
            self._send(json.dumps(payload), "application/json")
        elif url.path == "/health":
            self._send("ok", "text/plain")
        else:
            self.send_error(404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock vLLM listening on http://127.0.0.1:{port}/metrics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
