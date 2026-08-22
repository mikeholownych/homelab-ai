#!/usr/bin/env python3
"""Collect a non-mutating OS tuning telemetry snapshot from standard interfaces.

Prints a single JSON document with sections: numa, interrupts, cpu_power,
memory_policy, hugepages, io, kernel. Optional sources that are unavailable are
recorded explicitly as {"status": "unavailable", "reason": ...} rather than
silently fabricated.
"""

import json
import re
import subprocess
from pathlib import Path

UNAVAILABLE = "unavailable"


def run(command, required=False):
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        if required:
            raise RuntimeError(f"required tuning source failed: {' '.join(command)}: {error}") from error
        return ""


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, PermissionError) as error:
        return {"status": UNAVAILABLE, "reason": f"{type(error).__name__} reading {path}"}


def read_int(path):
    value = read_text(path)
    if isinstance(value, dict):
        return value
    try:
        return int(value)
    except ValueError:
        return {"status": UNAVAILABLE, "reason": f"non-integer content in {path}"}


def bracketed_choice(content):
    """Return the active option from sysfs files like '[always] madvise never'."""
    match = re.search(r"\[([A-Za-z+]+)\]", content)
    return match.group(1) if match else None


def collect_cpu_power():
    cpu0 = Path("/sys/devices/system/cpu/cpu0")
    section = {
        "simulated": False,
        "cpu_count": read_text(cpu0 / "../online") or None,
        "scaling_governor": read_text(cpu0 / "cpufreq/scaling_governor"),
        "scaling_available_governors": read_text(cpu0 / "cpufreq/scaling_available_governors"),
        "energy_performance_preference": read_text(cpu0 / "cpufreq/energy_performance_preference"),
        "energy_performance_available_preferences": read_text(
            cpu0 / "cpufreq/energy_performance_available_preferences"
        ),
        "cstates": {},
        "platform_profile": read_text("/sys/firmware/acpi/platform_profile"),
        "platform_profile_choices": read_text("/sys/firmware/acpi/platform_profile_choices"),
    }
    cpuidle = cpu0 / "cpuidle"
    try:
        for state_dir in sorted(cpuidle.iterdir()):
            if state_dir.is_dir():
                section["cstates"][state_dir.name] = {
                    "name": read_text(state_dir / "name"),
                    "disabled": read_text(state_dir / "disable"),
                }
    except OSError as error:
        section["cstates"] = {"status": UNAVAILABLE, "reason": f"{type(error).__name__} reading {cpuidle}"}
    return section


def collect_numa():
    section = {
        "simulated": False,
        "numactl_hardware": {"status": UNAVAILABLE, "reason": "numactl not executed"},
        "lscpu_extended": {"status": UNAVAILABLE, "reason": "lscpu -j -e not executed"},
        "gpu_numa_nodes": {},
        "nodes_with_memory": {},
    }
    hardware = run(["numactl", "--hardware"])
    if hardware:
        parsed = {}
        current_node = None
        for line in hardware.splitlines():
            node_match = re.match(r"available:\s*(\d+)\s*nodes", line)
            cpus_match = re.match(r"node\s+(\d+)\s+cpus:\s*(.*)", line)
            memory_match = re.match(r"node\s+(\d+)\s+size:\s*(\d+)\s*MB", line)
            free_match = re.match(r"node\s+(\d+)\s+free:\s*(\d+)\s*MB", line)
            if node_match:
                parsed["node_count"] = int(node_match.group(1))
            elif cpus_match:
                current_node = int(cpus_match.group(1))
                parsed.setdefault("cpu_map", {})[str(current_node)] = [
                    int(item) for item in cpus_match.group(2).split()
                ]
            elif memory_match and current_node is not None:
                parsed.setdefault("memory_mb", {})[str(memory_match.group(1))] = int(memory_match.group(2))
            elif free_match:
                parsed.setdefault("free_mb", {})[str(free_match.group(1))] = int(free_match.group(2))
        section["numactl_hardware"] = parsed or {
            "status": UNAVAILABLE,
            "reason": "numactl output did not match expected format",
        }
    lscpu = run(["lscpu", "-j", "-e=CPU,NODE,SOCKET,CORE,ONLINE"])
    if lscpu:
        try:
            section["lscpu_extended"] = json.loads(lscpu)
        except json.JSONDecodeError:
            section["lscpu_extended"] = {"status": UNAVAILABLE, "reason": "lscpu JSON parse failure"}
    meminfo_nodes = Path("/sys/devices/system/node")
    try:
        for node_dir in sorted(meminfo_nodes.glob("node*")):
            if node_dir.is_dir():
                mem_total = read_text(node_dir / "meminfo")
                first_kb = re.search(r"MemTotal:\s+(\d+) kB", mem_total) if isinstance(mem_total, str) else None
                section["nodes_with_memory"][node_dir.name] = (
                    round(int(first_kb.group(1)) / 1024 / 1024, 2) if first_kb else None
                )
    except OSError as error:
        section["nodes_with_memory"] = {"status": UNAVAILABLE, "reason": f"{type(error).__name__}"}
    try:
        for device_dir in sorted(Path("/sys/bus/pci/devices").iterdir()):
            class_path = device_dir / "class"
            device_class = class_path.read_text().strip()
            if not device_class.startswith("0x03"):
                continue
            numa_value = read_text(device_dir / "numa_node")
            local_cpus = read_text(device_dir / "local_cpulist")
            section["gpu_numa_nodes"][device_dir.name] = {
                "numa_node": numa_value if isinstance(numa_value, dict) else int(numa_value),
                "local_cpulist": local_cpus,
            }
    except OSError as error:
        section["gpu_numa_nodes"] = {"status": UNAVAILABLE, "reason": f"{type(error).__name__}"}
    return section


def collect_interrupts():
    irqbalance_state = run(["systemctl", "is-active", "irqbalance"]).strip()
    interrupts_raw = read_text("/proc/interrupts")
    categorized = {}
    total_lines = 0
    if isinstance(interrupts_raw, str):
        for line in interrupts_raw.splitlines()[1:]:
            label_part = line.split(":", 1)
            if len(label_part) != 2:
                continue
            total_lines += 1
            labels = [item.strip() for item in label_part[1].split(",") if item.strip()]
            joined = " ".join(labels).lower()
            category = None
            if "nvme" in joined:
                category = "nvme"
            elif any(prefix in joined for prefix in ("enp", "eth", "eno", "i40e", "ice", "igb")):
                category = "nic"
            elif any(token in joined for token in ("dri", "xe", "i915", "gpu")):
                category = "gpu"
            if category:
                categorized.setdefault(category, []).append({"labels": labels})
    section = {
        "simulated": False,
        "irqbalance_active": irqbalance_state or {"status": UNAVAILABLE, "reason": "systemctl query failed"},
        "total_irq_lines": total_lines,
        "categorized": categorized,
    }
    proc_interrupts_size_ok = not isinstance(interrupts_raw, dict)
    if not proc_interrupts_size_ok:
        section["proc_interrupts"] = interrupts_raw
    return section


def collect_memory_policy():
    keys = ["vm.swappiness", "vm.dirty_ratio", "vm.dirty_background_ratio", "vm.zone_reclaim_mode"]
    live_values = {}
    sysctl_output = run(["/usr/sbin/sysctl", "-n"] + keys)
    if sysctl_output:
        lines = sysctl_output.splitlines()
        for key, line in zip(keys, lines):
            try:
                live_values[key] = int(line.strip())
            except ValueError:
                live_values[key] = {"status": UNAVAILABLE, "reason": "non-integer sysctl value"}
    else:
        live_values = {"status": UNAVAILABLE, "reason": "sysctl query failed"}
    vmstat = {}
    vmstat_raw = read_text("/proc/vmstat")
    if isinstance(vmstat_raw, str):
        wanted = ("pgmajfault", "pswpin", "pswpout", "pgscan_kswapd", "pgsteal_kswapd", "allocstall")
        for line in vmstat_raw.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in wanted:
                vmstat[parts[0]] = int(parts[1])
    meminfo_raw = read_text("/proc/meminfo")
    swap = {}
    host_memory_gib = None
    if isinstance(meminfo_raw, str):
        for line in meminfo_raw.splitlines():
            for field in ("SwapTotal", "SwapFree"):
                if line.startswith(field + ":"):
                    parts = line.split()
                    swap[field] = round(int(parts[1]) / 1024 / 1024, 2)
            if line.startswith("MemTotal:"):
                parts = line.split()
                host_memory_gib = round(int(parts[1]) / 1024 / 1024, 2)
    return {
        "simulated": False,
        "host_memory_gib": (
            host_memory_gib
            if host_memory_gib is not None
            else {"status": UNAVAILABLE, "reason": "MemTotal missing from /proc/meminfo"}
        ),
        "live_sysctl": live_values,
        "vmstat_counters": vmstat,
        "swap_gib": swap,
        "pressure_stall": _collect_pressure_stall(),
    }


def _collect_pressure_stall():
    psi = {}
    for resource in ("memory", "cpu", "io"):
        content = read_text(f"/proc/pressure/{resource}")
        if isinstance(content, str):
            full = re.search(r"full\s+avg(\d+)=([\d.]+)", content)
            some = re.search(r"some\s+avg(\d+)=([\d.]+)", content)
            psi[resource] = {
                "some_avg10_pct": float(some.group(2)) if some else None,
                "full_avg10_pct": float(full.group(2)) if full else None,
            }
        else:
            psi[resource] = content
    return psi


def collect_hugepages():
    sizes = {}
    try:
        for hp_dir in sorted(Path("/sys/kernel/mm/hugepages").glob("hugepages-*")):
            if hp_dir.is_dir():
                sizes[hp_dir.name] = {
                    "nr_hugepages": read_int(hp_dir / "nr_hugepages"),
                    "free_hugepages": read_int(hp_dir / "free_hugepages"),
                }
    except OSError as error:
        sizes = {"status": UNAVAILABLE, "reason": f"{type(error).__name__}"}
    meminfo_raw = read_text("/proc/meminfo")
    meminfo = {}
    if isinstance(meminfo_raw, str):
        for line in meminfo_raw.splitlines():
            for field in ("HugePages_Total", "HugePages_Free", "Hugepagesize", "Hugetlb"):
                if line.startswith(field + ":"):
                    parts = line.split()
                    value = float(parts[1]) if field == "Hugetlb" else int(parts[1])
                    unit = parts[2] if len(parts) > 2 else ""
                    meminfo[field] = value if field != "Hugetlb" else round(value / 1024 / 1024, 2)
                    meminfo[field + "_unit"] = unit if field != "Hugetlb" else "GiB"
    thp_enabled = read_text("/sys/kernel/mm/transparent_hugepage/enabled")
    thp_defrag = read_text("/sys/kernel/mm/transparent_hugepage/defrag")
    return {
        "simulated": False,
        "hugepages_sizes": sizes,
        "meminfo": meminfo,
        "transparent_hugepage_enabled_mode": (
            bracketed_choice(thp_enabled) if isinstance(thp_enabled, str) else thp_enabled
        ),
        "transparent_hugepage_defrag_mode": (
            bracketed_choice(thp_defrag) if isinstance(thp_defrag, str) else thp_defrag
        ),
    }


def collect_io():
    devices = {}
    try:
        nvme_dirs = sorted(Path("/sys/block").glob("nvme*n*"))
        for block in nvme_dirs:
            queue = block / "queue"
            scheduler_content = read_text(queue / "scheduler")
            devices[block.name] = {
                "scheduler_current": (
                    bracketed_choice(scheduler_content) if isinstance(scheduler_content, str) else scheduler_content
                ),
                "scheduler_available": (
                    scheduler_content.replace("[", "").replace("]", "").split()
                    if isinstance(scheduler_content, str)
                    else scheduler_content
                ),
                "read_ahead_kb": read_int(queue / "read_ahead_kb"),
            }
    except OSError as error:
        devices = {"status": UNAVAILABLE, "reason": f"{type(error).__name__}"}
    mounts = []
    mounts_raw = read_text("/proc/mounts")
    if isinstance(mounts_raw, str):
        interesting = ("/", "/var", "/home", "/opt")
        for line in mounts_raw.splitlines():
            fields = line.split()
            if len(fields) >= 4 and any(fields[1] == target for target in interesting):
                mounts.append({"target": fields[1], "fstype": fields[2], "options": fields[3]})
    return {"simulated": False, "nvme_queues": devices, "mounts": mounts}


def _secure_boot_state():
    """SecureBoot efivar is binary; tolerate any read or parse failure."""
    raw = Path(
        "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
    )
    try:
        data = raw.read_bytes()
        return bool(data[-1]) if data else {"status": UNAVAILABLE, "reason": "empty SecureBoot efivar"}
    except (OSError, PermissionError):
        return {"status": UNAVAILABLE, "reason": "SecureBoot efivar not readable"}


def collect_kernel():
    installed = run(["dpkg-query", "-W", "-f=${Package}=${Version}\n", "linux-image-generic"])
    cmdline_raw = read_text("/proc/cmdline")
    return {
        "simulated": False,
        "running_release": run(["uname", "-r"], required=True).strip(),
        "cmdline_raw": cmdline_raw,
        "cmdline_parameters": cmdline_raw.split() if isinstance(cmdline_raw, str) else [],
        "installed_kernel_packages": sorted(line for line in installed.splitlines() if line),
        "secure_boot": _secure_boot_state(),
    }


def main():
    observed = {
        "simulated": False,
        "numa": collect_numa(),
        "interrupts": collect_interrupts(),
        "cpu_power": collect_cpu_power(),
        "memory_policy": collect_memory_policy(),
        "hugepages": collect_hugepages(),
        "io": collect_io(),
        "kernel": collect_kernel(),
    }
    print(json.dumps(observed, sort_keys=True))


if __name__ == "__main__":
    main()
