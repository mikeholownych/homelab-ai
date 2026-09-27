# Phase 13 Rollback Execution and Restoration Report

**Document Identifier**: `phase13_rollback_execution.md`  
**Execution Timestamp**: 2026-09-27T22:30:35Z  
**Rollback Mandate**: Section 15 ("Mandatory Baseline Restoration")  
**Rollback Disposition**: `ROLLBACK_EXECUTED_RESTORATION_IN_PROGRESS`  

---

## 1. Rollback Trigger & Justification

Upon successful completion of the matched physical comparison (11/11 benign tasks accepted, 39.27 tps) and sustained multi-agent project execution (2 projects accepted, 6.85 projects/hour), the planned experimental window concluded. In accordance with the non-negotiable instruction:
> "At the end of the experiment, restore the original dual-30B configuration. This instruction does not authorize permanent heterogeneous deployment, production promotion or Phase 14."

Rollback execution commenced immediately.

---

## 2. Configuration & Asset Restoration

The exact baseline files preserved prior to candidate deployment were restored:

```bash
sudo systemctl stop aihost-vllm-worker2.service
sudo cp -p /etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup /etc/local-ai/vllm/worker2/vllm-config.yaml
sudo cp -p /etc/local-ai/vllm/worker2/vllm.env.baseline-backup /etc/local-ai/vllm/worker2/vllm.env
sudo cp -p /etc/local-ai/orchestrator/gateway.env.baseline-backup /etc/local-ai/orchestrator/gateway.env
```

### Cryptographic Checksum Verification
- Worker 2 Config (`/etc/local-ai/vllm/worker2/vllm-config.yaml`):
  `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b` (**VERIFIED MATCH**)
- Gateway Environment (`/etc/local-ai/orchestrator/gateway.env`):
  `16b7be5bbe4a189dc8730ae2726530820d78e7b13564631a693d332b454c0970` (**VERIFIED MATCH**)
- Worker 2 Expected Model (`VLLM_XPU_EXPECTED_MODEL`):
  Restored to `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`

---

## 3. Worker 2 Service Re-launch

- Service started: `sudo systemctl start aihost-vllm-worker2.service`
- Target container: `vllm-xpu-tp1-worker2` (Container ID `1ec99118abee`)
- Container image digest: `sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d`
- Accelerator assignment: GPU 1 (PCI `0000:93:00.0`, Level Zero device 1)
- Model: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (revision `4bd30395b72ea6045edd04806c4fea448d4467b3`)
- Shards loaded: 4 of 4 shards verified loaded into VRAM.
