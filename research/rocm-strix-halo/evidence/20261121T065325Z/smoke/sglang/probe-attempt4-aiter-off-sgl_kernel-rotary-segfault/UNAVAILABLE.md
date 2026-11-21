# SGLang UNAVAILABLE on gfx1151 / ROCm 7.2.0 (probe)

- status: unavailable (not a zero-throughput result; no metrics exist)
- image: `docker.io/lmsysorg/sglang@sha256:a3a6eb293187b20012a5abc8f00423e6ab51d0169113a6e58a91da5614200170`
- reason: chat request failed (rc=1)
- command: see run_cmd.txt; image details: image.txt

## Last 60 log lines
```
    return await self.app(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/fastapi/applications.py", line 1194, in __call__
    await super().__call__(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/starlette/applications.py", line 96, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/starlette/middleware/errors.py", line 164, in __call__
    await self.app(scope, receive, _send)
  File "/opt/venv/lib/python3.10/site-packages/fastapi/telemetry/_asgi.py", line 151, in __call__
    await self.app(scope, receive, send)
  File "/sgl-workspace/sglang/python/sglang/srt/utils/http_middleware_patch.py", line 50, in __call__
    await self.dispatch(request, call_next)
  File "/sgl-workspace/sglang/python/sglang/srt/observability/http_request_metrics.py", line 79, in track_http_status_code
    return await call_next(request)
  File "/sgl-workspace/sglang/python/sglang/srt/utils/http_middleware_patch.py", line 47, in call_next
    await self.app(scope, receive, send_and_capture)
  File "/opt/venv/lib/python3.10/site-packages/starlette/middleware/cors.py", line 91, in __call__
    await self.simple_response(scope, receive, send, request_headers=headers)
  File "/opt/venv/lib/python3.10/site-packages/starlette/middleware/cors.py", line 149, in simple_response
    await self.app(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/starlette/middleware/exceptions.py", line 63, in __call__
    await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/opt/venv/lib/python3.10/site-packages/fastapi/middleware/asyncexitstack.py", line 18, in __call__
    await self.app(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/starlette/routing.py", line 676, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/fastapi/routing.py", line 2811, in app
    await route.handle(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/fastapi/routing.py", line 1330, in handle
    await super().handle(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/starlette/routing.py", line 282, in handle
    await self.app(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/fastapi/routing.py", line 166, in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
  File "/opt/venv/lib/python3.10/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/opt/venv/lib/python3.10/site-packages/fastapi/routing.py", line 152, in app
    response = await f(request)
  File "/sgl-workspace/sglang/python/sglang/srt/entrypoints/http_server.py", line 489, in custom_handler
    return await original_handler(ORJSONRequest(request.scope, request.receive))
  File "/opt/venv/lib/python3.10/site-packages/fastapi/routing.py", line 745, in app
    raw_response = await run_endpoint_function(
  File "/opt/venv/lib/python3.10/site-packages/fastapi/routing.py", line 372, in run_endpoint_function
    return await dependant.call(**values)
  File "/sgl-workspace/sglang/python/sglang/srt/entrypoints/http_server.py", line 940, in generate_request
    return await serve_generate_request(obj, request)
  File "/sgl-workspace/sglang/python/sglang/srt/entrypoints/http_server.py", line 984, in serve_generate_request
    ret = await _global_state.tokenizer_manager.generate_request(
  File "/sgl-workspace/sglang/python/sglang/srt/managers/tokenizer_manager.py", line 951, in generate_request
    async for response in self._wait_one_response(obj, request):
  File "/sgl-workspace/sglang/python/sglang/srt/managers/tokenizer_manager.py", line 1960, in _stream_one_response
    await asyncio.wait_for(
  File "/usr/lib/python3.10/asyncio/tasks.py", line 451, in wait_for
    await _cancel_and_wait(fut, loop=loop)
  File "/usr/lib/python3.10/asyncio/tasks.py", line 518, in _cancel_and_wait
    await waiter
asyncio.exceptions.CancelledError
[2026-11-21 07:23:17] INFO:     127.0.0.1:48662 - "POST /generate HTTP/1.1" 500 Internal Server Error
[2026-11-21 07:23:17] kill_process_tree called: parent_pid=1, include_parent=False, pid=1
```
