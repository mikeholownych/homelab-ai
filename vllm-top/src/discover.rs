//! Best-effort discovery of local inference servers through their listening sockets.
//!
//! This never reads another process's config file or environment — those
//! are frequently permission-restricted on hardened deployments (a vLLM
//! service running as its own system user, e.g. under systemd or a
//! rootless container, with a `600` config/env file) and reading them
//! would require privileges `vllm-top` has no business asking for.
//! Instead it uses only what is legitimately visible to any local user:
//!
//!   - `systemctl` unit state (unit files and `ActiveState`/`MainPID` are
//!     world-readable).
//!   - `/proc/<pid>/cmdline`, which is world-readable on Linux (unlike
//!     `/proc/<pid>/environ`, which is never touched here).
//!   - `/proc/<pid>/fd`, to get the *exact* set of socket inodes a
//!     candidate process holds open, when that process shares our uid (or
//!     we're otherwise permitted to read it). Cross-referencing against
//!     `/proc/net/tcp{,6}` then gives [`Confidence::Verified`] attribution
//!     — this is the process's socket, not just "a" process with the same
//!     uid. When `/proc/<pid>/fd` isn't readable (the common case for a
//!     systemd-managed service running as its own system user, as on a
//!     hardened box), attribution falls back to matching on uid alone —
//!     reported as [`Confidence::UidAssociation`], explicitly weaker: a
//!     shared uid does not by itself prove that *this* process owns that
//!     socket, only that some process running as that user does.
//!   - `/proc/net/tcp` / `tcp6`, the global socket table, to find the
//!     actual listening port(s) instead of assuming 8000, without ever
//!     opening the process's own config.
//!   - A couple of bounded, single-shot HTTP GETs (`/health`, `/metrics`,
//!     `/v1/models`) to validate reachability, confirm the candidate is
//!     actually vLLM (a same-uid, unrelated service can otherwise pass a
//!     generic `/health` check — see `validate`), and classify whether
//!     auth is required. None of these trigger inference.
//!
//! Any credential used or reported here comes only from the caller (i.e.
//! from `vllm-top`'s own `--api-key` / config file / `VLLM_API_KEY`
//! environment variable) — never harvested from another process.

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthState {
    /// The endpoint answered without a credential.
    NotRequired,
    /// The endpoint requires a credential and none was configured.
    RequiredNoCredential,
    /// A configured credential was rejected.
    RequiredCredentialRejected,
    /// A configured credential was accepted.
    RequiredCredentialAccepted,
    /// The auth-requiring endpoint couldn't be checked (e.g. timed out).
    Unknown,
}

impl AuthState {
    pub fn label(&self) -> &'static str {
        match self {
            AuthState::NotRequired => "not required",
            AuthState::RequiredNoCredential => "required (no credential configured)",
            AuthState::RequiredCredentialRejected => "required (credential rejected)",
            AuthState::RequiredCredentialAccepted => "required (credential accepted)",
            AuthState::Unknown => "unknown",
        }
    }
}

/// How confident we are that a discovered endpoint really belongs to the
/// process we think it does. Never treat `UidAssociation` as proof of
/// ownership — it only means "some process running as this user has this
/// socket open," which is the best available evidence without privilege
/// escalation on a deployment where the server runs as its own user.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Confidence {
    /// The exact candidate process's own `/proc/<pid>/fd` was enumerated
    /// and this socket's inode was found among its open file descriptors.
    Verified,
    /// `/proc/<pid>/fd` couldn't be read (cross-user, the common case for
    /// a hardened systemd-managed service); attribution falls back to
    /// "some process owned by this uid is listening here."
    UidAssociation,
}

impl Confidence {
    pub fn label(&self) -> &'static str {
        match self {
            Confidence::Verified => "verified (exact socket match)",
            Confidence::UidAssociation => "uid association, not exact-process-verified",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DiscoveredInstance {
    pub url: String,
    pub auth: AuthState,
    pub confidence: Confidence,
    /// Human-readable provenance, e.g. "systemd vllm.service" or
    /// "process (vllm serve)" — also used as a stable identity across
    /// restarts (deliberately not PID-based: a restart may reuse a PID,
    /// and a real restart must not be mistaken for continuity).
    pub discovered_via: String,
    /// Engine identity established by a bounded, read-only endpoint fingerprint.
    pub engine: String,
}

/// Pick the single discovered instance matching `identity`, refusing to
/// guess when more than one does. An ambiguous match (two live candidates
/// currently claiming the same identity) must never silently resolve to
/// an arbitrary one of them — that's how you end up quietly reconnected
/// to the wrong endpoint.
pub fn resolve_unique<'a>(
    candidates: &'a [DiscoveredInstance],
    identity: &str,
) -> Result<Option<&'a DiscoveredInstance>, &'static str> {
    let mut matches = candidates.iter().filter(|c| c.discovered_via == identity);
    let Some(first) = matches.next() else {
        return Ok(None);
    };
    if matches.next().is_some() {
        return Err("ambiguous: multiple candidates share this identity");
    }
    Ok(Some(first))
}

/// Ports never probed by the socket scan: well-known non-inference services (ssh, dns, cups,
/// node_exporter) plus whatever the operator adds with `--ignore-port`.
pub const DEFAULT_IGNORED_PORTS: [u16; 4] = [22, 53, 631, 9100];

static EXTRA_IGNORED_PORTS: std::sync::OnceLock<Vec<u16>> = std::sync::OnceLock::new();

/// Record the operator's extra ignored ports. Called once at startup; later calls are ignored.
pub fn set_ignored_ports(extra: &[u16]) {
    let _ = EXTRA_IGNORED_PORTS.set(extra.to_vec());
}

/// The gateway's monitoring listener is read through its own `/health` and `/metrics`, never fingerprinted:
/// its workload endpoints refuse local callers, so every probe there would be recorded as a refused
/// local-origin request.
fn gateway_monitoring_port() -> Option<u16> {
    crate::orchestrator::DEFAULT_URL.trim_end_matches('/').rsplit(':').next()?.parse().ok()
}

pub fn is_ignored_port(port: u16) -> bool {
    DEFAULT_IGNORED_PORTS.contains(&port)
        || gateway_monitoring_port() == Some(port)
        || EXTRA_IGNORED_PORTS.get().is_some_and(|ports| ports.contains(&port))
}

#[cfg(target_os = "linux")]
pub fn discover(configured_api_key: Option<&str>) -> Vec<DiscoveredInstance> {
    linux::discover(configured_api_key)
}

#[cfg(not(target_os = "linux"))]
pub fn discover(_configured_api_key: Option<&str>) -> Vec<DiscoveredInstance> {
    Vec::new()
}

#[cfg(target_os = "linux")]
mod linux {
    use super::{is_ignored_port, AuthState, Confidence, DiscoveredInstance};
    use std::collections::HashSet;
    use std::fs;
    use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
    use std::os::unix::fs::MetadataExt;
    use std::process::Command;
    use std::time::Duration;

    struct Candidate {
        pid: u32,
        uid: u32,
        via: String,
    }

    /// A LISTEN-state row from `/proc/net/tcp{,6}`.
    #[derive(Clone, Copy)]
    struct ListenSocket {
        addr: IpAddr,
        port: u16,
        uid: u32,
        inode: u64,
    }

    pub fn discover(configured_api_key: Option<&str>) -> Vec<DiscoveredInstance> {
        let mut candidates = Vec::new();
        let mut seen_pids = HashSet::new();

        for (pid, unit) in systemd_vllm_units() {
            if seen_pids.insert(pid) {
                let uid = pid_uid(pid).unwrap_or(u32::MAX);
                candidates.push(Candidate {
                    pid,
                    uid,
                    via: format!("systemd {unit}"),
                });
            }
        }
        for pid in proc_vllm_processes() {
            if seen_pids.insert(pid) {
                let uid = pid_uid(pid).unwrap_or(u32::MAX);
                let sig = cmdline_signature(pid).unwrap_or_else(|| "vllm serve".to_string());
                candidates.push(Candidate {
                    pid,
                    uid,
                    via: format!("process ({sig})"),
                });
            }
        }

        let listen_table = all_listen_sockets();

        // When fd-based verification isn't possible for a candidate (the
        // common case cross-user), attribution falls back to uid alone —
        // and uid alone cannot tell two same-uid candidates' sockets
        // apart. This used to mean whichever candidate got processed
        // first silently claimed *all* of that uid's ports, mislabeling
        // them as its own — caught live on a real deployment running two
        // independent single-GPU vLLM workers under one service account,
        // where every port ended up attributed to just the first worker.
        // Precomputing which uids have more than one such candidate lets
        // ports shared that way get an honest combined identity instead.
        let mut uid_fallback_vias: std::collections::HashMap<u32, Vec<String>> = std::collections::HashMap::new();
        for cand in &candidates {
            if cand.uid != u32::MAX && attributed_inodes(cand.pid).is_none() {
                uid_fallback_vias.entry(cand.uid).or_default().push(cand.via.clone());
            }
        }

        // A process's uid commonly owns several listening sockets besides
        // the actual API port (vLLM's tensor-parallel workers talk to each
        // other over internal ZMQ/RPC ports on loopback, for instance) —
        // observed on this box: 25 LISTEN sockets for one vLLM deployment,
        // one of which is the real API. Probing them one at a time would
        // make startup take as long as (candidate count * probe timeout);
        // probing them concurrently keeps total wall time bounded by a
        // single probe's timeout regardless of how many candidates exist.
        let mut seen = HashSet::new();
        let mut targets = Vec::new();
        let mut scanned = Vec::new();
        for cand in &candidates {
            if cand.uid == u32::MAX {
                continue;
            }
            for (sock, confidence) in attribute_sockets(cand, &listen_table) {
                if is_ignored_port(sock.port) {
                    continue;
                }
                if !seen.insert((sock.addr, sock.port)) {
                    continue;
                }
                let via = match confidence {
                    Confidence::Verified => cand.via.clone(),
                    Confidence::UidAssociation => merged_identity(cand.uid, &uid_fallback_vias),
                };
                targets.push((normalize_bind_addr(sock.addr), sock.port, via, confidence));
            }
        }

        // Socket ownership and process names are attribution hints only. Probe every remaining
        // LISTEN socket (loopback, wildcard or a host address) so an ad-hoc server started after
        // vllm-top can be found even when it is not a vLLM process or systemd unit. No config,
        // environment, or credential is read from the owning process; generic fingerprints never
        // receive a caller API key. A socket already classified within FINGERPRINT_TTL is not
        // probed again; a closed socket (its inode gone) is forgotten immediately.
        let live_inodes: HashSet<u64> = listen_table.iter().map(|sock| sock.inode).collect();
        let mut cached = Vec::new();
        {
            let mut cache = fingerprint_cache().lock().unwrap_or_else(|e| e.into_inner());
            cache.retain(|inode, (at, _)| live_inodes.contains(inode) && at.elapsed() < FINGERPRINT_TTL);
            for sock in &listen_table {
                if let Some((_, result)) = cache.get(&sock.inode) {
                    if seen.insert((sock.addr, sock.port)) {
                        cached.extend(result.clone());
                    }
                }
            }
        }
        for sock in &listen_table {
            if is_ignored_port(sock.port) {
                continue;
            }
            if seen.insert((sock.addr, sock.port)) {
                scanned.push((
                    sock.inode,
                    normalize_bind_addr(sock.addr),
                    sock.port,
                    format!("listening socket uid {} port {}", sock.uid, sock.port),
                ));
            }
        }

        let key = configured_api_key.map(|s| s.to_string());
        let handles: Vec<_> = targets
            .into_iter()
            .map(|(addr, port, via, confidence)| {
                let key = key.clone();
                std::thread::spawn(move || {
                    validate(&base_url(addr, port), key.as_deref(), &via, confidence)
                })
            })
            .collect();
        let scan_handles: Vec<_> = scanned
            .into_iter()
            .map(|(inode, addr, port, via)| {
                let key = key.clone();
                (inode, std::thread::spawn(move || {
                    validate(&base_url(addr, port), key.as_deref(), &via, Confidence::UidAssociation)
                }))
            })
            .collect();

        let mut found: Vec<DiscoveredInstance> = handles.into_iter().filter_map(|h| h.join().unwrap_or(None)).collect();
        let mut cache = fingerprint_cache().lock().unwrap_or_else(|e| e.into_inner());
        for (inode, handle) in scan_handles {
            let result = handle.join().unwrap_or(None);
            cache.insert(inode, (std::time::Instant::now(), result.clone()));
            found.extend(result);
        }
        found.extend(cached);
        found
    }

    /// How long a scanned socket's classification (inference engine or not) is reused before it
    /// is fingerprinted again.
    const FINGERPRINT_TTL: Duration = Duration::from_secs(60);

    type FingerprintCache = std::collections::HashMap<u64, (std::time::Instant, Option<DiscoveredInstance>)>;

    fn fingerprint_cache() -> &'static std::sync::Mutex<FingerprintCache> {
        static CACHE: std::sync::OnceLock<std::sync::Mutex<FingerprintCache>> = std::sync::OnceLock::new();
        CACHE.get_or_init(Default::default)
    }

    /// The identity to report for a `UidAssociation` port owned by `uid`.
    /// If only one uid-fallback candidate exists for that uid, its own
    /// identity is used unchanged (the common, unambiguous case). If
    /// several share the uid, names every one of them rather than picking
    /// an arbitrary single "discovered via" — false precision would be
    /// worse than an honestly-ambiguous label here.
    fn merged_identity(uid: u32, groups: &std::collections::HashMap<u32, Vec<String>>) -> String {
        let mut names = groups.get(&uid).cloned().unwrap_or_default();
        names.sort();
        names.dedup();
        match names.len() {
            0 => format!("uid {uid}"),
            1 => names.into_iter().next().unwrap(),
            _ => format!("uid {uid} shared by {}", names.join(" + ")),
        }
    }

    /// Resolve which of the listening sockets in `table` belong to
    /// `cand`. Prefers exact attribution via that process's own open file
    /// descriptors (only possible when we can read `/proc/<pid>/fd` —
    /// i.e. `cand` shares our uid, or we're root, which `vllm-top` never
    /// requires or assumes). Falls back to uid matching, explicitly
    /// labeled as the weaker signal it is, only when fd inspection isn't
    /// possible at all.
    fn attribute_sockets(cand: &Candidate, table: &[ListenSocket]) -> Vec<(ListenSocket, Confidence)> {
        if let Some(inodes) = attributed_inodes(cand.pid) {
            return table
                .iter()
                .filter(|s| inodes.contains(&s.inode))
                .map(|s| (*s, Confidence::Verified))
                .collect();
        }
        table
            .iter()
            .filter(|s| s.uid == cand.uid)
            .map(|s| (*s, Confidence::UidAssociation))
            .collect()
    }

    // -- systemd -------------------------------------------------------

    fn systemd_vllm_units() -> Vec<(u32, String)> {
        let Ok(output) = Command::new("systemctl")
            .args(["list-units", "--type=service", "--all", "--no-legend", "--plain"])
            .output()
        else {
            return Vec::new();
        };
        if !output.status.success() {
            return Vec::new();
        }
        let text = String::from_utf8_lossy(&output.stdout);
        let units: Vec<String> = text
            .lines()
            .filter_map(|line| line.split_whitespace().next())
            .filter(|unit| unit.to_lowercase().contains("vllm"))
            .map(|s| s.to_string())
            .collect();

        units
            .into_iter()
            .filter_map(|unit| systemd_unit_pid(&unit).map(|pid| (pid, unit)))
            .collect()
    }

    fn systemd_unit_pid(unit: &str) -> Option<u32> {
        let output = Command::new("systemctl")
            .args(["show", unit, "-p", "ActiveState", "-p", "MainPID"])
            .output()
            .ok()?;
        if !output.status.success() {
            return None;
        }
        let text = String::from_utf8_lossy(&output.stdout);
        let mut active = false;
        let mut pid = None;
        for line in text.lines() {
            if let Some(v) = line.strip_prefix("ActiveState=") {
                active = v == "active";
            }
            if let Some(v) = line.strip_prefix("MainPID=") {
                pid = v.parse::<u32>().ok();
            }
        }
        if active {
            pid.filter(|&p| p != 0)
        } else {
            None
        }
    }

    // -- /proc -----------------------------------------------------------

    fn pid_uid(pid: u32) -> Option<u32> {
        fs::metadata(format!("/proc/{pid}")).ok().map(|m| m.uid())
    }

    fn read_cmdline(pid: u32) -> Option<Vec<String>> {
        let raw = fs::read(format!("/proc/{pid}/cmdline")).ok()?;
        Some(
            raw.split(|&b| b == 0)
                .filter(|s| !s.is_empty())
                .map(|s| String::from_utf8_lossy(s).into_owned())
                .collect(),
        )
    }

    fn cmdline_signature(pid: u32) -> Option<String> {
        let args = read_cmdline(pid)?;
        vllm_signature(&args)
    }

    fn proc_vllm_processes() -> Vec<u32> {
        let mut out = Vec::new();
        let Ok(entries) = fs::read_dir("/proc") else {
            return out;
        };
        for entry in entries.flatten() {
            let Some(pid) = entry.file_name().to_str().and_then(|s| s.parse::<u32>().ok()) else {
                continue;
            };
            let Some(args) = read_cmdline(pid) else {
                continue;
            };
            if is_vllm_cmdline(&args) {
                out.push(pid);
            }
        }
        out
    }

    /// True for `vllm serve ...` / `python -m vllm.entrypoints.openai.api_server ...`
    /// style invocations, however the interpreter/wrapper got in front of them
    /// (e.g. `python3 /opt/venv/bin/vllm serve ...`, or a container's
    /// `--entrypoint vllm ... serve ...`).
    pub(super) fn is_vllm_cmdline(args: &[String]) -> bool {
        vllm_signature(args).is_some()
    }

    fn vllm_signature(args: &[String]) -> Option<String> {
        if args
            .iter()
            .any(|a| a.contains("vllm.entrypoints.openai.api_server"))
        {
            return Some("vllm.entrypoints.openai.api_server".to_string());
        }
        for (i, a) in args.iter().enumerate() {
            let base = a.rsplit('/').next().unwrap_or(a);
            if base == "vllm" && args[i + 1..].iter().any(|later| later == "serve") {
                return Some("vllm serve".to_string());
            }
        }
        None
    }

    /// The exact set of socket inodes `pid` has open, via `/proc/<pid>/fd`.
    /// `None` means the directory couldn't be enumerated at all (almost
    /// always a cross-user permission denial) — a hard "can't tell,"
    /// distinct from `Some(empty set)` ("could tell, and it's none").
    fn attributed_inodes(pid: u32) -> Option<HashSet<u64>> {
        let entries = fs::read_dir(format!("/proc/{pid}/fd")).ok()?;
        let mut inodes = HashSet::new();
        for entry in entries.flatten() {
            if let Ok(target) = fs::read_link(entry.path()) {
                if let Some(inode) = parse_socket_inode(&target.to_string_lossy()) {
                    inodes.insert(inode);
                }
            }
        }
        Some(inodes)
    }

    fn parse_socket_inode(link: &str) -> Option<u64> {
        link.strip_prefix("socket:[")?.strip_suffix(']')?.parse().ok()
    }

    // -- socket table ----------------------------------------------------

    fn all_listen_sockets() -> Vec<ListenSocket> {
        const TCP_LISTEN: u8 = 0x0A;
        let mut out = Vec::new();
        for path in ["/proc/net/tcp", "/proc/net/tcp6"] {
            let Ok(text) = fs::read_to_string(path) else {
                continue;
            };
            for line in text.lines().skip(1) {
                if let Some(row) = parse_tcp_line(line) {
                    if row.state == TCP_LISTEN {
                        out.push(ListenSocket {
                            addr: row.addr,
                            port: row.port,
                            uid: row.uid,
                            inode: row.inode,
                        });
                    }
                }
            }
        }
        out
    }

    pub(super) struct TcpRow {
        pub addr: IpAddr,
        pub port: u16,
        pub uid: u32,
        pub state: u8,
        pub inode: u64,
    }

    pub(super) fn parse_tcp_line(line: &str) -> Option<TcpRow> {
        let fields: Vec<&str> = line.split_whitespace().collect();
        if fields.len() < 10 {
            return None;
        }
        let (addr_hex, port_hex) = fields[1].split_once(':')?;
        let addr = decode_addr_hex(addr_hex)?;
        let port = u16::from_str_radix(port_hex, 16).ok()?;
        let state = u8::from_str_radix(fields[3], 16).ok()?;
        let uid = fields[7].parse::<u32>().ok()?;
        let inode = fields[9].parse::<u64>().ok()?;
        Some(TcpRow { addr, port, uid, state, inode })
    }

    /// `/proc/net/tcp{,6}` addresses are 32-bit words in host (little-endian
    /// on every platform this ships for) byte order, printed as hex — so
    /// each 4-byte word's *bytes* are reversed relative to normal dotted /
    /// colon notation, but the words themselves stay in order.
    pub(super) fn decode_addr_hex(hex: &str) -> Option<IpAddr> {
        if hex.is_empty() || !hex.len().is_multiple_of(8) {
            return None;
        }
        let mut bytes = Vec::with_capacity(hex.len() / 2);
        for word in hex.as_bytes().chunks(8) {
            let word_str = std::str::from_utf8(word).ok()?;
            let mut word_bytes = [0u8; 4];
            for i in 0..4 {
                word_bytes[3 - i] = u8::from_str_radix(&word_str[i * 2..i * 2 + 2], 16).ok()?;
            }
            bytes.extend_from_slice(&word_bytes);
        }
        match bytes.len() {
            4 => Some(IpAddr::V4(Ipv4Addr::new(bytes[0], bytes[1], bytes[2], bytes[3]))),
            16 => {
                let arr: [u8; 16] = bytes.try_into().ok()?;
                Some(IpAddr::V6(Ipv6Addr::from(arr)))
            }
            _ => None,
        }
    }

    fn normalize_bind_addr(addr: IpAddr) -> IpAddr {
        match addr {
            IpAddr::V4(v4) if v4.is_unspecified() => IpAddr::V4(Ipv4Addr::LOCALHOST),
            IpAddr::V6(v6) if v6.is_unspecified() => IpAddr::V6(Ipv6Addr::LOCALHOST),
            other => other,
        }
    }

    fn base_url(ip: IpAddr, port: u16) -> String {
        match ip {
            IpAddr::V4(v4) => format!("http://{v4}:{port}"),
            IpAddr::V6(v6) => format!("http://[{v6}]:{port}"),
        }
    }

    // -- capability / auth probing ----------------------------------------

    /// Real, minimal evidence a `/metrics` body is vLLM's own: at least
    /// one `vllm:`-prefixed Prometheus series. Kept as a pure function
    /// (rather than inlined in `validate`) so it's directly testable
    /// without a real HTTP server, matching this file's existing
    /// convention (`classify_auth`, `is_vllm_cmdline`).
    fn looks_like_vllm_metrics(body: &str) -> bool {
        crate::promparse::parse(body).iter().any(|s| s.name.starts_with("vllm:"))
    }

    fn validate(
        base: &str,
        api_key: Option<&str>,
        via: &str,
        confidence: Confidence,
    ) -> Option<DiscoveredInstance> {
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_millis(1500))
            .connect_timeout(Duration::from_millis(1500))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .ok()?;

        // Fingerprint only bounded, no-inference GET endpoints. Generic probes do not receive
        // configured credentials; a caller key is attached only after a vLLM-specific fingerprint.
        let metrics_body = client
            .get(format!("{base}/metrics"))
            .send()
            .ok()
            .filter(|r| r.status().is_success())
            .and_then(|r| r.text().ok())
            .unwrap_or_default();
        let props: Option<serde_json::Value> = client
            .get(format!("{base}/props"))
            .send()
            .ok()
            .filter(|r| r.status().is_success())
            .and_then(|r| r.json().ok());
        let engine = fingerprint_engine(&metrics_body, props.as_ref(), &client, base);
        let Some(engine) = engine else {
            return None;
        };

        let mut req = client.get(format!("{base}/v1/models"));
        // The supplied credential is used only after a vLLM-specific fingerprint. It is never
        // forwarded to an unrelated listener discovered by the socket scan.
        let has_credential = engine == "vLLM" && api_key.is_some();
        if engine == "vLLM" {
            if let Some(key) = api_key {
                req = req.bearer_auth(key);
            }
        }
        let v1_status = req.send().ok().map(|r| r.status().as_u16());

        Some(DiscoveredInstance {
            url: base.to_string(),
            auth: classify_auth(has_credential, v1_status),
            confidence,
            discovered_via: via.to_string(),
            engine: engine.to_string(),
        })
    }

    fn fingerprint_engine(
        metrics: &str,
        props: Option<&serde_json::Value>,
        client: &reqwest::blocking::Client,
        base: &str,
    ) -> Option<&'static str> {
        let sglang_info = get_json(client, &format!("{base}/get_server_info")).is_some();
        let ollama_version = get_json(client, &format!("{base}/api/version"))
            .is_some_and(|v| v.get("version").is_some());
        let tgi_info = get_json(client, &format!("{base}/info"))
            .is_some_and(|v| v.get("model_id").is_some());
        let models_status = client.get(format!("{base}/v1/models")).send().ok().and_then(|r| {
            let status = r.status().as_u16();
            let body: Option<serde_json::Value> = r.json().ok();
            openai_models_shape(status, body.as_ref()).then_some(status)
        });
        classify_engine(metrics, props, sglang_info, ollama_version, tgi_info, models_status)
    }

    fn classify_engine(
        metrics: &str,
        props: Option<&serde_json::Value>,
        sglang_info: bool,
        ollama_version: bool,
        tgi_info: bool,
        models_status: Option<u16>,
    ) -> Option<&'static str> {
        if looks_like_vllm_metrics(metrics) {
            return Some("vLLM");
        }
        let names: Vec<String> = crate::promparse::parse(metrics).into_iter().map(|s| s.name).collect();
        if names.iter().any(|name| name.starts_with("llamacpp:"))
            || props.is_some_and(|value| value.get("total_slots").is_some() || value.get("model_alias").is_some())
        {
            return Some("llama.cpp");
        }
        if names.iter().any(|name| name.starts_with("sglang:")) || sglang_info {
            return Some("SGLang");
        }
        if ollama_version {
            return Some("Ollama");
        }
        if tgi_info {
            return Some("TGI");
        }
        // Unknown OpenAI-compatible servers remain visible with limited metrics.
        if models_status.is_some_and(|status| (200..300).contains(&status) || status == 401 || status == 403) {
            return Some("unknown engine, limited metrics");
        }
        None
    }

    /// A `/v1/models` answer counts as an inference endpoint only in the OpenAI shape: a model list
    /// on success, or an OpenAI-style `error` object when authentication is required. Anything else
    /// (a login page, a 404 handler that echoes 401, ...) is not evidence of an inference server.
    pub(super) fn openai_models_shape(status: u16, body: Option<&serde_json::Value>) -> bool {
        match status {
            200..=299 => body.is_some_and(|b| b.get("data").is_some_and(serde_json::Value::is_array)),
            401 | 403 => body.is_some_and(|b| b.get("error").is_some()),
            _ => false,
        }
    }

    fn get_json(client: &reqwest::blocking::Client, url: &str) -> Option<serde_json::Value> {
        client.get(url).send().ok().filter(|r| r.status().is_success()).and_then(|r| r.json().ok())
    }

    pub(super) fn classify_auth(has_credential: bool, v1_models_status: Option<u16>) -> AuthState {
        match v1_models_status {
            Some(s) if (200..300).contains(&s) => {
                if has_credential {
                    AuthState::RequiredCredentialAccepted
                } else {
                    AuthState::NotRequired
                }
            }
            Some(401) | Some(403) => {
                if has_credential {
                    AuthState::RequiredCredentialRejected
                } else {
                    AuthState::RequiredNoCredential
                }
            }
            Some(_) => AuthState::NotRequired,
            None => AuthState::Unknown,
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn decodes_ipv4_loopback() {
            // 127.0.0.1 encoded as observed in a real /proc/net/tcp line.
            assert_eq!(
                decode_addr_hex("0100007F"),
                Some(IpAddr::V4(Ipv4Addr::new(127, 0, 0, 1)))
            );
        }

        #[test]
        fn decodes_ipv4_unspecified() {
            assert_eq!(
                decode_addr_hex("00000000"),
                Some(IpAddr::V4(Ipv4Addr::UNSPECIFIED))
            );
        }

        #[test]
        fn decodes_ipv6_loopback() {
            // ::1 as 4 little-endian 32-bit words: 0, 0, 0, 1.
            assert_eq!(
                decode_addr_hex("00000000000000000000000001000000"),
                Some(IpAddr::V6(Ipv6Addr::LOCALHOST))
            );
        }

        #[test]
        fn parses_real_listen_line() {
            // Captured verbatim (uid/inode) from the real /proc/net/tcp LISTEN
            // row for the vLLM server this was built against: 0.0.0.0:8000.
            let line = "  20: 00000000:1F40 00000000:0000 0A 00000000:00000000 00:00000000 00000000   999        0 759871 1 0000000000000000 100 0 0 10 0";
            let row = parse_tcp_line(line).expect("line parses");
            assert_eq!(row.addr, IpAddr::V4(Ipv4Addr::UNSPECIFIED));
            assert_eq!(row.port, 8000);
            assert_eq!(row.uid, 999);
            assert_eq!(row.state, 0x0A);
            assert_eq!(row.inode, 759871);
        }

        #[test]
        fn parses_non_listen_line_as_non_listen_state() {
            let line = "  40: 0100007F:DB56 0100007F:1F40 06 00000000:00000000 03:00000B2B 00000000     0        0 0 3 0000000000000000";
            let row = parse_tcp_line(line).expect("line parses");
            assert_ne!(row.state, 0x0A);
        }

        #[test]
        fn rejects_malformed_line() {
            assert!(parse_tcp_line("garbage").is_none());
        }

        #[test]
        fn detects_python_wrapped_vllm_serve() {
            let args = vec![
                "/opt/venv/bin/python3".to_string(),
                "/opt/venv/bin/vllm".to_string(),
                "serve".to_string(),
                "--config".to_string(),
                "/cfg/vllm-config.yaml".to_string(),
                "--tensor-parallel-size".to_string(),
                "2".to_string(),
            ];
            assert!(is_vllm_cmdline(&args));
        }

        #[test]
        fn detects_container_entrypoint_form() {
            let args = vec![
                "podman".to_string(),
                "run".to_string(),
                "--entrypoint".to_string(),
                "vllm".to_string(),
                "docker.io/vllm/vllm-openai-xpu@sha256:deadbeef".to_string(),
                "serve".to_string(),
                "--config".to_string(),
                "/cfg/vllm-config.yaml".to_string(),
            ];
            assert!(is_vllm_cmdline(&args));
        }

        #[test]
        fn detects_module_invocation() {
            let args = vec![
                "python3".to_string(),
                "-m".to_string(),
                "vllm.entrypoints.openai.api_server".to_string(),
                "--port".to_string(),
                "8001".to_string(),
            ];
            assert!(is_vllm_cmdline(&args));
        }

        #[test]
        fn rejects_unrelated_process() {
            let args = vec!["/usr/bin/ps".to_string(), "aux".to_string()];
            assert!(!is_vllm_cmdline(&args));
        }

        #[test]
        fn rejects_vllm_mentioned_without_serve() {
            // e.g. `grep vllm /var/log/syslog` — "vllm" appears, no server.
            let args = vec!["grep".to_string(), "vllm".to_string(), "/var/log/syslog".to_string()];
            assert!(!is_vllm_cmdline(&args));
        }

        #[test]
        fn auth_not_required_without_credential() {
            assert_eq!(classify_auth(false, Some(200)), AuthState::NotRequired);
        }

        #[test]
        fn auth_required_no_credential() {
            assert_eq!(classify_auth(false, Some(401)), AuthState::RequiredNoCredential);
        }

        #[test]
        fn auth_required_credential_accepted() {
            assert_eq!(
                classify_auth(true, Some(200)),
                AuthState::RequiredCredentialAccepted
            );
        }

        #[test]
        fn auth_required_credential_rejected() {
            assert_eq!(
                classify_auth(true, Some(403)),
                AuthState::RequiredCredentialRejected
            );
        }

        #[test]
        fn auth_unknown_when_probe_fails() {
            assert_eq!(classify_auth(true, None), AuthState::Unknown);
        }

        #[test]
        fn looks_like_vllm_metrics_accepts_a_real_vllm_exposition() {
            let text = "\
vllm:num_requests_running 3.0
vllm:num_requests_waiting 7.0
vllm:kv_cache_usage_perc 0.42
";
            assert!(looks_like_vllm_metrics(text));
        }

        #[test]
        fn looks_like_vllm_metrics_rejects_a_same_uid_non_vllm_service() {
            // The real false positive this check exists to close: an
            // orchestrator gateway sharing the vLLM workers' uid, with
            // its own real Prometheus `/metrics` output (verified against
            // the actual live gateway) that simply isn't vLLM's.
            let text = "\
aihost_gateway_uptime_seconds 217.957
aihost_scheduler_queued_work 0
aihost_worker_health_status{worker_id=\"b0-live-tp1-worker1\"} 1
";
            assert!(!looks_like_vllm_metrics(text));
        }

        #[test]
        fn looks_like_vllm_metrics_rejects_empty_or_unparseable_bodies() {
            assert!(!looks_like_vllm_metrics(""));
            assert!(!looks_like_vllm_metrics("not a prometheus body at all"));
        }

        #[test]
        fn fingerprints_recorded_engine_fixtures_and_unknown_openai_servers() {
            let props: serde_json::Value = serde_json::from_str(include_str!("../tests/fixtures/llamacpp/props.json")).unwrap();
            assert_eq!(classify_engine(
                include_str!("../tests/fixtures/vllm/metrics.txt"), None, false, false, false, Some(200)),
                Some("vLLM")
            );
            assert_eq!(classify_engine(
                include_str!("../tests/fixtures/llamacpp/metrics.txt"), Some(&props), false, false, false, Some(200)),
                Some("llama.cpp")
            );
            assert_eq!(classify_engine(
                include_str!("../tests/fixtures/sglang/metrics.txt"), None, false, false, false, Some(200)),
                Some("SGLang")
            );
            let ollama: serde_json::Value = serde_json::from_str(include_str!("../tests/fixtures/ollama/version.json")).unwrap();
            let tgi: serde_json::Value = serde_json::from_str(include_str!("../tests/fixtures/tgi/info.json")).unwrap();
            assert_eq!(ollama["version"], "0.6.0");
            assert_eq!(tgi["model_id"], "test-model");
            assert_eq!(classify_engine("", None, false, true, false, None), Some("Ollama"));
            assert_eq!(classify_engine("", None, false, false, true, None), Some("TGI"));
            assert_eq!(classify_engine(
                include_str!("../tests/fixtures/openai/metrics.txt"), None, false, false, false, Some(401)),
                Some("unknown engine, limited metrics")
            );
            assert_eq!(classify_engine("", None, false, false, false, Some(404)), None);
        }

        #[test]
        fn only_openai_shaped_model_answers_count_as_inference() {
            let list = serde_json::json!({"object": "list", "data": [{"id": "m"}]});
            let auth_error = serde_json::json!({"error": {"message": "invalid api key", "type": "invalid_request_error"}});
            let login_page = serde_json::json!({"message": "Unauthorized"});
            assert!(openai_models_shape(200, Some(&list)));
            assert!(openai_models_shape(401, Some(&auth_error)));
            assert!(openai_models_shape(403, Some(&auth_error)));
            assert!(!openai_models_shape(401, Some(&login_page)), "a non-OpenAI 401 is not an inference server");
            assert!(!openai_models_shape(401, None), "a non-JSON 401 is not an inference server");
            assert!(!openai_models_shape(200, Some(&login_page)), "a 200 without a model list is not one either");
            assert!(!openai_models_shape(302, None));
        }

        #[test]
        fn well_known_and_operator_ports_are_never_probed() {
            super::super::set_ignored_ports(&[8443]);
            for port in [22, 53, 631, 9100, 8443] {
                assert!(super::super::is_ignored_port(port), "{port}");
            }
            assert!(super::super::is_ignored_port(8010), "the gateway monitoring port is never fingerprinted");
            assert!(!super::super::is_ignored_port(8000));
        }

        #[test]
        fn attribution_prefers_verified_when_fds_known() {
            let sockets = [
                ListenSocket { addr: IpAddr::V4(Ipv4Addr::LOCALHOST), port: 8000, uid: 999, inode: 111 },
                ListenSocket { addr: IpAddr::V4(Ipv4Addr::LOCALHOST), port: 9000, uid: 999, inode: 222 },
            ];
            // Same uid owns both sockets, but this candidate's own fd table
            // (simulated) only actually holds inode 111 — verified
            // attribution must not also claim the other same-uid socket.
            let cand = Candidate { pid: 1, uid: 999, via: "test".into() };
            let mut owned = HashSet::new();
            owned.insert(111u64);
            let result: Vec<_> = sockets
                .iter()
                .filter(|s| owned.contains(&s.inode))
                .map(|s| (*s, Confidence::Verified))
                .collect();
            assert_eq!(result.len(), 1);
            assert_eq!(result[0].0.port, 8000);
            assert_eq!(result[0].1, Confidence::Verified);
            let _ = cand; // constructed to mirror real call shape
        }

        #[test]
        fn attribution_falls_back_to_uid_when_fds_unreadable() {
            let sockets = [
                ListenSocket { addr: IpAddr::V4(Ipv4Addr::LOCALHOST), port: 8000, uid: 999, inode: 111 },
                ListenSocket { addr: IpAddr::V4(Ipv4Addr::LOCALHOST), port: 5555, uid: 1000, inode: 333 },
            ];
            let cand = Candidate { pid: 99999999, uid: 999, via: "test".into() };
            // pid 99999999 almost certainly doesn't exist, so attributed_inodes
            // returns None (directory can't be opened) exactly like a
            // cross-user permission denial would.
            let result = attribute_sockets(&cand, &sockets);
            assert_eq!(result.len(), 1);
            assert_eq!(result[0].0.port, 8000);
            assert_eq!(result[0].1, Confidence::UidAssociation);
        }

        #[test]
        fn merged_identity_is_unchanged_for_a_single_candidate() {
            let mut groups = std::collections::HashMap::new();
            groups.insert(999u32, vec!["systemd vllm.service".to_string()]);
            assert_eq!(merged_identity(999, &groups), "systemd vllm.service");
        }

        #[test]
        fn merged_identity_combines_names_when_a_uid_is_shared() {
            // Regression test for a real bug found on a live deployment:
            // two independent single-GPU vLLM workers running as the same
            // service account had every one of their ports (both workers'
            // real API ports, discovered correctly) attributed entirely to
            // whichever worker's candidate was processed first — a false,
            // specific claim, not just an imprecise one.
            let mut groups = std::collections::HashMap::new();
            groups.insert(
                999u32,
                vec![
                    "systemd aihost-vllm-worker2.service".to_string(),
                    "systemd aihost-vllm-worker1.service".to_string(),
                ],
            );
            let identity = merged_identity(999, &groups);
            assert!(identity.contains("aihost-vllm-worker1.service"), "{identity}");
            assert!(identity.contains("aihost-vllm-worker2.service"), "{identity}");
            assert!(identity.contains("shared"), "{identity}");
        }

        #[test]
        fn merged_identity_dedupes_identical_names() {
            let mut groups = std::collections::HashMap::new();
            groups.insert(999u32, vec!["systemd vllm.service".to_string(), "systemd vllm.service".to_string()]);
            assert_eq!(merged_identity(999, &groups), "systemd vllm.service");
        }

        #[test]
        fn merged_identity_falls_back_when_uid_absent_from_groups() {
            let groups = std::collections::HashMap::new();
            assert_eq!(merged_identity(999, &groups), "uid 999");
        }

        #[test]
        fn resolve_unique_returns_none_when_absent() {
            let candidates: Vec<DiscoveredInstance> = Vec::new();
            assert_eq!(
                super::super::resolve_unique(&candidates, "systemd vllm.service"),
                Ok(None)
            );
        }

        #[test]
        fn resolve_unique_errs_on_ambiguity() {
            let candidates = vec![
                DiscoveredInstance {
                    url: "http://127.0.0.1:8000".into(),
                    auth: AuthState::NotRequired,
                    confidence: Confidence::UidAssociation,
                    discovered_via: "systemd vllm.service".into(),
                    engine: "vLLM".into(),
                },
                DiscoveredInstance {
                    url: "http://127.0.0.1:8001".into(),
                    auth: AuthState::NotRequired,
                    confidence: Confidence::UidAssociation,
                    discovered_via: "systemd vllm.service".into(),
                    engine: "vLLM".into(),
                },
            ];
            assert!(super::super::resolve_unique(&candidates, "systemd vllm.service").is_err());
        }

        #[test]
        fn resolve_unique_picks_sole_match() {
            let candidates = vec![DiscoveredInstance {
                url: "http://127.0.0.1:8000".into(),
                auth: AuthState::NotRequired,
                confidence: Confidence::Verified,
                discovered_via: "systemd vllm.service".into(),
                engine: "vLLM".into(),
            }];
            let found = super::super::resolve_unique(&candidates, "systemd vllm.service")
                .expect("not ambiguous")
                .expect("found");
            assert_eq!(found.url, "http://127.0.0.1:8000");
        }
    }
}
