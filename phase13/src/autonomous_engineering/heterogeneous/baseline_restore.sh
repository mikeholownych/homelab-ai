#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="10.0.8.5"

echo "=== RESTORING WORKER 2 TO BASELINE DUAL-30B CONFIGURATION ==="
ssh "$TARGET_HOST" '
sudo systemctl stop aihost-vllm-worker2.service

sudo cp -p /etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup /etc/local-ai/vllm/worker2/vllm-config.yaml
sudo cp -p /etc/local-ai/vllm/worker2/vllm.env.baseline-backup /etc/local-ai/vllm/worker2/vllm.env
sudo cp -p /etc/local-ai/orchestrator/gateway.env.baseline-backup /etc/local-ai/orchestrator/gateway.env

sudo chown aihost-runtime:aihost-runtime /etc/local-ai/vllm/worker2/vllm-config.yaml /etc/local-ai/vllm/worker2/vllm.env
sudo chmod 600 /etc/local-ai/vllm/worker2/vllm-config.yaml /etc/local-ai/vllm/worker2/vllm.env

sudo systemctl restart aihost-orchestrator-gateway.service
sudo systemctl start aihost-vllm-worker2.service
'

echo "Waiting for Worker 2 baseline readiness..."
for i in {1..40}; do
    if curl -s -H "Authorization: Bearer gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY" http://10.0.8.5:8001/v1/models | grep -q "Qwen3-Coder-30B"; then
        echo "Worker 2 READY: cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit restored on port 8001!"
        exit 0
    fi
    sleep 3
done

echo "ERROR: Worker 2 baseline restoration timed out"
exit 1
