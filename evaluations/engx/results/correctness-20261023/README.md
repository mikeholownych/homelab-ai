# October 23 gateway correctness follow-through

Read [the completed report](../../CORRECTNESS-2026-10-23.md) and [the SGLang prerequisite plan](../../SGLANG-CANDIDATE-2026-10-23.md).

The [sanitized evidence archive](../../evidence/correctness-20261023.tar.gz) retains tests, live cache checks, bounded probes, raw DRM observations, deployment/rollback procedure and immutable source/image identities. Historical development failures remain separate from final passing results. As-run `published:false` records predate GitHub publication.

Run future bounded probes through `playbooks/controller_qualification_probe.yml` on the authorized controller. It owns the reconciliation lock; the inner playbook refuses unprotected execution. Probe credentials arrive on stdin and are not retained in results. The archive's historical session procedures are audit data, not a turnkey replay interface.

Synthetic stateful results are not BFCL or full engineering qualification. Client concurrency two is not device batch size two. Prefix state is uncontrolled. Existing model/runtime no-go findings remain open; no SGLang image or GPU run occurred.
