# SGLang UNAVAILABLE on gfx1151 / ROCm 7.2.0 (probe)

- status: unavailable (not a zero-throughput result; no metrics exist)
- image: `docker.io/lmsysorg/sglang@sha256:a3a6eb293187b20012a5abc8f00423e6ab51d0169113a6e58a91da5614200170`
- reason: container exited before ready (exit 0)
- command: see run_cmd.txt; image details: image.txt

## Last 60 log lines
```
  151 |                 hipFree(ptr);
      |                 ^~~~~~~~~~~~
/sgl-workspace/aiter/csrc/include/aiter_tensor.h:175:21: warning: ignoring return value of type 'hipError_t' declared with 'nodiscard' attribute [-Wunused-value]
  175 |                     hipFreeAsync(ptr, stream_);
      |                     ^~~~~~~~~~~~~~~~~~~~~~~~~~
/sgl-workspace/aiter/csrc/include/aiter_tensor.h:177:21: warning: ignoring return value of type 'hipError_t' declared with 'nodiscard' attribute [-Wunused-value]
  177 |                     hipFree(ptr);
      |                     ^~~~~~~~~~~~
5 warnings generated when compiling for host.
ninja: build stopped: subcommand failed.

[31mfailed jit build [module_custom_all_reduce][0m↑↑↑↑↑↑↑↑↑↑
[aiter] [pid=136 pname=Process-1] [32mfinish build [module_custom_all_reduce], cost 9.5s [0m
[aiter] Custom allreduce is disabled: [aiter] build [module_custom_all_reduce] under /sgl-workspace/aiter/aiter/jit/build/module_custom_all_reduce/build failed !!!!!!
[2026-11-21 07:08:45] Ignore import error when loading sglang.srt.models.falcon_mamba: cannot import name 'causal_conv1d_fn' from 'sglang.srt.layers.attention.mamba.mamba' (/sgl-workspace/sglang/python/sglang/srt/layers/attention/mamba/mamba.py)
/opt/venv/lib/python3.10/site-packages/apex/transformer/functional/fused_rope.py:49: UserWarning: Aiter backend is selected for fused RoPE. This has lower precision. To disable aiter, export USE_ROCM_AITER_ROPE_BACKEND=0
  warnings.warn("Aiter backend is selected for fused RoPE. This has lower precision. To disable aiter, export USE_ROCM_AITER_ROPE_BACKEND=0", UserWarning)
[2026-11-21 07:08:45] Ignore import error when loading sglang.srt.models.inkling: No module named 'cutlass'
[2026-11-21 07:08:46] Ignore import error when loading sglang.srt.models.mamba: cannot import name 'causal_conv1d_fn' from 'sglang.srt.layers.attention.mamba.mamba' (/sgl-workspace/sglang/python/sglang/srt/layers/attention/mamba/mamba.py)
[2026-11-21 07:08:46] Load weight begin. avail mem=115.80 GB
Multi-thread loading shards:   0% Completed | 0/3 [00:00<?, ?it/s]Multi-thread loading shards:  33% Completed | 1/3 [00:01<00:02,  1.27s/it]Multi-thread loading shards:  67% Completed | 2/3 [00:02<00:01,  1.26s/it]Multi-thread loading shards: 100% Completed | 3/3 [00:02<00:00,  1.17it/s]
[2026-11-21 07:08:49] Load weight end. elapsed=3.16 s, type=Qwen3ForCausalLM, avail mem=107.92 GB, mem usage=7.88 GB.
[2026-11-21 07:08:53] Scheduler hit an exception: Traceback (most recent call last):
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 6362, in run_scheduler_process
    scheduler = Scheduler(server_args, port_args)
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 568, in __init__
    self.init_model_worker()
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 1137, in init_model_worker
    self.init_memory_pools()
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 1100, in init_memory_pools
    self.init_target_memory_pool()
  File "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py", line 1090, in init_target_memory_pool
    self.tp_worker.alloc_memory_pool(
  File "/sgl-workspace/sglang/python/sglang/srt/managers/tp_worker.py", line 409, in alloc_memory_pool
    self.model_runner.alloc_memory_pool(
  File "/sgl-workspace/sglang/python/sglang/srt/model_executor/model_runner.py", line 982, in alloc_memory_pool
    result = self.kv_cache_configurator.configure(
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/kv_cache_configurator.py", line 480, in configure
    pools = self._init_pools(
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/kv_cache_configurator.py", line 777, in _init_pools
    token_to_kv_pool = self._build_token_to_kv_pool(
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/kv_cache_configurator.py", line 1915, in _build_token_to_kv_pool
    token_to_kv_pool = self._build_mha_kv_pool(
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/kv_cache_configurator.py", line 2775, in _build_mha_kv_pool
    token_to_kv_pool = pool_cls(
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/memory_pool.py", line 2293, in __init__
    self._create_buffers()
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/memory_pool.py", line 2451, in _create_buffers
    self._create_buffers_normal()
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/memory_pool.py", line 2640, in _create_buffers_normal
    fused = [
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/memory_pool.py", line 2641, in <listcomp>
    _zeros((2, padded, *k_shape[1:]))
  File "/sgl-workspace/sglang/python/sglang/srt/mem_cache/memory_pool.py", line 2626, in _zeros
    return torch.zeros(
torch.OutOfMemoryError: HIP out of memory. Tried to allocate 2.31 GiB. GPU 0 has a total capacity of 61.35 GiB of which 236.52 MiB is free. Of the allocated memory 60.89 GiB is allocated by PyTorch, and 50.51 MiB is reserved by PyTorch but unallocated. If reserved but unallocated memory is large try setting PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True to avoid fragmentation.  See documentation for Memory Management  (https://pytorch.org/docs/stable/notes/cuda.html#environment-variables)

[2026-11-21 07:08:53] Received sigquit from a child process. It usually means the child failed.
[2026-11-21 07:08:53] kill_process_tree called: parent_pid=1, include_parent=True, pid=1
[2026-11-21 07:08:53] kill_process_tree called: parent_pid=1, include_parent=False, pid=1
```
