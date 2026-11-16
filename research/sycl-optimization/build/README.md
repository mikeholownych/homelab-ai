# head-stackB image provenance
`Dockerfile.stackB` is upstream `.devops/intel.Dockerfile` at llama.cpp a956a852 with the Intel runtime packages (IGC 2.34.4, NEO 26.18, IGDGMM 22.10.0)
pinned to the pre-#31540 versions and `GGML_SYCL_ENABLE_XMX_ESIMD=0` handled per worker via `llama_worker.env` (not baked in).
Built on the workstation (reniced), transferred to the host and loaded into `aihost-runtime`'s Podman store as `localhost/sycl-research/llama:head-stackB`;
manifest digest `sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9` (image id `3b9d3e97c8f6`). Not published to a registry.
The six installed IGC/NEO/IGDGMM .deb assets are pinned by SHA-256 in the Dockerfile (`sha256sum -c` before `dpkg --install`). The hashes were computed on 2026-11-16 from the
upstream release assets of the same names and versions; they were not proven byte-identical to the copies baked into the already-built image (the build predates the pins).
The -dbgsym .ddeb files are downloaded but not installed (the install glob is `*.deb`).
