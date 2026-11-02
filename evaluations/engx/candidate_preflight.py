#!/usr/bin/env python3
"""Read GGUF metadata and local configuration availability; never load tensor data."""
import argparse
import hashlib
import json
import shutil
import struct
from collections import Counter
from pathlib import Path


def inspect_gguf(path):
    with path.open("rb") as stream:
        def read(size):
            if stream.tell() + size > 128 * 1024 * 1024:
                raise ValueError("GGUF header exceeds inspection bound")
            data = stream.read(size)
            if len(data) != size:
                raise ValueError("Truncated GGUF metadata")
            return data

        def number(fmt):
            return struct.unpack("<" + fmt, read(struct.calcsize(fmt)))[0]

        def string():
            size = number("Q")
            return read(size).decode("utf-8")

        def value(kind, depth=0):
            if depth > 4:
                raise ValueError("Unexpected nested metadata")
            formats = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
            if kind in formats:
                return number(formats[kind])
            if kind == 8:
                return string()
            if kind == 9:
                subtype, count = number("I"), number("Q")
                if count > 2_000_000:
                    raise ValueError("Metadata array exceeds inspection bound")
                for _ in range(count):
                    value(subtype, depth + 1)
                return {"array_length": count}
            raise ValueError("Unknown GGUF metadata type")

        if read(4) != b"GGUF" or number("I") not in (2, 3):
            raise ValueError("Expected GGUF v2/v3")
        tensors, keys = number("Q"), number("Q")
        if tensors > 100_000 or keys > 100_000:
            raise ValueError("GGUF item count exceeds inspection bound")
        metadata = {}
        for _ in range(keys):
            name, kind = string(), number("I")
            item = value(kind)
            if name in ("general.architecture", "general.name") or name.endswith(".context_length"):
                metadata[name] = item
        mtp, types = [], Counter()
        for _ in range(tensors):
            name, dimensions = string(), number("I")
            if dimensions > 8:
                raise ValueError("Unexpected tensor rank")
            for _ in range(dimensions):
                number("Q")
            types[number("I")] += 1
            number("Q")
            if "mtp" in name.lower() or "nextn" in name.lower():
                mtp.append(name)
        return {"metadata": metadata, "tensor_count": tensors, "tensor_type_counts": dict(types),
                "mtp_named_tensor_count": len(mtp), "header_bytes_inspected": stream.tell()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--config-root", required=True, type=Path)
    args = parser.parse_args()
    before = args.model.stat()
    result = inspect_gguf(args.model)
    after = args.model.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)
    configs = []
    for config in args.config_root.glob("**/config.json"):
        if len(configs) >= 100:
            break
        data = config.read_bytes()
        if len(data) > 1024 * 1024:
            continue
        try:
            parsed = json.loads(data)
        except ValueError:
            continue
        configs.append({"path": str(config), "sha256": hashlib.sha256(data).hexdigest(),
                        "architectures": parsed.get("architectures"), "model_type": parsed.get("model_type"),
                        "tokenizer_json_present": (config.parent / "tokenizer.json").exists(),
                        "safetensors_index_present": (config.parent / "model.safetensors.index.json").exists()})
    result.update(model_path=str(args.model), bytes=after.st_size, mtime_ns=after.st_mtime_ns,
                  config_candidates=configs,
                  available_host_memory=[line.strip() for line in Path("/proc/meminfo").read_text().splitlines()
                                         if line.startswith("MemAvailable:")],
                  container_filesystem_free_bytes=shutil.disk_usage("/var/lib/aihost-runtime").free,
                  gpu_execution_performed=False,
                  limitation="Config presence and MTP-like tensor names do not establish matching tokenizer or backend support")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
