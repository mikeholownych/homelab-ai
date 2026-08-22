# Custom Kernel Workspace (Scaffolding Only)

This directory is reserved for a future reproducible custom-kernel workflow.
**No custom kernel is built, shipped, or deployed today.** Supported Ubuntu
24.04 kernels remain the default and preferred path.

## Why this exists

A custom kernel is justified only by a concrete blocker that no supported
packaged kernel can satisfy. See `docs/custom-kernel.md` for the explicit
trigger list. Speculative performance is not a trigger.

## Intended layout

```
kernel/
├── README.md        this file
├── config/          versioned kernel .config fragments (committed)
├── patches/         versioned patch series (committed, numbered)
├── build/           package artifacts (.deb) - NOT committed; checksums are
├── metadata/        upstream version, source URL, patch manifest (committed)
└── checksums/       SHA256SUMS binding source + config + patches to artifact (committed)
```

## Future workflow (do not run today)

```text
upstream source version (pinned)
+ source tarball checksum
+ versioned kernel config
+ versioned patch set
+ reproducible build environment (container, pinned toolchain)
→ versioned package artifact in kernel/build/
→ SHA256 recorded in kernel/checksums/
→ Ansible deployment via os_tuning custom_kernel block
   (requires os_tuning_custom_kernel_certified=true)
→ reboot → full hardware/XPU/inference validation
→ benchmark comparison against supported-kernel baseline
```

Rules that already apply through the tuning framework:

- kernels are never built interactively on the P620
- `custom_kernel.enabled` fails closed without the certification flag
- the previous kernel package is always retained for rollback
- acceptance requires reboot persistence plus full validation evidence
