# SGLang UNAVAILABLE on gfx1151 / ROCm 7.2.0 (probe)

- status: unavailable (not a zero-throughput result; no metrics exist)
- image: `docker.io/lmsysorg/sglang@sha256:a3a6eb293187b20012a5abc8f00423e6ab51d0169113a6e58a91da5614200170`
- reason: chat request failed (rc=1)
- command: see run_cmd.txt; image details: image.txt

## Last 60 log lines
```
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
[2026-11-21 07:12:00] INFO:     127.0.0.1:57820 - "POST /generate HTTP/1.1" 500 Internal Server Error
[2026-11-21 07:12:00] Initialization failed. warmup error: Traceback (most recent call last):
  File "/sgl-workspace/sglang/python/sglang/srt/entrypoints/http_server.py", line 2501, in _execute_server_warmup
    assert res.status_code == 200, f"{res.text}"
AssertionError: Internal Server Error

[2026-11-21 07:12:00] kill_process_tree called: parent_pid=1, include_parent=True, pid=1
[2026-11-21 07:12:00] ERROR:    Traceback (most recent call last):
  File "/opt/venv/lib/python3.10/site-packages/uvicorn/_compat.py", line 60, in asyncio_run
    return loop.run_until_complete(main)
  File "uvloop/loop.pyx", line 1509, in uvloop.loop.Loop.run_until_complete
  File "uvloop/loop.pyx", line 1502, in uvloop.loop.Loop.run_until_complete
  File "uvloop/loop.pyx", line 1371, in uvloop.loop.Loop.run_forever
  File "uvloop/loop.pyx", line 551, in uvloop.loop.Loop._run
  File "uvloop/loop.pyx", line 471, in uvloop.loop.Loop._on_idle
  File "uvloop/cbhandles.pyx", line 86, in uvloop.loop.Handle._run
  File "uvloop/cbhandles.pyx", line 64, in uvloop.loop.Handle._run
  File "/sgl-workspace/sglang/python/sglang/srt/managers/tokenizer_manager.py", line 4081, in running_phase_sigquit_handler
    kill_process_tree(os.getpid())
  File "/sgl-workspace/sglang/python/sglang/srt/utils/common.py", line 2552, in kill_process_tree
    sys.exit(0)
SystemExit: 0

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/opt/venv/lib/python3.10/site-packages/starlette/routing.py", line 661, in lifespan
    await receive()
  File "/opt/venv/lib/python3.10/site-packages/fastapi/telemetry/_runtime.py", line 214, in wrapped_receive
    message = await receive()
  File "/opt/venv/lib/python3.10/site-packages/uvicorn/lifespan/on.py", line 137, in receive
    return await self.receive_queue.get()
  File "/usr/lib/python3.10/asyncio/queues.py", line 159, in get
    await getter
asyncio.exceptions.CancelledError

[2026-11-21 07:12:00] kill_process_tree called: parent_pid=1, include_parent=False, pid=1
```
