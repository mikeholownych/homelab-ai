# Kernel Patch Series

Numbered patch series (`0001-*.patch`, `0002-*.patch`) for custom kernel experiments.
All patches in this directory must:
1. Address an explicit blocker that cannot be resolved via supported Ubuntu packages (see `docs/custom-kernel.md`).
2. Be referenced in the corresponding metadata manifest under `kernel/metadata/`.
3. Have their SHA256 checksum recorded in `kernel/checksums/SHA256SUMS`.
