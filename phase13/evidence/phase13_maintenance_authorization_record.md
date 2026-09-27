# Machine-Verifiable Maintenance Authorization Record

```json
{
  "authorization_record_version": "1.0.0",
  "proposal_id": "MAINT-PROP-PHASE13-HETERO-GPU1",
  "authorized_at": "2026-09-27T22:01:53Z",
  "authorizing_instruction": "PHASE 13 CONTINUATION: AUTHORIZED HETEROGENEOUS PHYSICAL CAMPAIGN",
  "authorization_scope": {
    "host": "Dell Precision T5820 (10.0.8.5)",
    "target_worker": "vllm-xpu-tp1-worker2",
    "target_systemd_unit": "aihost-vllm-worker2.service",
    "target_port": 8001,
    "target_gpu_index": 1,
    "target_gpu_pci": "0000:93:00.0",
    "target_gpu_uuid": "00000000-0000-0093-0000-0000e2228086",
    "target_drm_device": "/dev/dri/card2",
    "target_render_device": "/dev/dri/renderD129"
  },
  "protected_control_scope": {
    "control_worker": "vllm-xpu-tp1-worker1",
    "control_systemd_unit": "aihost-vllm-worker1.service",
    "control_port": 8000,
    "control_gpu_index": 0,
    "control_gpu_pci": "0000:51:00.0",
    "target_drm_device": "/dev/dri/card1",
    "target_render_device": "/dev/dri/renderD128",
    "public_production_route": "engineering/b0",
    "gateway_endpoint": "http://127.0.0.1:8010",
    "control_status": "ONLINE_PROTECTED_IMMUTABLE"
  },
  "original_configuration_digests": {
    "worker2_vllm_config_sha256": "641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b",
    "worker1_vllm_config_sha256": "57f27525c75e8daf33960d13bf8d29afb3762fef1d9c2b034982a620c304f41d",
    "gateway_env_baseline_sha256": "16b7be5bbe4a189dc8730ae2726530820d78e7b13564631a693d332b454c0970",
    "runtime_image_digest": "sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d"
  },
  "candidate_specification": {
    "model_id": "Qwen/Qwen2.5-7B-Instruct-AWQ",
    "snapshot_revision": "b25037543e9394b818fdfca67ab2a00ecc7dd641",
    "config_json_sha256": "ec0c1f5f875ad8bc1f78c5140c22dbdde1b55478442ad358e7a4d9ecf947a327",
    "quantization": "awq",
    "weight_format": "safetensors",
    "max_model_len": 32768,
    "isolated_route_port": 8001
  },
  "production_routing_configuration": {
    "gateway_env_path": "/etc/local-ai/orchestrator/gateway.env",
    "pinned_workers": ["b0-live-tp1-worker1"],
    "excluded_workers": ["b0-live-tp1-worker2"],
    "active_ports": [8000],
    "worker_pinning_verified": true
  },
  "rollback_configuration": {
    "backup_gateway_env": "/etc/local-ai/orchestrator/gateway.env.baseline-backup",
    "backup_worker2_config": "/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup",
    "backup_worker2_env": "/etc/local-ai/vllm/worker2/vllm.env.baseline-backup",
    "restoration_command": "sudo cp -p /etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup /etc/local-ai/vllm/worker2/vllm-config.yaml && sudo cp -p /etc/local-ai/vllm/worker2/vllm.env.baseline-backup /etc/local-ai/vllm/worker2/vllm.env && sudo systemctl restart aihost-vllm-worker2.service && sudo cp -p /etc/local-ai/orchestrator/gateway.env.baseline-backup /etc/local-ai/orchestrator/gateway.env && sudo systemctl restart aihost-orchestrator-gateway.service"
  },
  "maintenance_constraints": {
    "max_duration_seconds": 900,
    "max_duration_minutes": 15,
    "worker1_sla": "100_PERCENT_AVAILABILITY",
    "candidate_public_exposure": "FORBIDDEN",
    "permanent_deployment": "NOT_AUTHORIZED",
    "protected_processes_uninterrupted": [986, 2093382, 3130937]
  },
  "required_validation_gates": [
    "G9: Physical Heterogeneous Campaign (Matched physical candidate evaluation, live routing & fallback)",
    "G10: Sustained Throughput Measurement (8-item dependency DAG sustained project execution)",
    "G12: Protected Service Non-Interference Audit",
    "G16: Rollback verification and baseline dual-30B restoration"
  ]
}
```

## Maintenance Authority Declaration

Authority for proposal `MAINT-PROP-PHASE13-HETERO-GPU1` is hereby recorded under conditional authorization granted for Phase 13 Continuation.

1. **Target**: Strictly Worker 2 (`vllm-xpu-tp1-worker2`) on GPU 1 (`0000:93:00.0`).
2. **Exclusion**: Worker 1 on GPU 0 and production route `engineering/b0` are strictly protected and immutable.
3. **Rollback Mandate**: Complete restoration of baseline dual-worker configuration is mandatory immediately upon conclusion of the physical evaluation campaign.
4. **Maintenance Limit**: Hard maximum limit of 15 minutes applies to the disruptive maintenance interval.
