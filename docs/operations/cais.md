# CAIS operations: qualification, revocation, enablement, recovery

Design: [docs/design/07](../design/07-capability-aware-scheduling.md).

All commands run on the **controller** from the repository root with the project venv. Live evaluation goes through
the gateway from the controller (gateway-only worker access). Never start inference on the aihost, and never call a
worker port directly.

The authoritative directory is `inventory/production/cais/`:
- `capabilities.json`: versioned catalog and criteria;
- `ledger.jsonl`: append-only, hash-chained;
- `bundles/`: evidence.

Every change to it goes through a reviewed PR. The second approver is the qualification authority.

## Production-affecting steps that need explicit approval

| Step | Why |
|---|---|
| Running a live evaluation (step 2) | Occupies a single-slot production worker for the run, roughly 30–90 minutes per corpus and repeat |
| Bumping `orchestrator_gateway_release_id` and re-pinning reconcile | Deploys new gateway code (restart) |
| Setting `orchestrator_gateway_cais_mode: enforce` | Changes how capability requests are answered |
| Delivering a ledger change | SIGHUP reload changes eligibility |
| Admin suspend/revoke on the live gateway | Removes eligibility immediately |

## 1. Onboard a profile (new model, new runtime, new node)

1. Add the worker to inventory with exact `model_id`, `artifact_digest` (sha256 of the GGUF, or a manifest over its
   shards), `runtime_image_digest`, `engine`, `topology` and `hardware_class` (e.g. `intel-arc-pro-b65-32g`,
   `amd-strix-halo-128g`), plus `reasoning_budget`.
2. Verify the digest on the host before committing it:

   ```sh
   sha256sum /var/lib/local-ai/models/gguf/<file>
   ```

   The gateway cannot check the file.
3. Start it as `role: candidate` behind a `candidate/<name>` alias with `scope: qualification` (existing candidate
   workflow, `playbooks/candidate.yml`). A candidate role is never eligible for capability routing.

## 2. Produce evidence

```sh
# profile.json = the inventory worker record's identity fields + the alias reasoning policy, e.g.
# {"model_id":..., "artifact_digest":..., "runtime_image_digest":..., "engine":"llama.cpp",
#  "topology":"llama-cpp-sycl", "hardware_class":"intel-arc-pro-b65-32g", "reasoning_budget":8192,
#  "reasoning":{"mode":"off","answer_allowance":8192}}
SSL_CERT_FILE=<gateway CA> ENGX_PYTHON=.venv/bin/python \
  .venv/bin/python evaluations/cais/run_qualification.py run \
    --base https://10.0.8.5:8443 --token-file - --model engineering/lead \
    --profile profile.json --capability coding.routine --corpus base --reps 2 \
    --out evaluations/cais/results  < <(sudo cat /etc/local-ai/orchestrator/clients/qualification.token)
```

- The run refuses to start if `/v1/models` for the alias does not serve exactly the profile's artifact.
- The run refuses to emit a bundle if the serving identity changed during it.
- The alias must reach exactly one worker.
- `--max-tokens` (default 8192) and `--max-attempts` (default 3) are part of the suite version, and must equal the
  catalog's `suite_version` to qualify.

Re-grade it independently (no model needed). Mismatches exit 1:

```sh
.venv/bin/python evaluations/cais/run_qualification.py rescore evaluations/cais/results/<run>.json
```

## 3. Grant

```sh
.venv/bin/python -m orchestrator_runtime.cais_cli assess inventory/production/cais --bundle <run>.json
.venv/bin/python -m orchestrator_runtime.cais_cli grant  inventory/production/cais --bundle <run>.json --authority <you>
.venv/bin/python -m orchestrator_runtime.cais_cli verify inventory/production/cais --workers <worker-specs.json>
```

- `grant` copies the bundle into `bundles/`, appends a `qualification_granted` record and refuses a bundle that fails
  the current criteria. There is no override: an exception means a reviewed change to the catalog.
- Open a PR containing the bundle, the ledger line and the `rescore` output. The reviewer checks profile identity
  against inventory, re-runs `rescore` and approves.
- After merge, the gateway role verifies the directory with the gateway's own loader, delivers it read-only to
  `/var/lib/aihost/cais` and sends SIGHUP.

## 4. Enable enforcement (approval required)

1. Deploy the CAIS-capable release with mode `off`. Confirm `GET /v1/cais` reports `"mode": "off"` and legacy traffic
   is unchanged (validator `single_gpu_inference`, vllm-top).
2. Set `orchestrator_gateway_cais_mode: enforce` in host_vars and reconcile (env change, journaled restart).
3. If the authoritative ledger already has records, the gateway starts with `anti_rollback_baseline_missing` (it never
   trusts ledgers it has not accepted before). Compare `GET /v1/cais` → `ledger_heads` with the reviewed Git head,
   then accept them explicitly:

   ```sh
   curl --cacert <CA> -H "Authorization: Bearer $ADMIN" -X POST https://10.0.8.5:8443/v1/admin/cais/rebaseline
   ```

   This is evidenced as `cais_rebaselined` with your client id.
4. Check that `GET /v1/cais` shows `"valid": true` and the expected states, and that
   `aihost_cais_state_valid == 1`.
5. Send one request with `X-AIHost-Capability` from the controller and inspect the `X-AIHost-Qualification-Id` header
   and the `cais_routing_decision` evidence record.

## 5. Suspend or revoke

**Immediate (live gateway, removal only):**

```sh
curl --cacert <CA> -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d '{"reason_code":"confirmed_regression","detail":"<ticket>"}' \
  https://10.0.8.5:8443/v1/admin/cais/qualifications/<qid>/suspend     # or /revoke
```

- This is fsync'd to `/var/lib/aihost-gateway/cais-suspensions.jsonl`.
- It cancels in-flight requests on that qualification (409; clients discard partial output).
- It survives restarts.
- Repeating it (already suspended, or revoked) returns 409 and records nothing.
- `detail` is stored verbatim in the ledger and evidence: a ticket reference only, never prompt content.

**Authoritative (reviewed):**

```sh
cais_cli revoke <dir> <qid> --reason <code> --authority <you>
```

Use `suspend` instead of `revoke` when the fault is expected to be cleared.

| Trigger | Action |
|---|---|
| Unexpected artifact or runtime change | Nothing needed: the profile digest no longer matches, so the old qualification no longer applies to the worker. Also investigate. |
| Repeated deterministic failures (gate tests, protocol) | Suspend, then requalify |
| Confirmed regression | Revoke |
| Statistical drift in client outcomes | Investigate first. Client outcomes are attributed evidence, not proof (design §15); never auto-revoke on them. |

## 6. Requalify / reinstate

- **After a suspension:** produce new evidence (steps 2–3) for a new grant, or append an authoritative reinstatement
  naming every active suspension:

  ```sh
  cais_cli reinstate <dir> <qid> --lifts <evidence_id>[,...] --reason <code> --authority <you>
  ```

  The suspension evidence ids are in `GET /v1/cais` → `active_suspensions`.
- **A revocation is terminal.** Only a new grant on new evidence restores eligibility.
- **Expiry:** grants last at most `max_validity_days` (60). Requalify before `expires_at`. `GET /v1/cais` lists it.

## 7. Recovery

| Symptom | Cause | Recovery |
|---|---|---|
| `qualification_state_unavailable`, `aihost_cais_state_valid 0` | Ledger, catalog or bundle unreadable or corrupt; gateway ledger contains a forbidden event; anti-rollback violation | `GET /v1/cais` → `problems`. Restore the authoritative directory from Git (`git checkout` the reviewed head) and reconcile; legacy routing is unaffected meanwhile |
| `authoritative_ledger_rollback` / `gateway_ledger_rollback` | A ledger is shorter than, or diverges from, the one this gateway last accepted (Git revert, old backup, truncated or deleted suspension file) | Never "fix" by editing a ledger. Restore the missing records (Git head; the suspension file from backup). Only if the rollback is intended, re-apply any lost suspensions authoritatively first, then `POST /v1/admin/cais/rebaseline` (evidenced, attributable) |
| `anti_rollback_baseline_missing` | `cais-ledger-heads.json` absent while ledgers have records (first enablement, or the file was lost) | Verify `ledger_heads` against Git and the suspension backup, then `POST /v1/admin/cais/rebaseline` |
| `anti_rollback_state_unwritable` | The state directory is full or read-only | Fix the filesystem and reload; CAIS stays closed meanwhile |
| Gateway ledger corrupt | Disk or crash during append | Re-apply its suspensions authoritatively, move `cais-suspensions.jsonl` aside, rebaseline. Dropping it silently is refused by the anti-rollback check |
| Restore from backup | `/var/lib/aihost-gateway` restored | Suspensions and the baseline come back together. If the restored ledgers are older than the delivered ones, CAIS stays closed until rebaselined. Verify `GET /v1/cais` before enabling traffic |

## 8. Rollback

- **Disable enforcement:** set `orchestrator_gateway_cais_mode: off` and reconcile. Capability requests then get
  `cais_disabled` (503); legacy requests were never affected.
- **Roll back the code:** revert `orchestrator_gateway_release_id` to the previous release through the normal
  journaled activation (docs/GATEWAY-BOUNDED-ADMISSION-RECOVERY.md). The previous release ignores the CAIS headers and
  serves capability requests by legacy routing. Clients relying on qualification must therefore treat a missing
  `X-AIHost-Qualification-Id` response header as unqualified.
- CAIS state files are ignored by older releases and are safe to leave in place.
- Delivery copies but does not purge: a bundle removed from Git stays on the host, inert (only ledger-referenced,
  digest-matching bundles count).

## 9. Adding a worker or node (heterogeneous expansion)

1. Add the node to inventory with its own `hardware_class`, runtime image digest and engine.
2. Bring workers up as candidates. Every profile starts unqualified.
3. Evaluate each capability on the node through the gateway (step 2). Large models that need on-demand loading are
   not supported by the gateway today: a worker must be resident to be evaluated or routed.
4. Grant per profile. No equivalence is assumed across hardware classes.

## 10. Troubleshooting

- `details.cais.rejected` in every denial names each worker's reason:
  - `no_qualification`
  - `qualification_expired`, `qualification_suspended`, `qualification_revoked`, `qualification_invalid`,
    `qualification_superseded`, `qualification_pending`
  - `context_unsupported`
  - `candidate_role`, `not_requested`, `fallback_prohibited`
- `GET /v1/cais` → `qualifications.<qid>.reasons` explains `invalid` (e.g. `bundle_digest_mismatch`,
  `assessment:pass_rate_below_threshold`, `grant_scope_exceeds_evidence`).
- Evidence: filter `evidence-chain.jsonl` for `event == "cais_routing_decision"` by request id.
