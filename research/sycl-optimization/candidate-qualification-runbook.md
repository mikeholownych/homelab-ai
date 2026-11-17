# Qualifying the head-stackB candidate through the gateway (durable transaction)

Source: `evaluations/engx/RECOVERY-OPERATIONS.md`. All appliance changes run through Ansible via the durable transaction; direct
`candidate.yml` runs bypass the journal and are not used.

Preconditions: gateway idle (no operator workload; confirm worker logs show no `print_timing|launch_slot|slot update` for 6 min);
`/home/mike/.local/share/aihost/reconcile/candidate/active.json` absent or terminal; a clean committed checkout of `main` at a path that stays
in place until the transaction is terminal (the journal records it).

```
SRC=/home/mike/work/aihost-candidate-src   # git worktree of origin/main, kept until restored_verified
R=/home/mike/.local/share/aihost/reconcile
ansible-playbook -i $SRC/inventory/production/hosts.yml $SRC/playbooks/controller_candidate_transaction.yml \
  -e candidate_transaction_action=run -e candidate_transaction_inventory=inventory/production/hosts.yml \
  -e candidate_transaction_state=$R/candidate -e candidate_transaction_lock=$R/lock/ansible-snapshot.lock \
  -e candidate_transaction_profile=qwen36-stackb \
  -e candidate_transaction_baseline_playbook=playbooks/verify_candidate_restoration.yml \
  -e candidate_transaction_verify_playbook=playbooks/verify_candidate_restoration.yml \
  -e candidate_transaction_experiment_playbook=playbooks/candidate_probe.yml \
  -e candidate_transaction_source=$SRC -e candidate_transaction_ansible=$(command -v ansible-playbook)
```
Sequence: baseline capture -> `candidate.yml` swaps worker1 for `qwen36-stackb` (candidate/qwen36-stackb, qualification scope) -> `candidate_probe.yml`
(`controlled_probe.py` latency + synthetic multi-turn through authenticated TLS; evidence under `/home/mike/work/candidate-qwen36-stackb`) ->
restoration -> independent verification (`restored_verified`). Rollback at any point: `candidate_transaction_action=recover`, or
`candidate.yml -e candidate=qwen36-stackb -e candidate_state=absent`.
Production worker1 is out of service for the duration (minutes); worker2 is untouched.
