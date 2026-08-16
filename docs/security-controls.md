# Security controls for baseline hosts

This repository applies practical host controls for Ubuntu 24.04 AI nodes. It does not claim generic CIS compliance.

- The `users` role can place service accounts into `render` and `video` groups when GPU device access is explicitly configured. Those groups are not granted by default.
- The `ssh` role protects operator access by proving at least one managed public key exists before `PasswordAuthentication` can be disabled.
- The `security` role keeps firewall policy opt-in. SSH rules require explicit management CIDRs, and inference API firewall access requires both explicit CIDRs and explicit ports.
- Audit rules add useful visibility, but audit overhead should be measured before enabling extra high-volume syscall coverage on busy inference hosts.
- Future systemd hardening may need explicit exceptions for GPU device nodes, container workloads, and `mlock` use by latency-sensitive inference runtimes.
- Base OS package controls disable unattended package mutation, but they do not uninstall security tooling such as `unattended-upgrades`.
