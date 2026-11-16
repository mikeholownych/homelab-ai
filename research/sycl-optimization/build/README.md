# head-stackB image provenance
`Dockerfile.stackB` is upstream `.devops/intel.Dockerfile` at llama.cpp a956a852 with the Intel runtime packages (IGC 2.34.4, NEO 26.18, IGDGMM 22.10.0)
pinned to the pre-#31540 versions and `GGML_SYCL_ENABLE_XMX_ESIMD=0` handled per worker via `llama_worker.env` (not baked in).
Built on the workstation (reniced), transferred to the host and loaded into `aihost-runtime`'s Podman store as `localhost/sycl-research/llama:head-stackB`;
manifest digest `sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9` (image id `3b9d3e97c8f6`). Not published to a registry.
Package SHA-256 pins for the old IGC/NEO assets are still TODO (supply-chain note in integration-recommendations.md).
