# Slot-state persistence (llama.cpp conversation state across restarts)

A worker restart discards the conversation state (KV cache and, for the hybrid models, recurrent state) held in its slot, so the next turn of a long
conversation pays a cold prefill (an 18k-token conversation: 14.6 s on Qwen3.6). llama.cpp can save a slot to a file and restore it; measured on the
deployed build (2026-11-17, window-3 README): save 0.18 s (567 MB for 18k tokens), restore 2.8 s, next turn 0.38 s with 18,011 of 18,015 tokens reused.

## How it works here
- **Workers:** `llama_cpp_container_slot_persistence: true` (default) adds `--slot-save-path /slots` and mounts `<home>/slots/<worker_id>` (mode 0700, the runtime
  account) at `/slots`. The state is conversation-derived data; nothing outside that account can read it.
- **Gateway:** `POST /admin/workers/<id>/slot/<save|restore>` (admin scope, remote origin only; the gateway holds the worker credential, worker ports stay closed).
  The file name is derived by the gateway as `<worker_id>-<fingerprint>.bin`, never taken from the caller; the fingerprint hashes the model artifact digest, runtime
  image digest, model id and context window, so a restart that changes the model or image finds no file and starts cold (restore answers `unavailable`).
  The gateway never exposes `/slots` itself and its evidence records hold counts only (tokens, bytes), no names or content.
- **Planned restarts (Ansible):** `roles/llama_cpp_container/tasks/start_worker.yml` saves after the worker is drained and idle, restores once it is healthy and still drained, then
  undrains. Both steps are best effort: a failure means a cold start, never a failed deployment.
- **Watchdog restarts:** `scripts/worker_watchdog.py --slot-save-interval 300` saves an idle worker at most every 5 minutes, and only if it completed work since its last save (a state file is hundreds of MB, 356 MB even for a short Flash-Next conversation, so an unchanged state is never rewritten), and restores a restarted worker before readmitting it. A
  wedged worker cannot save, so recovery uses the last idle save (a stale state is harmless: reuse needs a prefix match, otherwise llama.cpp discards it).

## Operating it
- Turn off: `llama_cpp_container_slot_persistence: false` (removes the flag and mount at the next unit change); watchdog: `reconcile_controller_watchdog_slot_save_interval: 0`.
- State files are overwritten in place (one per worker and fingerprint); remove stale ones with `rm <home>/slots/<worker_id>/*` while the worker is stopped.
- Limits: slot 0 only (workers run `-np 1`); one file per worker (the last conversation, not all of them); a file is as large as the saved context (about 30 KB per token on Qwen3.6).
