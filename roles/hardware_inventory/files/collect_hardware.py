#!/usr/bin/env python3
"""Collect a non-mutating Linux hardware snapshot from standard interfaces."""

import json
import re
import subprocess
from pathlib import Path


def run(command, required=True):
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        if required:
            raise RuntimeError(f"required hardware source failed: {' '.join(command)}: {error}") from error
        return ""


def _generation(speed):
    return 5 if speed >= 32 else 4 if speed >= 16 else 3 if speed >= 8 else 2 if speed >= 5 else 1


def parse_slots(text):
    slots = {}
    for block in text.split("Handle "):
        bdf = re.search(r"Bus Address:\s*([0-9a-fA-F:.]+)", block)
        width = re.search(r"Data Bus Width:\s*(\d+)x", block) or \
                re.search(r"Type:\s*x?(\d+)\s+PCI Express", block) or \
                re.search(r"Type:\s*PCI Express.*?\bx(\d+)", block)
        if bdf and width:
            slots[bdf.group(1).lower()] = int(width.group(1))
    return slots


def collect_drm_nodes(bdf):
    """Find drm_card (/dev/dri/card*) and render_node (/dev/dri/renderD*) under sysfs."""
    drm_dir = Path("/sys/bus/pci/devices") / bdf / "drm"
    drm_card = None
    render_node = None
    if drm_dir.exists() and drm_dir.is_dir():
        for entry in sorted(drm_dir.iterdir()):
            name = entry.name
            if re.match(r"^card\d+$", name) and not drm_card:
                drm_card = f"/dev/dri/{name}"
            elif re.match(r"^renderD\d+$", name) and not render_node:
                render_node = f"/dev/dri/{name}"
    return drm_card, render_node


def parse_lspci(text, slots_text):
    slots = parse_slots(slots_text)
    devices = []
    for section in text.strip().split("\n\n"):
        lines = section.splitlines()
        if not lines or not re.search(r"VGA|Display controller", lines[0], re.I):
            continue
        identity = re.search(r"^([0-9a-fA-F:.]+).*\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]", lines[0])
        cap = re.search(r"LnkCap:.*Speed (\d+(?:\.\d+)?)GT/s, Width x(\d+)", section)
        sta = re.search(r"LnkSta:.*Speed (\d+(?:\.\d+)?)GT/s.*Width x(\d+)", section)
        if not identity or not cap or not sta:
            raise RuntimeError(f"required explicit PCIe link fields missing: {lines[0]}")
        bdf = identity.group(1).lower()
        bars = [int(value) * {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1, "T": 1024}[unit.upper()]
                for value, unit in re.findall(r"Region \d+:.*\[size=(\d+)([KMGT])\]", section, re.I)]
        rebar = re.search(r"BAR \d+: current size: (\d+)([MG])B", section)
        kernel_driver = re.search(r"Kernel driver in use:\s*(\S+)", section)
        rebar_gib = int(rebar.group(1)) / 1024 if rebar and rebar.group(2) == "M" else \
            int(rebar.group(1)) if rebar else 0
        drm_card, render_node = collect_drm_nodes(bdf)
        slot_width = slots.get(bdf)
        max_gen = _generation(float(cap.group(1)))
        max_width = int(cap.group(2))
        cur_gen = _generation(float(sta.group(1)))
        cur_width = int(sta.group(2))
        if slot_width is None:
            pci_dev_path = Path("/sys/bus/pci/devices") / bdf
            if pci_dev_path.exists():
                for parent in pci_dev_path.resolve().parents:
                    p_bdf = parent.name.lower()
                    if p_bdf in slots:
                        slot_width = slots[p_bdf]
                        speed_f = parent / "current_link_speed"
                        width_f = parent / "current_link_width"
                        max_s_f = parent / "max_link_speed"
                        max_w_f = parent / "max_link_width"
                        if speed_f.exists() and width_f.exists():
                            try:
                                s_val = float(re.search(r"(\d+(?:\.\d+)?)", speed_f.read_text()).group(1))
                                cur_gen = _generation(s_val)
                                cur_width = int(width_f.read_text().strip())
                            except Exception:
                                pass
                        if max_s_f.exists() and max_w_f.exists():
                            try:
                                ms_val = float(re.search(r"(\d+(?:\.\d+)?)", max_s_f.read_text()).group(1))
                                max_gen = _generation(ms_val)
                                max_width = int(max_w_f.read_text().strip())
                            except Exception:
                                pass
                        break
        devices.append({"bdf": bdf, "vendor_id": identity.group(2).lower(),
                        "device_id": identity.group(3).lower(),
                        "device_max_generation": max_gen,
                        "device_max_width": max_width,
                        "current_generation": cur_gen,
                        "current_width": cur_width, "slot_width": slot_width,
                        "bar_sizes_gib": bars, "rebar_enabled": rebar_gib >= 16,
                        "aer_counters": collect_aer(bdf),
                        "kernel_driver": kernel_driver.group(1) if kernel_driver else None,
                        "drm_card": drm_card, "render_node": render_node})
    return devices


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def parse_level_zero(text):
    if not text:
        return []
    payload = json.loads(text)
    devices = []
    for item in _walk(payload):
        bdf = next((item.get(key) for key in ("pci_bdf", "pciAddress", "bdf", "pci_bdf_address") if item.get(key)), None)
        memory = next((item.get(key) for key in ("global_memory_size", "globalMemorySize", "memory_bytes", "memory_physical_size_byte")
                       if item.get(key) is not None), None)
        uuid = next((item.get(key) for key in ("uuid", "device_uuid", "deviceUuid", "deviceUUID", "level_zero_uuid")
                     if item.get(key)), None)
        if bdf and memory is not None:
            dev = {"bdf": str(bdf).lower(), "name": item.get("name") or item.get("device_name"),
                   "memory_gib": round(int(memory) / (1024 ** 3)),
                   "memory_source": "level_zero_global_memory"}
            if uuid:
                dev["uuid"] = str(uuid)
                dev["level_zero_uuid"] = str(uuid)
            xpu_ord = item.get("device_id")
            if xpu_ord is not None:
                try:
                    dev["xpu_ordinal"] = int(xpu_ord)
                except (ValueError, TypeError):
                    pass
            devices.append(dev)
    unique = {item["bdf"]: item for item in devices}
    return [unique[bdf] for bdf in sorted(unique)]


def sys_text(name):
    path = Path("/sys/class/dmi/id") / name
    return path.read_text().strip() if path.exists() else None


def collect_iommu():
    """Read-only IOMMU state: kernel groups, DMAR devices, cmdline flags."""
    try:
        group_count = len(list(Path("/sys/kernel/iommu_groups").iterdir()))
    except OSError:
        group_count = None
    try:
        dmar_devices = sorted(path.name for path in Path("/sys/class/iommu").iterdir())
    except OSError:
        dmar_devices = []
    try:
        cmdline = Path("/proc/cmdline").read_text().split()
    except OSError:
        cmdline = []
    return {
        "kernel_iommu_groups": group_count,
        "iommu_devices": dmar_devices,
        "intel_iommu_on": "intel_iommu=on" in cmdline,
        "iommu_pt": any(param.startswith("iommu.pt=") for param in cmdline),
        "source": "sysfs+/proc/cmdline",
    }


def collect_aer(bdf):
    """Per-device PCIe AER error counters when the sysfs attributes exist."""
    counters = {}
    base = Path("/sys/bus/pci/devices") / bdf
    for name in ("aer_dev_correctable", "aer_dev_fatal", "aer_dev_nonfatal"):
        path = base / name
        if not path.exists():
            continue
        entries = {}
        try:
            for line in path.read_text().splitlines():
                fields = line.split()
                if len(fields) == 2:
                    entries[fields[0]] = int(fields[1])
        except (OSError, ValueError):
            continue
        counters[name] = entries
    if not counters:
        return {"status": "unavailable", "reason": f"no AER sysfs attributes under {bdf}"}
    return counters


def main():
    cpuinfo = Path("/proc/cpuinfo").read_text()
    memory_kib = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                          if line.startswith("MemTotal:")))
    pci = parse_lspci(run(["lspci", "-Dnnvv"]), run(["dmidecode", "--type", "slot"]))
    level_zero_raw = run(["zeinfo", "-j"], required=False)
    if not level_zero_raw.strip():
        xpu_raw = run(["xpu-smi", "discovery", "-j"], required=False)
        if xpu_raw.strip():
            try:
                disco = json.loads(xpu_raw)
                detailed = []
                for d in disco.get("device_list", []):
                    dev_id = d.get("device_id")
                    if dev_id is not None:
                        det = run(["xpu-smi", "discovery", "-d", str(dev_id), "-j"], required=False)
                        if det.strip():
                            detailed.append(json.loads(det))
                        else:
                            detailed.append(d)
                    else:
                        detailed.append(d)
                level_zero_raw = json.dumps({"devices": detailed})
            except Exception:
                pass
    level_zero = parse_level_zero(level_zero_raw)
    lsblk = json.loads(run(["lsblk", "--json", "--bytes", "-o",
                            "NAME,TYPE,SIZE,MODEL,SERIAL,WWN,REV,FSTYPE,MOUNTPOINTS"]))
    links = json.loads(run(["ip", "-json", "link", "show"]))
    dimms_text = run(["dmidecode", "--type", "memory"])
    firmware_text = run(["fwupdmgr", "get-devices", "--json"], required=False)
    psu_text = run(["dmidecode", "--type", "39"], required=False)
    level_zero_packages = run(["dpkg-query", "-W", "-f=${Package}=${Version}\\n",
                               "libze1", "libze-intel-gpu1", "intel-opencl-icd"], required=False)
    kernel_driver_version = run(["modinfo", "-F", "version", "xe"], required=False).strip()
    dimms = []
    for block in dimms_text.split("Memory Device"):
        locator, size = re.search(r"Locator:\s*(.+)", block), re.search(r"Size:\s*(.+)", block)
        if locator and size and "No Module Installed" not in size.group(1):
            dimms.append({"locator": locator.group(1).strip(), "size": size.group(1).strip()})
    level_zero_by_bdf = {item["bdf"]: item for item in level_zero if item.get("bdf")}
    gpu_records = []
    for item in pci:
        bdf = item["bdf"]
        l0_dev = level_zero_by_bdf.get(bdf, {})
        l0_uuid = l0_dev.get("level_zero_uuid") or l0_dev.get("uuid")
        xpu_ord = l0_dev.get("xpu_ordinal") if l0_dev.get("xpu_ordinal") is not None else item.get("xpu_ordinal")
        drm_card = item.get("drm_card")
        render_node = item.get("render_node")
        if drm_card is None or render_node is None:
            sys_card, sys_render = collect_drm_nodes(bdf)
            drm_card = drm_card or sys_card
            render_node = render_node or sys_render
        gpu_records.append({
            "bdf": bdf,
            "vendor_id": item["vendor_id"],
            "device_id": item["device_id"],
            "pci_bdf": bdf,
            "pci_id": f"{item['vendor_id']}:{item['device_id']}",
            "kernel_driver": item.get("kernel_driver"),
            "drm_card": drm_card,
            "render_node": render_node,
            "level_zero_uuid": l0_uuid,
            "xpu_ordinal": xpu_ord,
        })
    above_4g = {"value": None, "source": "not exposed by Linux sources",
                "confidence": "unknown"}
    for candidate_path in (Path("/var/lib/local-ai/hardware/bios_export.json"),
                           Path("/etc/local-ai/bios_export.json")):
        if candidate_path.is_file():
            try:
                data = json.loads(candidate_path.read_text())
                if "above_4g_decoding" in data:
                    above_4g = data["above_4g_decoding"]
                    break
            except Exception:
                pass
    observed = {
        "simulated": False,
        "dmi": {"manufacturer": sys_text("sys_vendor"), "product_name": sys_text("product_name"),
                "serial_number": sys_text("product_serial"), "asset_tag": sys_text("chassis_asset_tag"),
                "bios_version": sys_text("bios_version")},
        "cpu": {"model": next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines()
                                 if line.startswith("model name")), "")},
        "memory": {"total_gib": round(memory_kib / 1024 / 1024, 2), "dimms": dimms},
        "gpus": gpu_records,
        "pci": pci, "iommu": collect_iommu(), "level_zero_devices": level_zero,
        "storage": [item for item in lsblk["blockdevices"]
                    if item.get("type") == "disk" and item["name"].startswith("nvme")],
        "nics": [{"name": item.get("ifname"), "mac": item.get("address"), "mtu": item.get("mtu")}
                 for item in links if item.get("link_type") == "ether"],
        "firmware": {"bios_version": sys_text("bios_version"),
                     "above_4g_decoding": above_4g,
                     "devices": json.loads(firmware_text) if firmware_text else []},
        "power_supplies": [{"raw": block.strip()} for block in psu_text.split("System Power Supply")
                            if "Power Unit Group" in block],
        "runtime_versions": {
            "kernel": run(["uname", "-r"]).strip(),
            "kernel_driver": {"name": "xe", "version": kernel_driver_version or None},
            "level_zero_packages": sorted(line for line in level_zero_packages.splitlines() if line),
        },
    }
    print(json.dumps(observed, sort_keys=True))


if __name__ == "__main__":
    main()
