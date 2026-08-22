# Custom Kernel Policy and Workflow

**Status: scaffolding only. No custom kernel is built, deployed, or planned
until a concrete blocker appears.** Supported Ubuntu 24.04 kernels (GA and
approved HWE/OEM tracks) are the default.

## Justification triggers

A custom kernel is justified only by:

- required Xe-driver functionality or a fix unavailable in any supported
  Ubuntu kernel,
- a demonstrated kernel scheduler/NUMA defect affecting this workload,
- a required memory-management patch,
- a meaningful low-latency requirement not satisfiable through supported
  configuration,
- a measured gain large enough to justify maintaining the kernel,
- a critical bug fix unavailable through vendor-supported package streams.

A small synthetic benchmark improvement alone never qualifies. Triggers are
also encoded in `policies/tuning.yml`.

## Before a custom kernel: supported-kernel experiments

The framework supports comparing kernels without any private build:

1. Pick an explicitly installed, supported candidate kernel (pinned release).
2. Set `os_tuning.kernel.expected_release` in a candidate profile; commit.
3. Install the pinned kernel via the normal patching/upgrade workflow; retain
   the previous kernel package (never removed automatically).
4. Reboot; boot validation plus hardware/XPU/inference validation must pass.
5. Benchmark against the GA baseline with full provenance.
6. Promote or revert per docs/tuning.md sections 8-10. Unexpected running
   kernels fail validation (`running_kernel`, blocking) — they never roll back
   automatically.

## Reproducible build workflow (future)

Layout under `kernel/`:

```
config/      versioned .config fragments        (committed)
patches/     numbered patch series              (committed)
build/       produced .deb artifacts            (NOT committed)
metadata/    upstream version, source URL, patch manifest (committed)
checksums/   SHA256SUMS binding everything      (committed)
```

Pipeline: pinned upstream source + checksum -> versioned config -> versioned
patch set -> containerized build environment with pinned toolchain ->
versioned `.deb` artifact -> SHA256 recorded -> deployment only through the
`os_tuning` `custom_kernel` block (requires
`os_tuning_custom_kernel_certified=true` and matching artifact/sha256 pins) ->
reboot -> full hardware/XPU/inference validation -> benchmark comparison ->
promotion per policies/tuning.yml.

Rules:

- kernels are never built interactively on the P620;
- artifacts are reproducible from committed inputs alone;
- the previous kernel always remains bootable for rollback;
- acceptance requires reboot persistence plus complete validation evidence.
