# SGLang UNAVAILABLE on gfx1151 / ROCm 7.2.0 (probe)

- status: unavailable (not a zero-throughput result; no metrics exist)
- image: `docker.io/lmsysorg/sglang@sha256:a3a6eb293187b20012a5abc8f00423e6ab51d0169113a6e58a91da5614200170`
- reason: container exited before ready (exit 0)
- command: see run_cmd.txt; image details: image.txt

## Last 60 log lines
```
  File "/sgl-workspace/sglang/python/sglang/srt/models/qwen3.py", line 296, in forward_prepare_aiter_fused
    q = aiter_fused_qk_norm_rope_set_kv(
  File "/sgl-workspace/sglang/python/sglang/srt/models/qwen3.py", line 138, in aiter_fused_qk_norm_rope_set_kv
    fused_qk_norm_rope_cache_pts_quant_shuffle(**kernel_kwargs)
  File "/sgl-workspace/aiter/aiter/jit/utils/torch_guard.py", line 294, in wrapper_custom
    getattr(torch.ops.aiter, f"{loadName}")(*args, **kwargs)
  File "/opt/venv/lib/python3.10/site-packages/torch/_ops.py", line 1255, in __call__
    return self._op(*args, **kwargs)
  File "/sgl-workspace/aiter/aiter/jit/utils/torch_guard.py", line 317, in outer_wrapper
    wrapper(*args, **kwargs)
  File "/sgl-workspace/aiter/aiter/jit/utils/torch_guard.py", line 211, in wrapper
    return func(*args, **kwargs)
  File "/sgl-workspace/aiter/aiter/jit/core.py", line 2481, in custom_wrapper
    return wrapper(*args, **kwargs)
  File "/sgl-workspace/aiter/aiter/jit/core.py", line 2231, in wrapper
    build_module(
  File "/sgl-workspace/aiter/aiter/jit/core.py", line 1586, in build_module
    mp_lock(
  File "/sgl-workspace/aiter/aiter/jit/core.py", line 78, in mp_lock
    ret = MainFunc()
  File "/sgl-workspace/aiter/aiter/jit/core.py", line 1548, in MainFunc
    raise_build_error(error)
  File "/sgl-workspace/aiter/aiter/jit/core.py", line 1336, in raise_build_error
    raise RuntimeError(
RuntimeError: [aiter] build [module_fused_qk_norm_rope_cache_quant_shuffle] under /sgl-workspace/aiter/aiter/jit/build/module_fused_qk_norm_rope_cache_quant_shuffle/build failed !!!!!!

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 6362, in run_scheduler_process
    scheduler = Scheduler(server_args, port_args)
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 568, in __init__
    self.init_model_worker()
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 1146, in init_model_worker
    self.init_all_cuda_graphs()
  File "/opt/venv/lib/python3.10/site-packages/torch/utils/_contextlib.py", line 120, in decorate_context
    return func(*args, **kwargs)
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 1124, in init_all_cuda_graphs
    self.tp_worker.init_cuda_graphs()
  File "/sgl-workspace/sglang/python/sglang/srt/managers/tp_worker.py", line 435, in init_cuda_graphs
    self.model_runner.init_cuda_graphs(
  File "/sgl-workspace/sglang/python/sglang/srt/model_executor/model_runner.py", line 1192, in init_cuda_graphs
    capture = capture_cuda_graphs(
  File "/sgl-workspace/sglang/python/sglang/srt/model_executor/model_runner_components/cuda_graph_setup.py", line 437, in capture_cuda_graphs
    decode = capture_decode_graph(model_runner=model_runner)
  File "/sgl-workspace/sglang/python/sglang/srt/model_executor/model_runner_components/cuda_graph_setup.py", line 780, in capture_decode_graph
    runner = GraphRunnerCls(model_runner)
  File "/sgl-workspace/sglang/python/sglang/srt/model_executor/runner/decode_cuda_graph_runner.py", line 602, in __init__
    raise Exception(
Exception: Capture cuda graph failed: [aiter] build [module_fused_qk_norm_rope_cache_quant_shuffle] under /sgl-workspace/aiter/aiter/jit/build/module_fused_qk_norm_rope_cache_quant_shuffle/build failed !!!!!!
Possible solutions:
1. set --mem-fraction-static to a smaller value (e.g., 0.8 or 0.7)
2. set --cuda-graph-max-bs-decode to a smaller value (e.g., 16)
3. disable decode CUDA graph by --cuda-graph-backend-decode=disabled. (Not recommended. Huge performance loss)
Open an issue on GitHub https://github.com/sgl-project/sglang/issues/new/choose 


[2026-11-21 07:10:37] Received sigquit from a child process. It usually means the child failed.
[2026-11-21 07:10:37] kill_process_tree called: parent_pid=1, include_parent=True, pid=1
[2026-11-21 07:10:37] kill_process_tree called: parent_pid=1, include_parent=False, pid=1
```
