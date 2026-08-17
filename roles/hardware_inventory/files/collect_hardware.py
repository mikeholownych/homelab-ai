#!/usr/bin/env python3
"""Collect a non-mutating Linux hardware snapshot from standard interfaces."""

import json
import re
import subprocess
from pathlib import Path


def run(command, required=True):
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        if required:
            raise RuntimeError(f"required hardware source failed: {' '.join(command)}: {error}") from error
        return ""


def sys_text(name):
    path = Path("/sys/class/dmi/id") / name
    return path.read_text().strip() if path.exists() else None


def main():
    cpuinfo = Path("/proc/cpuinfo").read_text()
    model = next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines() if line.startswith("model name")), "")
    memory_kib = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                          if line.startswith("MemTotal:")))
    lspci = run(["lspci", "-Dnnvv"])
    lsblk = json.loads(run(["lsblk", "--json", "--bytes", "-o",
                            "NAME,TYPE,SIZE,MODEL,SERIAL,WWN,REV,FSTYPE,MOUNTPOINTS"]))
    links = json.loads(run(["ip", "-json", "link", "show"]))
    dimms_text = run(["dmidecode", "--type", "memory"])
    slots_text = run(["dmidecode", "--type", "slot"])
    psu_text = run(["dmidecode", "--type", "39"], required=False)
    firmware_text = run(["fwupdmgr", "get-devices", "--json"], required=False)
    ze_text = run(["zeinfo", "-j"], required=False)
    gpu_sections = [section for section in lspci.split("\n\n") if re.search(r"VGA|Display controller", section, re.I)
                    and "Intel" in section]
    gpus, pci = [], []
    slot_widths = {}
    for slot in slots_text.split("Handle "):
        address_match = re.search(r"Bus Address:\s*([0-9a-fA-F:.]+)", slot)
        width_match = re.search(r"Type:\s*PCI Express.*?x(\d+)", slot, re.S)
        if address_match and width_match:
            slot_widths[address_match.group(1).lower()] = int(width_match.group(1))
    for section in gpu_sections:
        first = section.splitlines()[0]
        address = first.split()[0]
        widths = re.findall(r"Width x(\d+)", section)
        speeds = re.findall(r"Speed (\d+(?:\.\d+)?)GT/s", section)
        bars = []
        for value, unit in re.findall(r"size=(\d+)([KMGTP])", section, re.I):
            bars.append(int(value) * (1024 ** {"K": 1, "M": 2, "G": 3, "T": 4, "P": 5}[unit.upper()]) /
                        (1024 ** 3))
        pci_id = (re.findall(r"\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]", first) or [""])[-1]
        def generation(speed):
            return 5 if speed >= 32 else 4 if speed >= 16 else 3 if speed >= 8 else 2 if speed >= 5 else 1
        max_gen = generation(float(speeds[0])) if speeds else None
        current_gen = generation(float(speeds[-1])) if speeds else None
        pci.append({"address": address, "slot_width": slot_widths.get(address.lower()),
                    "device_max_width": int(widths[0]) if widths else None,
                    "current_width": int(widths[-1]) if widths else None, "max_generation": max_gen,
                    "current_generation": current_gen, "bar_gib": max(bars, default=0),
                    "rebar_enabled": max(bars, default=0) >= 16})
        gpus.append({"model": first, "pci_id": pci_id, "memory_gib": max(bars, default=0),
                     "level_zero": address in ze_text or bool(ze_text and len(gpu_sections) == 1)})
    dimms = []
    for device in dimms_text.split("Memory Device"):
        locator = re.search(r"Locator:\s*(.+)", device)
        size = re.search(r"Size:\s*(.+)", device)
        if locator and size and "No Module Installed" not in size.group(1):
            dimms.append({"locator": locator.group(1).strip(), "size": size.group(1).strip()})
    disks = [item for item in lsblk["blockdevices"] if item.get("type") == "disk" and item["name"].startswith("nvme")]
    observed = {
        "simulated": False,
        "dmi": {"manufacturer": sys_text("sys_vendor"), "product_name": sys_text("product_name"),
                "serial_number": sys_text("product_serial"), "asset_tag": sys_text("chassis_asset_tag"),
                "bios_version": sys_text("bios_version")},
        "cpu": {"model": model, "sockets": len(set(re.findall(r"physical id\s*:\s*(\d+)", cpuinfo))) or 1},
        "memory": {"total_gib": round(memory_kib / 1024 / 1024, 2), "dimms": dimms},
        "gpus": gpus, "pci": pci, "storage": disks,
        "nics": [{"name": item.get("ifname"), "mac": item.get("address"), "mtu": item.get("mtu"),
                  "speed_mbps": (Path("/sys/class/net") / item.get("ifname", "") / "speed").read_text().strip()
                  if (Path("/sys/class/net") / item.get("ifname", "") / "speed").exists() else None}
                 for item in links if item.get("link_type") == "ether"],
        "firmware": {"bios_version": sys_text("bios_version"),
                     "above_4g_decoding": len(pci) > 0 and all(item["bar_gib"] >= 16 for item in pci),
                     "above_4g_source": "derived from allocated GPU BAR sizes",
                     "devices": json.loads(firmware_text) if firmware_text else []},
        "power_supplies": [{"raw": block.strip()} for block in psu_text.split("System Power Supply")
                           if "Power Unit Group" in block]
    }
    print(json.dumps(observed, sort_keys=True))


if __name__ == "__main__":
    main()
