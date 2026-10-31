"""Bounded HTTP ingress and execution; independent of the default asyncio executor."""
from __future__ import annotations

import asyncio
import functools
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor


class IngressError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


async def read_object(request, max_bytes, timeout):
    async def read():
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > max_bytes:
                raise IngressError(413, "request body exceeds configured byte limit")
            body.extend(chunk)
        try:
            value = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise IngressError(400, "invalid JSON") from None
        if not isinstance(value, dict):
            raise IngressError(400, "request body must be a JSON object")
        return value
    try:
        return await asyncio.wait_for(read(), timeout)
    except asyncio.TimeoutError:
        raise IngressError(408, "request body read timeout") from None


class ExecutionBusy(Exception):
    pass


class BoundedExecutor:
    """No hidden executor queue. Capacity is released by the real thread, not its HTTP caller."""
    def __init__(self, capacity, name, per_client_capacity=None):
        if capacity < 1:
            raise ValueError("executor capacity must be positive")
        self._clients = {}
        self._client_lock = threading.Lock()
        self._per_client = per_client_capacity or capacity
        self._slots = threading.BoundedSemaphore(capacity)
        self._pool = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix=name)

    def submit(self, function, *args, **kwargs):
        return self.submit_for(None, function, *args, **kwargs)

    def submit_for(self, client_id, function, *args, **kwargs):
        with self._client_lock:
            if self._clients.get(client_id, 0) >= self._per_client:
                raise ExecutionBusy()
            if not self._slots.acquire(blocking=False):
                raise ExecutionBusy()
            self._clients[client_id] = self._clients.get(client_id, 0) + 1

        def release(_=None):
            with self._client_lock:
                self._clients[client_id] -= 1
                if self._clients[client_id] == 0:
                    del self._clients[client_id]
            self._slots.release()
        try:
            future = self._pool.submit(functools.partial(function, *args, **kwargs))
        except BaseException:
            release()
            raise
        future.add_done_callback(release)
        return asyncio.wrap_future(future)

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


async def watch_disconnect(request, cancel):
    while not cancel.is_set():
        if await request.is_disconnected():
            cancel.set()
            return
        await asyncio.sleep(0.02)


class GatewayMetricsMiddleware:
    """Measure the complete ASGI lifetime, including streaming and rejection paths."""
    def __init__(self, app, runtime):
        self.app, self.runtime = app, runtime

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        known = {"/health": "health", "/metrics": "metrics", "/v1/models": "v1_models",
                 "/v1/routes": "v1_routes", "/v1/tokenize": "v1_tokenize",
                 "/v1/chat/completions": "v1_chat_completions", "/v1/outcomes": "v1_outcomes",
                 "/v1/outcomes/summary": "v1_outcomes_summary"}
        route = known.get(path, "admin" if path.startswith(("/admin", "/v1/admin")) else "unsupported")
        method = scope.get("method", "GET")
        method = method if method in {"GET", "POST", "HEAD", "OPTIONS", "PUT", "DELETE", "PATCH"} else "OTHER"
        metrics = self.runtime.metrics
        status, started = 500, time.monotonic()
        metrics.http_requests_in_flight.inc(route=route)

        async def observed(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
        try:
            await self.app(scope, receive, observed)
        except asyncio.CancelledError:
            status = 499
            raise
        finally:
            metrics.http_requests_in_flight.dec(route=route)
            metrics.http_requests_total.inc(route=route, method=method, status_class=f"{status // 100}xx")
            metrics.http_request_duration_seconds.observe(time.monotonic() - started, route=route, method=method)
