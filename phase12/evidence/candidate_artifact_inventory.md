# Phase 12 Candidate Artifact Custody & Integrity Inventory

## 1. Scope & Custody Policy

In accordance with Workstream C and Gate G5, this inventory establishes immutable custody records for all model candidates evaluated during Phase 12.

Each model artifact is pinned to its exact repository origin, commit snapshot digest, tokenizer configuration, weight file digests, and runtime container specification. Mutable or floating tags (e.g. `latest`) are strictly disqualified from qualification.

---

## 2. Protected Control Model Custody Record

- **Model Identifier**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
- **Served Model Alias**: `engineering/b0`
- **Snapshot Revision Digest**: `4bd30395b72ea6045edd04806c4fea448d4467b3`
- **Architecture**: `Qwen2ForCausalLM` (MoE: 30B total, ~3.3B active)
- **Local Path**: `/var/lib/local-ai/models/hub/models--cyankiwi--Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit/snapshots/4bd30395b72ea6045edd04806c4fea448d4467b3`
- **Configuration Digest (`config.json`)**: `42981b44892a1940c8f93bf5fb40972bc62f2c9a6c8f0d10115175e68b11396d`
- **Quantization Metadata**: AWQ 4-bit (GEMM, group_size 128, zero_point true)
- **Runtime Container Image Digest**: `docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d`
- **Tool-Call Parser**: `qwen3_coder`
- **Active Serving Nodes**: `vllm-xpu-tp1-worker1` (GPU 0), `vllm-xpu-tp1-worker2` (GPU 1)

---

## 3. Candidate 1 (Tier 1 Physical Candidate) Custody Record

- **Model Identifier**: `Qwen/Qwen2.5-7B-Instruct-AWQ`
- **Candidate ID**: `CAND-QWEN2.5-7B-AWQ`
- **Snapshot Revision Digest**: `b25037543e9394b818fdfca67ab2a00ecc7dd641`
- **Architecture**: `Qwen2ForCausalLM` (Dense 7.61B parameters, 28 layers, 28 heads, 4 KV heads GQA)
- **Local Path**: `/var/lib/local-ai/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641`
- **Configuration Digest (`config.json`)**: `ec0c1f5f875ad8bc1f78c5140c22dbdde1b55478442ad358e7a4d9ecf947a327`
- **Tokenizer Digest (`tokenizer.json`)**: `c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539`
- **Weight Files**:
  - `model-00001-of-00002.safetensors` (Size: 3,822,467,232 bytes, Blob: `4ad6e70f9382...`)
  - `model-00002-of-00002.safetensors` (Size: 1,514,561,408 bytes, Blob: `920a8cc9d3c8...`)
- **Quantization Metadata**: AWQ 4-bit (GEMM, group_size 128, zero_point true)
- **Context Length**: 32,768 tokens native
- **Target Runtime Container**: `docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d`
- **Tool-Call Parser**: `hermes` / `json`
- **Structured-Output Engine**: Outlines / JSON Schema constrained decoding

---

## 4. Candidate 2 (Experimental Long-Context Candidate) Custody Record

- **Model Identifier**: `cyankiwi/Qwen3.8-27B-AWQ-INT4`
- **Candidate ID**: `CAND-QWEN3.8-27B-INT4`
- **Snapshot Revision Digest**: `6e134bae811fb5adac50ee042ae5f029ac6779aa`
- **Architecture**: `qwen3_5` multimodal with linear attention / Mamba SSM layers
- **Local Path**: `/var/lib/local-ai/models/hub/models--cyankiwi--Qwen3.8-27B-AWQ-INT4/snapshots/6e134bae811fb5adac50ee042ae5f029ac6779aa`
- **Quantization Method**: `compressed-tensors` (INT4)
- **Total Weight Size**: 14.8 GB (5 safetensors files)
- **Context Window**: 262,144 tokens (256K)
- **Intel XPU Compatibility**: **Blocked**. Linear attention kernels require custom Triton/Level-Zero kernels not compiled in base vLLM XPU container.

---

## 5. Candidate 3 (Oversized Candidate) Custody Record

- **Model Identifier**: `casperhansen/llama-3.3-70b-instruct-awq`
- **Candidate ID**: `CAND-LLAMA3.3-70B-AWQ`
- **Snapshot Revision Digest**: `64d255621f40b42adaf6d1f32a47e1d4534c0f14`
- **Architecture**: `LlamaForCausalLM` (Dense 70.6B)
- **Local Path**: `/var/lib/local-ai/models/hub/models--casperhansen--llama-3.3-70b-instruct-awq/snapshots/64d255621f40b42adaf6d1f32a47e1d4534c0f14`
- **Quantization Method**: AWQ 4-bit
- **Total Weight Size**: 38.6 GB (9 safetensors files)
- **Context Window**: 131,072 tokens
- **Physical Allocation**: 38.6 GB weights + overhead exceeds single B65 GPU (32,656 MiB). Requires Tensor Parallelism $TP=2$ across both physical cards.

---

## 6. Verification Status

- **Immutable Pinning**: All candidates bound to cryptographic commit snapshots (**VERIFIED**).
- **Blob Digest Integrity**: Verified safetensors symlinks resolve to valid data blocks on host disk (**VERIFIED**).
- **Floating Tag Rejection**: All unversioned tags rejected (**VERIFIED**).
