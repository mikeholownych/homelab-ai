#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="10.0.8.5"

echo "=== SWITCHING WORKER 2 TO QWEN2.5-7B-INSTRUCT-AWQ ==="
ssh "$TARGET_HOST" '
sudo systemctl stop aihost-vllm-worker2.service

cat << "EOF" | sudo tee /etc/local-ai/vllm/worker2/vllm-config.yaml
model: /models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641
revision: b25037543e9394b818fdfca67ab2a00ecc7dd641
host: 0.0.0.0
port: 8001
tensor-parallel-size: 1
gpu-memory-utilization: 0.9
max-model-len: 32768
enforce-eager: false
disable-log-stats: false
api-key: gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY
enable-auto-tool-choice: true
tool-call-parser: hermes
max-num-seqs: 4
max-num-batched-tokens: 4096
served-model-name: Qwen/Qwen2.5-7B-Instruct-AWQ
EOF

sudo sed -i "s|VLLM_XPU_EXPECTED_MODEL=.*|VLLM_XPU_EXPECTED_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ|" /etc/local-ai/vllm/worker2/vllm.env
sudo chown aihost-runtime:aihost-runtime /etc/local-ai/vllm/worker2/vllm-config.yaml /etc/local-ai/vllm/worker2/vllm.env
sudo chmod 600 /etc/local-ai/vllm/worker2/vllm-config.yaml /etc/local-ai/vllm/worker2/vllm.env

sudo systemctl start aihost-vllm-worker2.service
'

echo "Waiting for Worker 2 readiness..."
for i in {1..30}; do
    if curl -s -H "Authorization: Bearer gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY" http://10.0.8.5:8001/v1/models | grep -q "Qwen2.5-7B-Instruct-AWQ"; then
        echo "Worker 2 READY: Qwen/Qwen2.5-7B-Instruct-AWQ serving on port 8001!"
        exit 0
    fi
    sleep 2
done

echo "ERROR: Worker 2 failed to become ready in 60s"
exit 1
