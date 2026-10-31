"""Bounded TLS gateway qualification. Credentials arrive on stdin; never enter receipts.

This exercises the deployed HTTP contract, not the Nexus application or arbitrary model quality.
No service/configuration mutation is performed by this runner.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
from pathlib import Path
import ssl
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

MODELS = ('engineering/lead', 'engineering/deep')


def percentile(values: list[float], fraction: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def summarize(samples: list[dict[str, Any]], minimum_samples: int = 100) -> dict[str, Any]:
    """Fail closed on missing samples, health errors, process changes or growing resources."""
    good = [s for s in samples if s.get('status') == 200 and s.get('ready') is True]
    resources = [s for s in samples if 'memory' in s]
    p99 = percentile([s['seconds'] for s in good], .99)
    gates: dict[str, bool] = {
        'sufficient_health_samples': len(samples) >= minimum_samples,
        'every_health_sample_ready': len(good) == len(samples),
        'health_p99_below_250ms': p99 is not None and p99 < .25,
        'sufficient_resource_samples': len(resources) >= 6,
    }
    measurements: dict[str, Any] = {'health_samples': len(samples), 'health_p99_seconds': p99}
    if resources:
        width = max(1, len(resources) // 3)
        first = statistics.median(s['memory'] for s in resources[:width])
        last = statistics.median(s['memory'] for s in resources[-width:])
        growth = last - first
        gates.update({
            'memory_headroom': max(s['memory'] for s in resources) < 512 * 1024**2,
            'memory_growth_bounded': growth <= max(16 * 1024**2, first * .20),
            'gateway_process_unchanged': len({s['pid'] for s in resources}) == 1 and resources[0]['pid'] > 0,
            'fd_growth_bounded': max(s['fds'] for s in resources[-width:]) <= max(s['fds'] for s in resources[:width]) + 4,
            'task_growth_bounded': max(s['tasks'] for s in resources[-width:]) <= max(s['tasks'] for s in resources[:width]) + 2,
        })
        measurements.update({'memory_peak_bytes': max(s['memory'] for s in resources),
                             'memory_first_third_median': first, 'memory_last_third_median': last,
                             'memory_growth_bytes': growth, 'resource_samples': len(resources)})
    return {'gates': gates, 'measurements': measurements, 'passed': all(gates.values())}


class Probe:
    def __init__(self, base: str, ca: str, tokens: dict[str, str], host: str):
        self.base = base.rstrip('/')
        self.context = ssl.create_default_context(cafile=ca)
        self.tokens = tokens
        self.host = host

    def request(self, path: str, client: str = 'operator', body: Any = None,
                extra_headers: dict[str, str] | None = None, slow_stream: bool = False) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {'Authorization': 'Bearer ' + self.tokens[client], 'Content-Type': 'application/json',
                   'Cache-Control': 'no-store', 'X-AIHost-Cache': 'bypass',
                   'X-AIHost-Reasoning': 'off', 'X-AIHost-Deadline-Ms': '30000'}
        headers.update(extra_headers or {})
        req = urllib.request.Request(self.base + path, data=data, headers=headers)
        start = time.monotonic()
        result: dict[str, Any] = {'status': 0}
        try:
            with urllib.request.urlopen(req, timeout=40, context=self.context) as response:
                result['status'] = response.status
                result['headers_seconds'] = time.monotonic() - start
                if body and body.get('stream'):
                    chunks = []
                    times = []
                    done = False
                    for line in response:
                        if slow_stream:
                            time.sleep(.02)
                        if not line.startswith(b'data: '):
                            continue
                        raw = line[6:].strip()
                        if raw == b'[DONE]':
                            done = True
                            break
                        event = json.loads(raw)
                        chunks.append(event)
                        for choice in event.get('choices', []):
                            delta = choice.get('delta', {})
                            if delta.get('content') or delta.get('tool_calls'):
                                times.append(time.monotonic() - start)
                    result.update({'events': chunks, 'done': done,
                                   'ttft_seconds': times[0] if times else None,
                                   'content_event_gaps_seconds': [b - a for a, b in zip(times, times[1:])]})
                else:
                    raw = response.read(2 * 1024 * 1024)
                    result['body'] = json.loads(raw)
        except urllib.error.HTTPError as error:
            with error:
                raw = error.read(8192)
                result.update({'status': error.code, 'error_body_sha256': hashlib.sha256(raw).hexdigest()})
        except (OSError, ValueError) as error:
            # Exception messages can contain URLs; retain the class only.
            result['error_type'] = type(error).__name__
        result['seconds'] = time.monotonic() - start
        return result

    def resources(self) -> dict[str, int]:
        code = '''import json,subprocess,os
s=dict(x.split('=',1) for x in subprocess.check_output(['systemctl','show','aihost-orchestrator-gateway.service','-p','MainPID,MemoryCurrent,TasksCurrent'],text=True).splitlines())
p=int(s['MainPID']);print(json.dumps({'pid':p,'memory':int(s['MemoryCurrent']),'tasks':int(s['TasksCurrent']),'fds':len(os.listdir('/proc/'+str(p)+'/fd'))}))
'''
        p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', self.host,
                            'sudo -n python3 -'], input=code, text=True, capture_output=True, timeout=10, check=True)
        return json.loads(p.stdout)


def payload(model: str, prompt: str, stream: bool = False) -> dict[str, Any]:
    return {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0, 'max_tokens': 128, 'cache': False, 'stream': stream}


def scrub(result: dict[str, Any]) -> dict[str, Any]:
    """Keep timing/status/usage and hashes, never generated text or request credentials."""
    record = {k: v for k, v in result.items() if k not in ('body', 'events')}
    for key in ('body', 'events'):
        if key in result:
            record[key + '_sha256'] = hashlib.sha256(json.dumps(result[key], sort_keys=True).encode()).hexdigest()
    if isinstance(result.get('body'), dict):
        record['usage'] = result['body'].get('usage')
    return record


def contract_suite(probe: Probe) -> list[dict[str, Any]]:
    records = []
    schema = {'type': 'object', 'properties': {'replacement': {'type': 'string'}},
              'required': ['replacement'], 'additionalProperties': False}
    for model in MODELS:
        body = payload(model, 'Fix Python def first(xs): return xs[1] so it returns the first item. '
                       'Return JSON with replacement equal to the corrected return statement, no explanation.')
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'fix', 'strict': True, 'schema': schema}}
        result = probe.request('/v1/chat/completions', body=body)
        passed = False
        try:
            content = result['body']['choices'][0]['message']['content']
            parsed = json.loads(content)
            passed = result['status'] == 200 and parsed == {'replacement': 'return xs[0]'}
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        records.append({'case': 'structured_bugfix', 'model': model, 'passed': passed, **scrub(result)})
        body = payload(model, 'Use lookup_service to inspect service gateway on host ai-5820-01.')
        body['tools'] = [{'type': 'function', 'function': {'name': 'lookup_service', 'description': 'Inspect a service',
                          'parameters': {'type': 'object', 'properties': {'host': {'type': 'string'}, 'service': {'type': 'string'}},
                                         'required': ['host', 'service'], 'additionalProperties': False}}}]
        body['tool_choice'] = {'type': 'function', 'function': {'name': 'lookup_service'}}
        tool_request = dict(body)
        result = probe.request('/v1/chat/completions', body=body)
        try:
            calls = result['body']['choices'][0]['message']['tool_calls']
            call = calls[0]
            passed = (result['status'] == 200 and len(calls) == 1 and bool(call.get('id'))
                      and call['function']['name'] == 'lookup_service'
                      and json.loads(call['function']['arguments']) == {'host': 'ai-5820-01', 'service': 'gateway'})
        except (KeyError, IndexError, TypeError, ValueError):
            passed = False
        records.append({'case': 'tool_arguments', 'model': model, 'passed': passed, **scrub(result)})
        # Follow the real wire contract back through a tool-result message.
        if passed:
            body = payload(model, 'Use lookup_service to inspect service gateway on host ai-5820-01.')
            body['messages'] += [result['body']['choices'][0]['message'],
                {'role': 'tool', 'tool_call_id': call['id'], 'content': '{"state":"active"}'},
                {'role': 'user', 'content': 'Reply with exactly ACTIVE.'}]
            final = probe.request('/v1/chat/completions', body=body)
            try:
                passed = final['status'] == 200 and final['body']['choices'][0]['message']['content'].strip() == 'ACTIVE'
            except (KeyError, IndexError, TypeError):
                passed = False
            records.append({'case': 'tool_result_roundtrip', 'model': model, 'passed': passed, **scrub(final)})
        result = probe.request('/v1/chat/completions', body=payload(model, 'Reply with exactly READY.', True))
        text = ''.join(c.get('delta', {}).get('content', '') or '' for e in result.get('events', []) for c in e.get('choices', []))
        passed = result['status'] == 200 and result.get('done') is True and text.strip() == 'READY'
        records.append({'case': 'unconstrained_exact_text', 'model': model, 'passed': passed, **scrub(result)})
        wire_ok = result['status'] == 200 and result.get('done') is True and bool(text.strip())
        wire_ok = wire_ok and any(c.get('finish_reason') == 'stop' for e in result.get('events', []) for c in e.get('choices', []))
        records.append({'case': 'sse_wire_contract', 'model': model, 'passed': wire_ok, **scrub(result)})
        result = probe.request('/v1/chat/completions', body={**tool_request, 'stream': True})
        assembled: dict[int, dict[str, str]] = {}
        for event in result.get('events', []):
            for choice in event.get('choices', []):
                for delta in choice.get('delta', {}).get('tool_calls', []):
                    call = assembled.setdefault(delta.get('index', 0), {'id': '', 'name': '', 'arguments': ''})
                    call['id'] += delta.get('id', '') or ''
                    for key in ['name', 'arguments']:
                        call[key] += delta.get('function', {}).get(key, '') or ''
        try:
            call = assembled[0]
            passed = (result['status'] == 200 and result.get('done') is True and len(assembled) == 1
                      and bool(call['id']) and call['name'] == 'lookup_service'
                      and json.loads(call['arguments']) == {'host': 'ai-5820-01', 'service': 'gateway'})
        except (KeyError, TypeError, ValueError):
            passed = False
        records.append({'case': 'sse_tool_arguments', 'model': model, 'passed': passed, **scrub(result)})
        body = payload(model, 'Reply with exactly READY.', True)
        body['grammar'] = 'root ::= "READY"'
        result = probe.request('/v1/chat/completions', body=body)
        text = ''.join(c.get('delta', {}).get('content', '') or '' for e in result.get('events', []) for c in e.get('choices', []))
        passed = result['status'] == 200 and result.get('done') is True and text.strip() == 'READY'
        records.append({'case': 'grammar_constrained_stream', 'model': model, 'passed': passed, **scrub(result)})
    return records


def soak(probe: Probe, duration: int, output: Path, record: dict[str, Any]) -> None:
    samples: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    stop = threading.Event()
    def monitor() -> None:
        i = 0
        while not stop.is_set():
            result = probe.request('/health?strict=true', 'ansible-admin')
            sample = {'seconds': result['seconds'], 'status': result['status'],
                      'ready': result.get('body', {}).get('ready'), 'elapsed': time.monotonic() - start}
            if i % 10 == 0:
                try:
                    sample.update(probe.resources())
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    sample['resource_error'] = type(error).__name__
            samples.append(sample)
            i += 1
            stop.wait(1)
    start = time.monotonic()
    thread = threading.Thread(target=monitor)
    thread.start()
    pending: dict[concurrent.futures.Future, tuple[int, str, str]] = {}
    def finish(future: concurrent.futures.Future) -> None:
        i, model, client = pending.pop(future)
        result = future.result()
        passed = result['status'] == 200 and (result.get('done') is True if i % 2 == 0 else bool(result.get('body', {}).get('choices')))
        requests.append({'index': i, 'model': model, 'client': client, 'passed': passed, **scrub(result)})
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            i = 0
            next_at = start
            checkpoint_at = start
            while time.monotonic() - start < duration:
                for f in list(pending):
                    if f.done():
                        finish(f)
                if len(pending) < 2 and time.monotonic() >= next_at and i < 500:
                    model = MODELS[(i // 2) % 2]
                    client = 'qualification' if i % 4 == 0 else 'operator'
                    body = payload(model, f'Probe {i}: Explain in one sentence why service health and process liveness differ.', i % 2 == 0)
                    pending[pool.submit(probe.request, '/v1/chat/completions', client, body, None, i % 10 == 0)] = (i, model, client)
                    next_at = time.monotonic() + 3
                    i += 1
                record.update({'health_samples': samples, 'requests': requests, 'state': 'running'})
                if time.monotonic() >= checkpoint_at:
                    save(output, record)
                    checkpoint_at = time.monotonic() + 10
                stop.wait(.25)
            for f in list(pending):
                finish(f)
    finally:
        stop.set()
        thread.join(15)
    summary = summarize(samples)
    summary['gates'].update({'enough_completions': len(requests) >= duration // 6,
                             'all_generations_succeeded': all(r['passed'] for r in requests),
                             'resource_sampling_succeeded': not any('resource_error' in s for s in samples)})
    for model in MODELS:
        timing = [r['ttft_seconds'] for r in requests if r['model'] == model and r.get('ttft_seconds') is not None]
        summary['measurements'][model] = {'stream_samples': len(timing), 'ttft_p50_seconds': percentile(timing, .5),
                                         'ttft_p95_seconds': percentile(timing, .95), 'ttft_p99_seconds': percentile(timing, .99)}
        # Initial bounded, short-prompt acceptance; not a long-context SLO.
        summary['gates'][model + '_short_prompt_ttft_p95'] = len(timing) >= 10 and percentile(timing, .95) < 10
    summary['passed'] = all(summary['gates'].values())
    record.update({'health_samples': samples, 'requests': requests, 'summary': summary, 'passed': summary['passed']})


def save(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['contracts', 'soak'])
    parser.add_argument('--base', default='https://10.0.8.5:8443')
    parser.add_argument('--ca', required=True)
    parser.add_argument('--ssh-host', default='mike@10.0.8.5')
    parser.add_argument('--expected-release', required=True)
    parser.add_argument('--duration', type=int, default=900)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.base.startswith('https://') or not 120 <= args.duration <= 3600:
        parser.error('TLS required; duration must be 120..3600 seconds')
    tokens = json.load(sys.stdin)
    probe = Probe(args.base, args.ca, tokens, args.ssh_host)
    health = probe.request('/health?strict=true', 'ansible-admin')
    if health.get('status') != 200 or health.get('body', {}).get('release_id') != args.expected_release:
        raise SystemExit('Expected ready release not observed; no workload started')
    record: dict[str, Any] = {'schema_version': 1, 'phase': args.phase,
        'started_at': datetime.now(timezone.utc).isoformat(), 'release_id': args.expected_release,
        'tls_verified': True, 'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'profile': 'bounded real-worker HTTP protocol probes; not an application-client or general intelligence benchmark'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if args.phase == 'contracts':
            record['cases'] = contract_suite(probe)
            record['passed'] = all(c['passed'] for c in record['cases'])
            record['protocol_passed'] = all(c['passed'] for c in record['cases'] if c['case'] != 'unconstrained_exact_text')
        else:
            soak(probe, args.duration, args.output, record)
        record['state'] = 'complete'
    except Exception as error:
        record.update({'state': 'failed', 'passed': False, 'error_type': type(error).__name__})
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        save(args.output, record)
    print(json.dumps({k: record[k] for k in ('phase', 'passed', 'state')}))
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
