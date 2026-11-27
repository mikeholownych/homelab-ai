"""Header-only GGUF v2/v3 parser and physical byte-offset indexer for MoE routed experts.

Maps every routed expert slice (layer, expert_idx, role) to its physical shard file
offset and 4 KiB-aligned direct-I/O extent without loading or paging tensor weights.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

GGUF_MAGIC = b"GGUF"
GGUF_SUPPORTED_VERSIONS = (2, 3)
DEFAULT_GGUF_ALIGNMENT = 32
DIRECT_IO_BLOCK_SIZE = 4096
DIRECT_IO_ALIGNMENT = DIRECT_IO_BLOCK_SIZE

GGML_TYPE_F32 = 0
GGML_TYPE_F16 = 1
GGML_TYPE_Q4_0 = 2
GGML_TYPE_Q8_0 = 8
GGML_TYPE_Q4_K = 12
GGML_TYPE_Q6_K = 14
GGML_TYPE_BF16 = 30
GGML_TYPE_MXFP4 = 39

EXPERT_ROLES: tuple[str, str, str] = ("up", "gate", "down")
_ROUTED_TENSOR_RE = re.compile(r"^blk\.(\d+)\.ffn_(up|gate|down)_exps\.weight$")
_ANY_EXPERT_TENSOR_RE = re.compile(r"^blk\.(\d+)\.ffn_(up|down|gate|gate_up)_(?:ch)?exps\.")
_SHARD_NAME_RE = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$")

# GGUF metadata value type IDs (GGUF v2/v3 specification).
GGUF_TYPE_UINT8 = 0
GGUF_TYPE_INT8 = 1
GGUF_TYPE_UINT16 = 2
GGUF_TYPE_INT16 = 3
GGUF_TYPE_UINT32 = 4
GGUF_TYPE_INT32 = 5
GGUF_TYPE_FLOAT32 = 6
GGUF_TYPE_BOOL = 7
GGUF_TYPE_STRING = 8
GGUF_TYPE_ARRAY = 9
GGUF_TYPE_UINT64 = 10
GGUF_TYPE_INT64 = 11
GGUF_TYPE_FLOAT64 = 12

_SCALAR_STRUCT: dict[int, str] = {
    GGUF_TYPE_UINT8: "<B",
    GGUF_TYPE_INT8: "<b",
    GGUF_TYPE_UINT16: "<H",
    GGUF_TYPE_INT16: "<h",
    GGUF_TYPE_UINT32: "<I",
    GGUF_TYPE_INT32: "<i",
    GGUF_TYPE_FLOAT32: "<f",
    GGUF_TYPE_BOOL: "<?",
    GGUF_TYPE_UINT64: "<Q",
    GGUF_TYPE_INT64: "<q",
    GGUF_TYPE_FLOAT64: "<d",
}


@dataclass(frozen=True)
class QuantTypeSpec:
    """GGML quantization block geometry: (ggml_type_id, name, block_elements, block_bytes)."""

    type_id: int
    name: str
    block_elements: int
    block_bytes: int


# Standard GGML quantization block sizes used across dense and MoE GGUF checkpoints.
GGML_QUANT_SPECS: dict[int, QuantTypeSpec] = {
    0: QuantTypeSpec(0, "F32", 1, 4),
    1: QuantTypeSpec(1, "F16", 1, 2),
    2: QuantTypeSpec(2, "Q4_0", 32, 18),
    3: QuantTypeSpec(3, "Q4_1", 32, 20),
    6: QuantTypeSpec(6, "Q5_0", 32, 22),
    7: QuantTypeSpec(7, "Q5_1", 32, 24),
    8: QuantTypeSpec(8, "Q8_0", 32, 34),
    9: QuantTypeSpec(9, "Q8_1", 32, 36),
    10: QuantTypeSpec(10, "Q2_K", 256, 84),
    11: QuantTypeSpec(11, "Q3_K", 256, 110),
    12: QuantTypeSpec(12, "Q4_K", 256, 144),
    13: QuantTypeSpec(13, "Q5_K", 256, 176),
    14: QuantTypeSpec(14, "Q6_K", 256, 210),
    15: QuantTypeSpec(15, "Q8_K", 256, 292),
    16: QuantTypeSpec(16, "IQ2_XXS", 256, 66),
    17: QuantTypeSpec(17, "IQ2_XS", 256, 74),
    18: QuantTypeSpec(18, "IQ3_XXS", 256, 98),
    19: QuantTypeSpec(19, "IQ1_S", 256, 50),
    20: QuantTypeSpec(20, "IQ4_NL", 32, 18),
    21: QuantTypeSpec(21, "IQ3_S", 256, 110),
    22: QuantTypeSpec(22, "IQ2_S", 256, 82),
    23: QuantTypeSpec(23, "IQ4_XS", 256, 136),
    24: QuantTypeSpec(24, "I8", 1, 1),
    25: QuantTypeSpec(25, "I16", 1, 2),
    26: QuantTypeSpec(26, "I32", 1, 4),
    27: QuantTypeSpec(27, "I64", 1, 8),
    28: QuantTypeSpec(28, "F64", 1, 8),
    29: QuantTypeSpec(29, "IQ1_M", 256, 56),
    30: QuantTypeSpec(30, "BF16", 1, 2),
    39: QuantTypeSpec(39, "MXFP4", 32, 17),
}


class GGUFIndexError(ValueError):
    """Raised when a GGUF header or routed expert layout is malformed or incompatible."""


@dataclass(frozen=True)
class FileIdentity:
    """Immutable OS file identity preventing stale cache hits across file replacements."""

    path: str
    dev: int
    ino: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_path(cls, path: Path | str) -> FileIdentity:
        st = os.stat(path)
        return cls(
            path=str(Path(path).resolve()),
            dev=st.st_dev,
            ino=st.st_ino,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            ctime_ns=st.st_ctime_ns,
        )


@dataclass(frozen=True)
class DirectReadExtent:
    """Physical 4 KiB-aligned direct-I/O read window for a logical tensor slice."""

    source_idx: int
    logical_offset: int
    logical_bytes: int
    aligned_offset: int
    aligned_bytes: int
    data_offset: int


@dataclass(frozen=True)
class TensorDescriptor:
    """Parsed GGUF tensor header record."""

    name: str
    dims: tuple[int, ...]
    ggml_type: int
    relative_offset: int
    source_idx: int
    absolute_offset: int
    nbytes: int


@dataclass(frozen=True)
class ExpertRoleSpec:
    """Geometry and quantization metadata for one role (up, gate, or down) of a routed layer."""

    role: str
    ggml_type: int
    type_name: str
    columns: int
    rows: int
    row_bytes: int
    expert_bytes: int


@dataclass(frozen=True)
class ExpertLayerLayout:
    """Indexed physical extents for all experts in a single routed MoE layer."""

    layer_id: int
    n_experts: int
    roles: dict[str, ExpertRoleSpec]
    extents: dict[tuple[int, str], DirectReadExtent]

    def extent_for(self, expert_idx: int, role: str) -> DirectReadExtent:
        return self.extents[(expert_idx, role)]


@dataclass(frozen=True)
class ByteRange:
    """Half-open file byte interval [start, end) for page-cache eviction (MADV_DONTNEED)."""

    start: int
    end: int


@dataclass(frozen=True)
class MoEModelIndex:
    """Complete header-derived physical layout of a single- or multi-shard GGUF checkpoint."""

    shards: tuple[FileIdentity, ...]
    architecture: str
    n_layers: int
    n_experts: int
    n_experts_used: int
    dense_bytes: int
    routed_bytes: int
    total_tensor_bytes: int
    latent_dim: int | None
    hidden_dim: int | None
    routed_layers: dict[int, ExpertLayerLayout]
    max_role_read_bytes: dict[str, int]
    coalesced_expert_ranges: dict[int, tuple[ByteRange, ...]]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_moe(self) -> bool:
        return len(self.routed_layers) > 0 and self.n_experts > 0

    @property
    def max_expert_slot_bytes(self) -> int:
        """Page-aligned slot byte stride able to hold all three roles of the largest expert."""
        raw = sum(self.max_role_read_bytes.get(role, 0) for role in EXPERT_ROLES)
        if raw == 0:
            return 0
        return align_up(raw, DIRECT_IO_BLOCK_SIZE)


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0:
        raise ValueError("alignment must be positive")
    rem = value % alignment
    return value if rem == 0 else value + (alignment - rem)


def compute_direct_read_extent(
    source_idx: int,
    logical_offset: int,
    logical_bytes: int,
    block_size: int = DIRECT_IO_BLOCK_SIZE,
) -> DirectReadExtent:
    """Compute the minimal block-aligned direct-I/O read covering [logical_offset, logical_offset + logical_bytes)."""
    if logical_offset < 0 or logical_bytes <= 0:
        raise GGUFIndexError(f"invalid extent offset={logical_offset} bytes={logical_bytes}")
    data_offset = logical_offset % block_size
    aligned_offset = logical_offset - data_offset
    aligned_bytes = align_up(data_offset + logical_bytes, block_size)
    return DirectReadExtent(
        source_idx=source_idx,
        logical_offset=logical_offset,
        logical_bytes=logical_bytes,
        aligned_offset=aligned_offset,
        aligned_bytes=aligned_bytes,
        data_offset=data_offset,
    )


def compute_tensor_nbytes(ggml_type: int, dims: tuple[int, ...]) -> int:
    """Exact byte footprint of a contiguous GGML tensor from its quantization spec and dimensions."""
    spec = GGML_QUANT_SPECS.get(ggml_type)
    if spec is None:
        raise GGUFIndexError(f"unsupported ggml quantization type id: {ggml_type}")
    if not dims or any(d <= 0 for d in dims):
        raise GGUFIndexError(f"invalid tensor dimensions: {dims}")
    cols = dims[0]
    if cols % spec.block_elements != 0:
        raise GGUFIndexError(
            f"dimension ne[0]={cols} is not divisible by block size {spec.block_elements} for {spec.name}"
        )
    row_bytes = (cols // spec.block_elements) * spec.block_bytes
    higher = 1
    for dim in dims[1:]:
        higher *= dim
    return row_bytes * higher


def coalesce_ranges(ranges: list[ByteRange]) -> tuple[ByteRange, ...]:
    """Sort and merge overlapping or adjacent byte intervals for MADV_DONTNEED eviction."""
    valid = sorted((r for r in ranges if r.end > r.start), key=lambda r: (r.start, r.end))
    if not valid:
        return ()
    merged: list[ByteRange] = [valid[0]]
    for current in valid[1:]:
        prev = merged[-1]
        if current.start <= prev.end:
            merged[-1] = ByteRange(prev.start, max(prev.end, current.end))
        else:
            merged.append(current)
    return tuple(merged)


def discover_gguf_shards(model_path: Path | str) -> list[Path]:
    """Expand a split GGUF shard path (`*-00001-of-0000N.gguf`) into all ordered shards."""
    primary = Path(model_path)
    if not primary.is_file():
        raise FileNotFoundError(f"GGUF file not found: {primary}")
    match = _SHARD_NAME_RE.match(primary.name)
    if not match:
        return [primary]
    prefix, _idx_str, total_str = match.groups()
    total = int(total_str)
    if total <= 1:
        return [primary]
    shards: list[Path] = []
    for idx in range(1, total + 1):
        candidate = primary.parent / f"{prefix}-{idx:05d}-of-{total:05d}.gguf"
        if not candidate.is_file():
            raise FileNotFoundError(f"Missing GGUF shard {idx}/{total}: {candidate}")
        shards.append(candidate)
    return shards


def _read_exact(stream: BinaryIO, n: int) -> bytes:
    data = stream.read(n)
    if len(data) != n:
        raise GGUFIndexError(f"unexpected EOF reading GGUF header (wanted {n} bytes, got {len(data)})")
    return data


def _read_scalar(stream: BinaryIO, value_type: int) -> Any:
    fmt = _SCALAR_STRUCT.get(value_type)
    if fmt is None:
        raise GGUFIndexError(f"unsupported GGUF metadata type id: {value_type}")
    return struct.unpack(fmt, _read_exact(stream, struct.calcsize(fmt)))[0]


def _read_string(stream: BinaryIO) -> str:
    length = _read_scalar(stream, GGUF_TYPE_UINT64)
    if length > 64 * 1024 * 1024:
        raise GGUFIndexError(f"GGUF string length exceeds safety limit: {length}")
    return _read_exact(stream, length).decode("utf-8", errors="replace")


def _skip_or_read_value(stream: BinaryIO, value_type: int, *, retain_arrays: bool = False) -> Any:
    if value_type == GGUF_TYPE_STRING:
        return _read_string(stream)
    if value_type == GGUF_TYPE_ARRAY:
        elem_type = _read_scalar(stream, GGUF_TYPE_UINT32)
        count = _read_scalar(stream, GGUF_TYPE_UINT64)
        if elem_type in _SCALAR_STRUCT:
            elem_size = struct.calcsize(_SCALAR_STRUCT[elem_type])
            byte_len = count * elem_size
            if retain_arrays and count <= 256:
                raw = _read_exact(stream, byte_len)
                return [val[0] for val in struct.iter_unpack(_SCALAR_STRUCT[elem_type], raw)]
            stream.seek(byte_len, os.SEEK_CUR)
            return None
        if elem_type == GGUF_TYPE_STRING:
            out: list[str] | None = [] if (retain_arrays and count <= 256) else None
            for _ in range(count):
                s = _read_string(stream)
                if out is not None:
                    out.append(s)
            return out
        # Nested arrays are uncommon; walk sequentially.
        for _ in range(count):
            _skip_or_read_value(stream, elem_type, retain_arrays=False)
        return None
    return _read_scalar(stream, value_type)


def parse_gguf_shard_header(
    path: Path | str,
    source_idx: int = 0,
) -> tuple[FileIdentity, dict[str, Any], int, list[TensorDescriptor]]:
    """Parse one GGUF shard header without reading or mapping tensor weight payloads."""
    identity = FileIdentity.from_path(path)
    with open(path, "rb") as stream:
        magic = _read_exact(stream, 4)
        if magic != GGUF_MAGIC:
            raise GGUFIndexError(f"{path}: invalid GGUF magic {magic!r}")
        version = _read_scalar(stream, GGUF_TYPE_UINT32)
        if version not in GGUF_SUPPORTED_VERSIONS:
            raise GGUFIndexError(f"{path}: unsupported GGUF version {version}")
        n_tensors = _read_scalar(stream, GGUF_TYPE_UINT64)
        n_kv = _read_scalar(stream, GGUF_TYPE_UINT64)

        metadata: dict[str, Any] = {}
        for _ in range(n_kv):
            key = _read_string(stream)
            vtype = _read_scalar(stream, GGUF_TYPE_UINT32)
            keep_key = key.startswith("general.") or not key.startswith("tokenizer.")
            val = _skip_or_read_value(stream, vtype, retain_arrays=False)
            if keep_key and val is not None:
                metadata[key] = val

        alignment = int(metadata.get("general.alignment", DEFAULT_GGUF_ALIGNMENT))
        if alignment <= 0 or (alignment & (alignment - 1)) != 0:
            raise GGUFIndexError(f"{path}: invalid general.alignment={alignment}")

        raw_tensors: list[tuple[str, tuple[int, ...], int, int]] = []
        for _ in range(n_tensors):
            name = _read_string(stream)
            n_dims = _read_scalar(stream, GGUF_TYPE_UINT32)
            if n_dims == 0 or n_dims > 4:
                raise GGUFIndexError(f"{path}: tensor {name!r} has invalid rank {n_dims}")
            dims = tuple(int(_read_scalar(stream, GGUF_TYPE_UINT64)) for _ in range(n_dims))
            ggml_type = int(_read_scalar(stream, GGUF_TYPE_UINT32))
            rel_offset = int(_read_scalar(stream, GGUF_TYPE_UINT64))
            raw_tensors.append((name, dims, ggml_type, rel_offset))

        header_end = stream.tell()
        data_offset = align_up(header_end, alignment)

    descriptors: list[TensorDescriptor] = []
    for name, dims, ggml_type, rel_offset in raw_tensors:
        nbytes = compute_tensor_nbytes(ggml_type, dims)
        abs_offset = data_offset + rel_offset
        if abs_offset + nbytes > identity.size:
            raise GGUFIndexError(
                f"{path}: tensor {name!r} extent [{abs_offset}, {abs_offset + nbytes}) exceeds file size {identity.size}"
            )
        descriptors.append(
            TensorDescriptor(
                name=name,
                dims=dims,
                ggml_type=ggml_type,
                relative_offset=rel_offset,
                source_idx=source_idx,
                absolute_offset=abs_offset,
                nbytes=nbytes,
            )
        )
    return identity, metadata, data_offset, descriptors


def index_gguf_model(model_path: Path | str, *, block_size: int = DIRECT_IO_BLOCK_SIZE) -> MoEModelIndex:
    """Index single- or multi-shard GGUF files into a physical MoE expert extent map."""
    shard_paths = discover_gguf_shards(model_path)
    identities: list[FileIdentity] = []
    merged_meta: dict[str, Any] = {}
    all_tensors: dict[str, TensorDescriptor] = {}
    per_shard_expert_ranges: dict[int, list[ByteRange]] = {i: [] for i in range(len(shard_paths))}

    for idx, shard_path in enumerate(shard_paths):
        ident, meta, _data_offset, descriptors = parse_gguf_shard_header(shard_path, source_idx=idx)
        identities.append(ident)
        if idx == 0:
            merged_meta.update(meta)
        for desc in descriptors:
            all_tensors[desc.name] = desc

    arch = str(merged_meta.get("general.architecture", "unknown"))
    n_layers = int(merged_meta.get(f"{arch}.block_count", 0))
    n_experts = int(merged_meta.get(f"{arch}.expert_count", 0))
    n_experts_used = int(merged_meta.get(f"{arch}.expert_used_count", 0))

    total_tensor_bytes = 0
    routed_bytes = 0
    layer_role_tensors: dict[int, dict[str, TensorDescriptor]] = {}

    for desc in all_tensors.values():
        total_tensor_bytes += desc.nbytes
        if _ANY_EXPERT_TENSOR_RE.match(desc.name):
            routed_bytes += desc.nbytes
            per_shard_expert_ranges[desc.source_idx].append(
                ByteRange(desc.absolute_offset, desc.absolute_offset + desc.nbytes)
            )
        routed_match = _ROUTED_TENSOR_RE.match(desc.name)
        if routed_match:
            layer_id = int(routed_match.group(1))
            role = routed_match.group(2)
            layer_role_tensors.setdefault(layer_id, {})[role] = desc

    dense_bytes = max(0, total_tensor_bytes - routed_bytes)

    routed_layers: dict[int, ExpertLayerLayout] = {}
    max_role_read_bytes: dict[str, int] = {role: 0 for role in EXPERT_ROLES}
    latent_dim: int | None = None
    hidden_dim: int | None = None
    inferred_experts = n_experts

    for layer_id in sorted(layer_role_tensors):
        role_map = layer_role_tensors[layer_id]
        if not all(role in role_map for role in EXPERT_ROLES):
            continue

        role_specs: dict[str, ExpertRoleSpec] = {}
        for role in EXPERT_ROLES:
            desc = role_map[role]
            if len(desc.dims) != 3:
                raise GGUFIndexError(f"routed layer {layer_id} {role}: expected 3D tensor, got {desc.dims}")
            cols, rows, count = desc.dims
            spec = GGML_QUANT_SPECS[desc.ggml_type]
            row_bytes = (cols // spec.block_elements) * spec.block_bytes
            expert_bytes = row_bytes * rows
            if expert_bytes * count != desc.nbytes:
                raise GGUFIndexError(f"routed layer {layer_id} {role}: expert stride mismatch")
            role_specs[role] = ExpertRoleSpec(
                role=role,
                ggml_type=desc.ggml_type,
                type_name=spec.name,
                columns=cols,
                rows=rows,
                row_bytes=row_bytes,
                expert_bytes=expert_bytes,
            )

        up_s, gate_s, down_s = role_specs["up"], role_specs["gate"], role_specs["down"]
        up_count = role_map["up"].dims[2]
        gate_count = role_map["gate"].dims[2]
        down_count = role_map["down"].dims[2]
        if not (
            gate_s.columns == up_s.columns
            and gate_s.rows == up_s.rows
            and down_s.columns == up_s.rows
            and down_s.rows == up_s.columns
            and up_count == gate_count == down_count
        ):
            raise GGUFIndexError(
                f"routed layer {layer_id}: inconsistent up/gate/down shapes "
                f"up={role_map['up'].dims}, gate={role_map['gate'].dims}, down={role_map['down'].dims}"
            )

        if latent_dim is None:
            latent_dim = up_s.columns
            hidden_dim = up_s.rows
            inferred_experts = up_count
        elif latent_dim != up_s.columns or hidden_dim != up_s.rows or inferred_experts != up_count:
            raise GGUFIndexError(
                f"routed layer {layer_id}: geometry ({up_s.columns}, {up_s.rows}, {up_count}) "
                f"differs from first routed layer ({latent_dim}, {hidden_dim}, {inferred_experts})"
            )

        extents: dict[tuple[int, str], DirectReadExtent] = {}
        for role in EXPERT_ROLES:
            desc = role_map[role]
            eb = role_specs[role].expert_bytes
            for expert_idx in range(up_count):
                logical_off = desc.absolute_offset + expert_idx * eb
                ext = compute_direct_read_extent(desc.source_idx, logical_off, eb, block_size=block_size)
                extents[(expert_idx, role)] = ext
                if ext.aligned_bytes > max_role_read_bytes[role]:
                    max_role_read_bytes[role] = ext.aligned_bytes

        routed_layers[layer_id] = ExpertLayerLayout(
            layer_id=layer_id,
            n_experts=up_count,
            roles=role_specs,
            extents=extents,
        )

    coalesced = {idx: coalesce_ranges(rlist) for idx, rlist in per_shard_expert_ranges.items()}
    return MoEModelIndex(
        shards=tuple(identities),
        architecture=arch,
        n_layers=max(n_layers, (max(routed_layers) + 1) if routed_layers else 0),
        n_experts=inferred_experts,
        n_experts_used=n_experts_used,
        dense_bytes=dense_bytes,
        routed_bytes=routed_bytes,
        total_tensor_bytes=total_tensor_bytes,
        latent_dim=latent_dim,
        hidden_dim=hidden_dim,
        routed_layers=routed_layers,
        max_role_read_bytes=max_role_read_bytes,
        coalesced_expert_ranges=coalesced,
        metadata=merged_meta,
    )
