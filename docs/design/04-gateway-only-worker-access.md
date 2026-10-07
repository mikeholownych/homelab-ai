# Design 04: gateway-only access to inference workers

- **Status:** ACCEPTED (review below), 2026-10-07.
- **Covers:** todo.md "Policy: gateway-only access to inference workers".
- **Requirement (operator):**
  - no workload client can directly invoke an inference worker;
  - worker access is an internal gateway capability;
  - the solution is inventory-driven and enforced by Ansible;
  - candidate/ad-hoc servers must not create an unprotected bypass.

## Current state (verified 2026-10-07)
- Workers bind 127.0.0.1.
- Keys are 0400 `aihost-runtime`.
- The gateway runs as `aihost-runtime` (the same uid as the workers).
- ufw is hand-made (`8000/tcp DENY # AIHost-B0-temporary-api-block`; nothing for 8001).
- The evaluation reached workers directly by reading keys with sudo.

## Options evaluated

| Option | Mechanism | Pros | Cons | Verdict |
|---|---|---|---|---|
| A. Separate gateway uid + nftables `skuid` on loopback worker ports | Gateway runs as new system user `aihost-gateway`. `inet aihost_policy` output rule: traffic to any inventory worker/candidate port on `lo` is allowed only from `meta skuid aihost-gateway`; everything else is `counter reject with tcp reset`. | Engine-agnostic (llama.cpp, vLLM, anything on TCP). Kernel-enforced regardless of key possession. Counters give evidence. Inventory-driven port set. | Port-based: a server on an unlisted port is not covered (handled by the reserved port range plus vllm-top detection). Root can change rules (administrative authority, out of the workload threat model). | **SELECTED** |
| B. Unix sockets readable only by the gateway | Workers listen on a unix socket under a gateway-only directory. | No TCP surface. | Rootless podman bind-mount and socket permissions across the user namespace are fragile. llama.cpp unix-socket support is version-dependent; vLLM differs again. Breaks the existing engine_stats/HTTP tooling. | Rejected (engine coupling, operational risk) |
| C. Keys only | Rely on worker API keys. | Already present. | The key is readable by root/sudoers and the runtime account; it is not a boundary on its own. | Kept as defence in depth, not as the control |

## Selected design (A, with defence in depth)
1. **Identity separation:**
   - New system user/group `aihost-gateway` (Ansible `users` role). The gateway unit runs as it.
   - The release dir, evidence file and gateway state are owned by it.
   - The gateway leaves the `aihost-runtime` group (the unit currently sets `SupplementaryGroups=aihost-runtime video`; both are
     removed).
2. **Worker credentials:**
   - Worker key files stay `aihost-runtime:aihost-runtime 0400` (the container reads them).
   - The gateway receives them via systemd `LoadCredential=worker-<id>:<path>`, delivered by root into the gateway's private
     credentials dir. The gateway user cannot read the files directly, and the runtime user cannot read the gateway's copies.
   - `token_file` in the worker spec becomes the relative credential name (already supported by `__main__.worker_records`).
3. **Kernel enforcement (`roles/inference_policy`, new):**
   - `/etc/aihost/nftables/aihost-policy.nft` defines `table inet aihost_policy`, with:
     - set `worker_ports` = all `llama_cpp_container_workers[*].port` + candidate ports + `inference_reserved_port_ranges`
       (default `8000-8009, 8020-8029`);
     - set `gateway_uids` = the uid of `aihost-gateway`;
     - chain `output` (hook output, priority filter): `oifname "lo" tcp dport @worker_ports meta skuid != @gateway_uids
       counter name worker_direct_denied reject with tcp reset`;
     - chain `input` (hook input): `iifname != "lo" tcp dport @worker_ports counter name worker_remote_denied drop`. This covers
       a candidate or ad-hoc server bound to 0.0.0.0 on a reserved port.
   - Loaded by `aihost-inference-policy.service` (oneshot, `RemainAfterExit`, `Before=` every worker and the gateway).
     Worker units `Requires=` and are ordered after it, so if the policy cannot be loaded no worker starts (fail closed).
   - A separate table coexists with ufw. In nftables a drop/reject in any table is final, and an accept in ufw's table cannot
     override it.
   - The hand-made ufw temporary rules (`8000`, `4096:4099`) are removed by Ansible once this table is in place, so the policy is
     codified rather than tribal.
4. **Ansible health waits:** `start_worker.yml` waits on worker `/health` with `become_user: aihost-gateway`, so its socket carries
   the gateway uid and is allowed. No exception for root is needed.
5. **Candidates (R4):**
   - Candidate workers are inventory-declared, on reserved ports, and gateway-registered.
   - Ad-hoc servers on reserved ports are unreachable except from the gateway.
   - Ad-hoc servers on unreserved ports are not blocked locally. They are detected and flagged by vllm-top (Design 06) and remain
     remotely unreachable (Design 05 input policy).
6. **Detection:**
   - vllm-top marks any discovered inference server that is not a gateway-registered worker and not the gateway itself as
     `POLICY VIOLATION: outside gateway`.
   - The gateway exports `aihost_inference_policy_denied_total{direction}` by reading the named nft counters through a tiny root
     helper. Alternatively node_exporter's textfile collector writes them from the monitoring role. Selected: a textfile writer in
     the monitoring timer, because the gateway itself gets no root.
7. **Retire direct-worker qualification:**
   - `cand.sh`, `runqueue.sh` and on-host engx are removed from the host (evidence archived first).
   - `evaluations/engx` documents the gateway path only.

## Verification plan

| Check | Expected |
|---|---|
| `curl` as mike to 127.0.0.1:<each worker port> | connection reset; `worker_direct_denied` counter increments |
| a rootless podman process (aihost-runtime) to a worker port | reset |
| an `aihost-runtime` process other than the gateway | reset |
| a gateway → worker completion | succeeds |
| a remote host → 10.0.8.5:<worker port> | dropped; `worker_remote_denied` increments |
| an ad-hoc llama-server on an unreserved port | visible in vllm-top as a policy violation |
| reboot | policy loaded before workers (unit ordering); workers do not start if the policy fails to load |

## Review (2026-10-07)
- **Requirement coverage:**
  - Direct workload invocation is refused for every non-gateway uid on every inventory or reserved port.
  - Credentials are separated (the gateway gets keys only via LoadCredential; the runtime user cannot reach the gateway's copy).
  - Inventory-driven.
  - Ansible-enforced, fail closed at boot.
  - Candidates are covered.
  - The residual (ad-hoc servers on unreserved ports, root) is explicitly detected or out of model.
  Passes.
- **Engine-agnostic:** TCP-level, so vLLM and future engines are covered. Passes.
- **Operational risk:** ordering bugs could block workers at boot, which is the intended fail-closed behaviour. Verified with a
  reboot test in Q-FINAL.
