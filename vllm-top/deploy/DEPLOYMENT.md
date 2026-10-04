# TTY1 deployment

`vllm-top` remains a normal terminal application — nothing in its code
knows or cares that it might be running on a physical console instead of
an SSH session. "Owning TTY1" is entirely a systemd deployment concern,
implemented by `vllm-top-console.service` (source of truth: the Ansible role
`roles/vllm_top_console` in this repo, template
`templates/vllm-top-console.service.j2`; installed copy:
`/etc/systemd/system/vllm-top-console.service`).

## Architecture

- `getty@tty1.service` is **masked** (`systemctl mask getty@tty1.service`),
  not merely disabled — this prevents anything, including udev/generator
  activity, from ever starting a login prompt on tty1 again while this
  deployment stands.
- `vllm-top-console.service` declares `Conflicts=getty@tty1.service`, so
  starting either one stops the other; the two can never both hold the
  device.
- It runs `vllm-top` directly (`ExecStart=/home/mike/.cargo/bin/vllm-top`,
  the real cargo-install path, not the `~/.local/bin` PATH-resolution
  wrapper or a login shell) as `User=mike`/`Group=mike` — no elevated
  privileges, no `root`.
- `TTYPath=/dev/tty1` + `TTYReset=yes`/`TTYVHangup=yes`/
  `TTYVTDisallocate=yes` is the same mechanism a normal getty uses to take
  clean ownership of a tty and release it cleanly on stop — this is what
  lets a rollback (re-enabling getty) start clean afterwards.
- `Restart=on-failure` with `RestartSec=2s` and a bounded
  `StartLimitIntervalSec=300s`/`StartLimitBurst=5` in `[Unit]`: recovers
  from a crash, but gives up (goes to the terminal "failed" state, tty1
  left with nothing running on it — never a runaway restart loop) if it
  keeps crashing.
- `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=read-only`,
  `PrivateTmp=yes`: `vllm-top` never writes to the filesystem at all (no
  database, no log files — everything it needs is reads: TOML config,
  `/proc`, outbound HTTP, and executing `xpu-smi`), so full read-only
  system hardening costs nothing functionally. Confirmed live: discovery
  (`/proc` reads), metrics collection and GPU telemetry (`xpu-smi` exec)
  all work correctly under this hardening.
- `vllm-top` is **not** required by, or coupled to, `vllm.service` — only
  soft-ordered after it (`After=`). If the vLLM API is down, `vllm-top`
  keeps running and shows that fact; it doesn't stop.

## Administrative access

SSH is untouched by any of this — it doesn't run on a tty at all
(`ssh.socket`/`ssh.service`, independent of the getty/tty subsystem), and
was verified still active throughout deployment and after every restart
performed during validation. No PAM, sudo, or other login-service
configuration was touched.

## Installing / re-deploying

Deployed by Ansible only (builds nothing on the host; installs the binary from
`vllm-top/target/release/vllm-top` root-owned, writes the unit, masks getty):

```sh
cd vllm-top && cargo build --release && cd ..
.venv/bin/ansible-playbook playbooks/inference.yml --limit ai-5820-01 --tags console
```

The unit waits for the orchestrator gateway before starting, because vllm-top
discovers its endpoints once at startup.

## Upgrading `vllm-top` itself

Re-run the playbook command above after `cargo build --release`; the handler
restarts the service (this also resets monitor-lifetime statistics, by design).

## Rollback

All of this is reversible from any administrative session (SSH), without
touching TTY1 directly:

```sh
# Stop the console and give tty1 back to a normal login prompt:
sudo systemctl stop vllm-top-console.service
sudo systemctl disable vllm-top-console.service
sudo systemctl unmask getty@tty1.service
sudo systemctl enable --now getty@tty1.service

# To also roll back the vllm-top binary itself, see ../rollback/README.md
```

## Troubleshooting

- **Service won't start / crashes immediately:**
  `journalctl -u vllm-top-console.service -n 50` — `vllm-top`'s own lines
  are interleaved with its `xpu-smi` child processes' output (tagged
  `xpu-smi[<pid>]`); filter those out to isolate application errors.
- **`xpu-smi` logs `Cannot establish a handle to the Intel MEI driver
  ... Permission denied` / HECI init errors:** expected and harmless —
  `/dev/mei*` is `root`-only on this host for *any* user, with or without
  this service's sandboxing (verified by reproducing it with a plain
  interactive, unsandboxed `xpu-smi` call). It only affects firmware
  version queries `vllm-top` never asks for; the power/memory JSON fields
  it actually reads are unaffected.
- **GPU utilization/temperature always show "n/a":** confirmed, not a
  bug — `xpu-smi`'s own JSON output omits those fields entirely on this
  hardware/driver combination (verified directly, not assumed). Power and
  memory usage/utilization are available and displayed.
- **tty1 shows nothing / stuck on an old frame:** check
  `systemctl status vllm-top-console.service`; if it's not `active
  (running)`, the terminal was never reclaimed. `TTYVTDisallocate=yes`
  should prevent stale frames from a previous run persisting after a
  restart.
- **Need the login prompt back immediately:** see Rollback above — none
  of it requires access to tty1 itself.
