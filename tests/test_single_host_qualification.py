"""Qualification must not issue a pass when observations are missing or degraded."""
import copy

import pytest

from evaluations.qualify_single_host import percentile, scrub, summarize


def observations():
    return [{'status': 200, 'ready': True, 'seconds': .05, 'memory': 32 * 1024**2,
             'pid': 12, 'fds': 20, 'tasks': 5} for _ in range(120)]


def test_clean_measurements_pass_and_report_nearest_rank_tail():
    result = summarize(observations())
    assert result['passed']
    assert result['measurements']['health_samples'] == 120
    assert percentile([1, 2, 3, 4], .95) == 4
    assert percentile([], .99) is None


@pytest.mark.parametrize('failure', ['health_error', 'not_ready', 'slow_health', 'memory_growth',
                                     'memory_limit', 'process_change', 'fds', 'tasks', 'missing_resources'])
def test_failed_observation_cannot_be_qualified(failure):
    samples = observations()
    if failure == 'health_error':
        samples[-1]['status'] = 503
    elif failure == 'not_ready':
        samples[-1]['ready'] = False
    elif failure == 'slow_health':
        for sample in samples[-3:]:
            sample['seconds'] = .5
    elif failure in ('memory_growth', 'memory_limit'):
        for sample in samples[-40:]:
            sample['memory'] = (60 if failure == 'memory_growth' else 600) * 1024**2
    elif failure == 'process_change':
        samples[-1]['pid'] = 13
    elif failure in ('fds', 'tasks'):
        samples[-1][failure] = 100
    else:
        for sample in samples:
            for key in ('memory', 'pid', 'fds', 'tasks'):
                del sample[key]
    assert not summarize(samples)['passed']


def test_no_or_insufficient_samples_fail():
    assert not summarize([])['passed']
    assert not summarize(observations()[:3])['passed']


def test_receipt_scrubs_generated_content_and_keeps_usage():
    original = {'status': 200, 'body': {'choices': [{'message': {'content': 'PRIVATE'}}],
                                      'usage': {'total_tokens': 4}},
                'events': [{'choices': [{'delta': {'content': 'PRIVATE'}}]}]}
    before = copy.deepcopy(original)
    result = scrub(original)
    assert 'body' not in result and 'events' not in result
    assert 'PRIVATE' not in str(result)
    assert result['usage']['total_tokens'] == 4
    assert original == before


def test_http_error_retains_health_payload_in_memory_but_scrubs_receipt(monkeypatch):
    import io
    import ssl
    import urllib.error
    import urllib.request
    from evaluations.qualify_single_host import Probe

    monkeypatch.setattr(ssl, 'create_default_context', lambda **kwargs: None)
    body = io.BytesIO(b'{"status":"degraded","ready":true}')
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError('https://fixture/health', 503, 'degraded', {}, body)
    monkeypatch.setattr(urllib.request, 'urlopen', fail)
    probe = Probe('https://fixture', 'fixture-ca', {'operator': 'fixture-token'}, 'fixture')
    result = probe.request('/health')
    assert result['status'] == 503
    assert result['body'] == {'status': 'degraded', 'ready': True}
    assert 'body' not in scrub(result)
    assert body.closed
