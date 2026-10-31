"""Bounded opt-in queueing must preserve explicit aliases and never retry after dispatch."""
import time

import pytest

from orchestrator_runtime import CapabilityRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime, Router, RouteConfigError
from tests.test_orchestrator_runtime import worker

RULES = [
    {'id': 'fast', 'match': {'task_class': ['interactive-fast']}, 'pool': 'lead', 'fallback': ['deep'],
     'fallback_on_saturation': True, 'max_queue_wait_ms': 30},
    {'id': 'default', 'match': {}, 'pool': 'lead'},
]


def runtime(tmp_path):
    lead, deep = worker('lead'), worker('deep')
    object.__setattr__(lead, 'pool', 'lead'); object.__setattr__(deep, 'pool', 'deep')
    for w in (lead, deep): object.__setattr__(w, 'max_concurrency', 1)
    r = OrchestratorRuntime(CapabilityRegistry([lead, deep]),
        {'lead': InMemoryAdapter('lead'), 'deep': InMemoryAdapter('deep')}, EvidenceStore(tmp_path / 'e.jsonl'),
        router=Router.from_config(RULES, {'engineering/lead': 'lead'}))
    return r


def hold(r, pool):
    return r.admission.acquire(r.admission.new_ticket(pool), lambda: [pool])


def close(r):
    for name in ('http_dispatch', 'http_tokenize'):
        executor = getattr(r, name, None)
        if executor is not None: executor.shutdown()


def test_fast_route_uses_available_fallback_without_waiting_for_long_primary(tmp_path):
    r = runtime(tmp_path); hold(r, 'lead')
    try:
        start = time.monotonic()
        result = r.complete({'model': 'engineering/b0', 'messages': [{'role': 'user', 'content': 'hello'}]}, task_class='interactive-fast')
        assert result['status'] == 'ok' and result['route']['worker_id'] == 'deep'
        assert result['route']['fallback_used']
        assert time.monotonic() - start < .3
    finally:
        r.admission.release('lead', ok=True); close(r)


def test_both_busy_return_retryable_capacity_before_overall_deadline(tmp_path):
    r = runtime(tmp_path); hold(r, 'lead'); hold(r, 'deep')
    try:
        start = time.monotonic()
        result = r.complete({'model': 'engineering/b0', 'messages': [{'role': 'user', 'content': 'hello'}]}, task_class='interactive-fast', deadline_ms=1000)
        assert result['http_status'] == 429 and result['failure_class'] == 'capacity_exhausted'
        assert result['retry_after'] > 0
        assert time.monotonic() - start < .3
    finally:
        for p in ('lead', 'deep'):r.admission.release(p, ok=True)
        close(r)


def test_pinned_alias_keeps_its_model_and_own_deadline(tmp_path):
    r = runtime(tmp_path); hold(r, 'lead')
    try:
        start = time.monotonic()
        result = r.complete({'model': 'engineering/lead', 'messages': [{'role': 'user', 'content': 'hello'}]}, task_class='interactive-fast', deadline_ms=120)
        assert result['http_status'] == 504 and result['failure_class'] == 'deadline_exceeded'
        assert time.monotonic() - start >= .10
        assert not any(e.get('worker_id') == 'deep' for e in r.evidence.records())
    finally:
        r.admission.release('lead', ok=True); close(r)


@pytest.mark.parametrize('value', [0, -1, True, 1.5, '100', 120001])
def test_invalid_queue_budgets_are_rejected(value):
    with pytest.raises(RouteConfigError):
        Router.from_config([{**RULES[0], 'max_queue_wait_ms': value}, RULES[1]], {})


def test_asgi_reports_fallback_and_retry_after_over_the_supported_wire_contract(tmp_path):
    import asyncio
    httpx = pytest.importorskip('httpx')
    pytest.importorskip('starlette')
    from orchestrator_gateway import create_asgi_gateway
    r = runtime(tmp_path); hold(r, 'lead')
    app = create_asgi_gateway(r, 'fixture-token')
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture',
            headers={'Authorization': 'Bearer fixture-token', 'X-Task-Class': 'interactive-fast'}) as client:
            request = {'model': 'engineering/b0', 'messages': [{'role': 'user', 'content': 'hello'}]}
            response = await client.post('/v1/chat/completions', json=request)
            assert response.status_code == 200
            assert 'worker=deep;fallback=true' in response.headers['X-AIHost-Route']
            hold(r, 'deep')
            try:
                response = await client.post('/v1/chat/completions', json=request)
                assert response.status_code == 429 and int(response.headers['Retry-After']) > 0
            finally:r.admission.release('deep', ok=True)
    try:asyncio.run(exercise())
    finally:r.admission.release('lead', ok=True); close(r)


def test_fallback_does_not_bypass_client_pool_authority(tmp_path):
    from orchestrator_runtime.clients import Client
    r = runtime(tmp_path); hold(r, 'lead')
    client = Client('restricted', '0' * 64, frozenset({'workload'}), allowed_pools=frozenset({'lead'}))
    try:
        result = r.complete({'model': 'engineering/b0', 'messages': [{'role': 'user', 'content': 'hello'}]},
                            task_class='interactive-fast', client=client)
        assert result['http_status'] == 429
        assert not any(e.get('worker_id') == 'deep' for e in r.evidence.records())
    finally:r.admission.release('lead', ok=True); close(r)


def test_request_deadline_still_preempts_the_route_queue_budget(tmp_path):
    r = runtime(tmp_path); hold(r, 'lead')
    try:
        result = r.complete({'model': 'engineering/b0', 'messages': [{'role': 'user', 'content': 'hello'}]},
                            task_class='interactive-fast', deadline_ms=10)
        assert result['http_status'] == 504
        assert not any(e.get('worker_id') == 'deep' for e in r.evidence.records())
    finally:r.admission.release('lead', ok=True); close(r)


def test_explicit_interactive_model_is_discoverable_with_both_serving_pools(tmp_path):
    r = runtime(tmp_path)
    rules = [{**RULES[0], 'id': 'interactive-model', 'match': {'model': ['engineering/interactive']}}, RULES[1]]
    r.router = Router.from_config(rules, {'engineering/lead': 'lead'})
    try:
        views = r.alias_view()
        view = next(v for v in views if v['id'] == 'engineering/interactive')
        assert {s['pool'] for s in view['serving']} == {'lead', 'deep'}
        hold(r, 'lead')
        result = r.complete({'model': 'engineering/interactive', 'messages': [{'role': 'user', 'content': 'hello'}]})
        assert result['status'] == 'ok' and result['route']['worker_id'] == 'deep'
    finally:r.admission.release('lead', ok=True); close(r)


def test_legacy_model_selection_also_respects_client_pool_authority(tmp_path):
    from orchestrator_runtime.clients import Client
    r = runtime(tmp_path); r.router = None
    client = Client('restricted', '0' * 64, frozenset({'workload'}), allowed_pools=frozenset({'lead'}))
    try:
        result = r.complete({'model': 'engineering/deep', 'messages': [{'role': 'user', 'content': 'hello'}]}, client=client)
        assert result['status'] != 'ok'
        assert r.adapters['deep'].calls == 0
    finally:close(r)
