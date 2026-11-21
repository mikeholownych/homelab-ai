#!/usr/bin/env bash
# Download pinned shortlist artifacts (probe + mid-size) to the lab host model dir.
# Usage: download_probe_models.sh probe|mid|all
# Revisions / sha256 are the pins in ../model-shortlist.md. GGUF files are verified
# against the pinned sha256; HF safetensors repos are verified against the per-file
# LFS sha256 reported by the HF tree API at the pinned revision.
# Runs on the lab host (needs curl + python3). Resumable (curl -C -).
set -euo pipefail

MODELS_ROOT="${MODELS_ROOT:-/var/lib/local-ai/models}"
WHAT="${1:-probe}"

fetch_verify() { # url dest sha256
  local url="$1" dest="$2" want="$3"
  mkdir -p "$(dirname "$dest")"
  if [[ -f "$dest" ]] && [[ "$(sha256sum "$dest" | cut -d' ' -f1)" == "$want" ]]; then
    echo "OK (cached) $dest $want"; return 0
  fi
  curl -fL -sS --retry 5 --retry-delay 5 -C - -o "$dest" "$url"
  local got; got="$(sha256sum "$dest" | cut -d' ' -f1)"
  if [[ "$got" != "$want" ]]; then echo "SHA256 MISMATCH $dest want=$want got=$got" >&2; return 1; fi
  echo "OK $dest $got"
}

gguf() { # repo rev file sha slug
  local repo="$1" rev="$2" file="$3" sha="$4" slug="$5"
  fetch_verify "https://huggingface.co/${repo}/resolve/${rev}/${file}" "${MODELS_ROOT}/${slug}/${file}" "$sha"
}

hf_repo() { # repo rev slug : all files, verify LFS sha256 where present
  local repo="$1" rev="$2" slug="$3"
  local listing; listing="$(mktemp)"
  curl -fsS "https://huggingface.co/api/models/${repo}/tree/${rev}?recursive=1" >"$listing"
  python3 - "$listing" <<'PY' | while read -r path sha; do
import json, sys
for e in json.load(open(sys.argv[1])):
    if e.get("type") != "file":
        continue
    print(e["path"], (e.get("lfs") or {}).get("oid", "-"))
PY
    local dest="${MODELS_ROOT}/${slug}/${path}"
    mkdir -p "$(dirname "$dest")"
    if [[ "$sha" == "-" ]]; then
      curl -fL -sS --retry 5 -o "$dest" "https://huggingface.co/${repo}/resolve/${rev}/${path}"
      echo "OK (no lfs sha) $dest"
    else
      fetch_verify "https://huggingface.co/${repo}/resolve/${rev}/${path}" "$dest" "$sha"
    fi
  done
  rm -f "$listing"
  echo "$rev" >"${MODELS_ROOT}/${slug}/.revision"
}

if [[ "$WHAT" == probe || "$WHAT" == all ]]; then
  gguf unsloth/Qwen3-4B-Instruct-2507-GGUF a06e946bb6b655725eafa393f4a9745d460374c9 \
    Qwen3-4B-Instruct-2507-Q8_0.gguf 391c1e410fd9f4cf2de2b510273b56a84c19ce18f4fa3bfb3774031dac4ef068 \
    Qwen3-4B-Instruct-2507-GGUF
  hf_repo Qwen/Qwen3-4B-Instruct-2507 cdbee75f17c01a7cc42f958dc650907174af0554 Qwen3-4B-Instruct-2507
fi
if [[ "$WHAT" == mid || "$WHAT" == all ]]; then
  gguf unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF b17cb02dd882d5b6ab62fc777ad2995f19668350 \
    Qwen3-Coder-30B-A3B-Instruct-Q8_0.gguf 4ff1cff607804037bf6d2168249c570baa4e1621292b159c0e06591e0d7c3066 \
    Qwen3-Coder-30B-A3B-Instruct-GGUF
  hf_repo Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 dcaee4d4dfc5ee71ad501f01f530e5652438fde0 Qwen3-Coder-30B-A3B-Instruct-FP8
fi
