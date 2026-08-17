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
        width = re.search(r"Type:\s*x?(\d+) PCI Express", block)
        if bdf and width:
            slots[bdf.group(1).lower()] = int(width.group(1))
    return slots


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
        rebar_gib = int(rebar.group(1)) / 1024 if rebar and rebar.group(2) == "M" else \
            int(rebar.group(1)) if rebar else 0
        devices.append({"bdf": bdf, "vendor_id": identity.group(2).lower(),
                        "device_id": identity.group(3).lower(),
                        "device_max_generation": _generation(float(cap.group(1))),
                        "device_max_width": int(cap.group(2)),
                        "current_generation": _generation(float(sta.group(1))),
                        "current_width": int(sta.group(2)), "slot_width": slots.get(bdf),
                        "bar_sizes_gib": bars, "rebar_enabled": rebar_gib >= 16})
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
        bdf = next((item.get(key) for key in ("pci_bdf", "pciAddress", "bdf") if item.get(key)), None)
        memory = next((item.get(key) for key in ("global_memory_size", "globalMemorySize", "memory_bytes")
                       if item.get(key) is not None), None)
        if bdf and memory is not None:
            devices.append({"bdf": str(bdf).lower(), "name": item.get("name"),
                            "memory_gib": int(memory) / (1024 ** 3),
                            "memory_source": "level_zero_global_memory"})
    unique = {item["bdf"]: item for item in devices}
    return [unique[bdf] for bdf in sorted(unique)]


def sys_text(name):
    path = Path("/sys/class/dmi/id") / name
    return path.read_text().strip() if path.exists() else None


def main():
    cpuinfo = Path("/proc/cpuinfo").read_text()
    memory_kib = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                          if line.startswith("MemTotal:")))
    pci = parse_lspci(run(["lspci", "-Dnnvv"]), run(["dmidecode", "--type", "slot"]))
    level_zero = parse_level_zero(run(["zeinfo", "-j"], required=False))
    lsblk = json.loads(run(["lsblk", "--json", "--bytes", "-o",
                            "NAME,TYPE,SIZE,MODEL,SERIAL,WWN,REV,FSTYPE,MOUNTPOINTS"]))
    links = json.loads(run(["ip", "-json", "link", "show"]))
    dimms_text = run(["dmidecode", "--type", "memory"])
    firmware_text = run(["fwupdmgr", "get-devices", "--json"], required=False)
    psu_text = run(["dmidecode", "--type", "39"], required=False)
    dimms = []
    for block in dimms_text.split("Memory Device"):
        locator, size = re.search(r"Locator:\s*(.+)", block), re.search(r"Size:\s*(.+)", block)
        if locator and size and "No Module Installed" not in size.group(1):
            dimms.append({"locator": locator.group(1).strip(), "size": size.group(1).strip()})
    observed = {
        "simulated": False,
        "dmi": {"manufacturer": sys_text("sys_vendor"), "product_name": sys_text("product_name"),
                "serial_number": sys_text("product_serial"), "asset_tag": sys_text("chassis_asset_tag"),
                "bios_version": sys_text("bios_version")},
        "cpu": {"model": next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines()
                                 if line.startswith("model name")), "")},
        "memory": {"total_gib": round(memory_kib / 1024 / 1024, 2), "dimms": dimms},
        "gpus": [{key: item[key] for key in ("bdf", "vendor_id", "device_id")} for item in pci],
        "pci": pci, "level_zero_devices": level_zero,
        "storage": [item for item in lsblk["blockdevices"]
                    if item.get("type") == "disk" and item["name"].startswith("nvme")],
        "nics": [{"name": item.get("ifname"), "mac": item.get("address"), "mtu": item.get("mtu")}
                 for item in links if item.get("link_type") == "ether"],
        "firmware": {"bios_version": sys_text("bios_version"),
                     "above_4g_decoding": {"value": None, "source": "not exposed by Linux sources",
                                            "confidence": "unknown"},
                     "devices": json.loads(firmware_text) if firmware_text else []},
        "power_supplies": [{"raw": block.strip()} for block in psu_text.split("System Power Supply")
                           if "Power Unit Group" in block],
    }
    print(json.dumps(observed, sort_keys=True))


if __name__ == "__main__":
    main()
