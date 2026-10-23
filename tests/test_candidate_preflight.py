import importlib.util
import struct
from pathlib import Path

import pytest


def inspector():
    path = Path(__file__).parents[1] / "evaluations/engx/candidate_preflight.py"
    spec = importlib.util.spec_from_file_location("candidate_preflight", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.inspect_gguf


def string(value):
    encoded = value.encode()
    return struct.pack("<Q", len(encoded)) + encoded


def test_gguf_preflight_reads_metadata_without_tensor_data(tmp_path):
    path = tmp_path / "model.gguf"
    header = b"GGUF" + struct.pack("<IQQ", 3, 1, 1)
    header += string("general.architecture") + struct.pack("<I", 8) + string("fixture")
    header += string("mtp.fixture.weight") + struct.pack("<I", 1) + struct.pack("<QIQ", 16, 12, 0)
    path.write_bytes(header)  # Deliberately no weight payload.
    result = inspector()(path)
    assert result["metadata"]["general.architecture"] == "fixture"
    assert result["mtp_named_tensor_count"] == 1
    assert result["header_bytes_inspected"] == len(header)


@pytest.mark.parametrize("data", [b"bad!", b"GGUF" + struct.pack("<IQQ", 3, 100001, 0)])
def test_gguf_preflight_rejects_invalid_or_excessive_headers(tmp_path, data):
    path = tmp_path / "model.gguf"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        inspector()(path)
