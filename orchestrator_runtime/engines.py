"""Engine adapters: what a worker really is, what it can hold, and exactly how many tokens a request costs.

The gateway owns admission and sizing, so it needs the worker's *observed* identity and limits rather than the
numbers someone typed into the inventory. Every call here is read-only and bounded (it never generates): llama.cpp
answers `/props`, `/apply-template` and `/tokenize`; vLLM answers `/v1/models`, `/version` and `/tokenize`.
A failed observation is reported as None (unknown), never as a fabricated value; callers fail closed on unknown.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# Request fields that change the rendered prompt (and therefore the token count). Sampling parameters do not.
_TEMPLATE_FIELDS = ("messages", "tools", "tool_choice", "parallel_tool_calls", "chat_template_kwargs", "response_format")


@dataclass(frozen=True)
class EngineObservation:
    engine: str
    engine_version: str | None
    model_path: str | None
    model_alias: str | None
    quantization: str | None
    ctx_per_slot: int | None
    slots_total: int | None
    declared: dict[str, bool] = field(default_factory=dict)
    observed_at: float = 0.0

    def limits_tuple(self) -> tuple[Any, ...]:
        return (self.engine, self.engine_version, self.model_path, self.model_alias, self.quantization,
                self.ctx_per_slot, self.slots_total, tuple(sorted(self.declared.items())))


class EngineAdapter:
    """Base adapter: an engine it does not know is observed as nothing (callers fall back to fail-closed rules)."""

    engine = "unknown"

    def __init__(self, endpoint: str, token: str = "", timeout: float = 3.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str) -> Any:
        request = urllib.request.Request(self.endpoint + path, headers=self._headers(), method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read(4 * 1024 * 1024).decode())

    def _post(self, path: str, body: dict[str, Any], timeout: float | None = None) -> Any:
        request = urllib.request.Request(self.endpoint + path, json.dumps(body).encode(), headers=self._headers(), method="POST")
        with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
            return json.loads(response.read(64 * 1024 * 1024).decode())

    def observe(self) -> EngineObservation | None:
        return None

    def count_prompt(self, request: dict[str, Any]) -> int | None:
        return None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


class LlamaCppAdapter(EngineAdapter):
    engine = "llama.cpp"

    def observe(self) -> EngineObservation | None:
        try:
            props = self._get("/props")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None
        return self.parse_props(props)

    @staticmethod
    def parse_props(props: Any) -> EngineObservation | None:
        if not isinstance(props, dict):
            return None
        settings = props.get("default_generation_settings") or {}
        caps = props.get("chat_template_caps") or {}
        modalities = props.get("modalities") or {}
        declared = {
            "tools": bool(caps.get("supports_tool_calls") or caps.get("supports_tools")),
            "parallel_tool_calls": bool(caps.get("supports_parallel_tool_calls")),
            "vision": bool(modalities.get("vision")),
            # llama.cpp constrains output to response_format json_schema / json_object through its grammar engine.
            "structured_output": True,
            "reasoning": bool(caps.get("supports_reasoning_effort") or caps.get("supports_preserve_reasoning")),
        }
        return EngineObservation(
            engine="llama.cpp",
            engine_version=str(props.get("build_info")) if props.get("build_info") else None,
            model_path=props.get("model_path"),
            model_alias=props.get("model_alias"),
            quantization=props.get("model_ftype"),
            # Current llama.cpp reports nested defaults; older builds and lightweight /props implementations
            # expose n_ctx directly. Both are observations from the server, not inventory fallbacks.
            ctx_per_slot=_int(settings.get("n_ctx") or props.get("n_ctx")),
            slots_total=_int(props.get("total_slots")),
            declared=declared,
            observed_at=time.time(),
        )

    def count_prompt(self, request: dict[str, Any]) -> int | None:
        """Exact prompt tokens: render the request with the worker's own chat template, then tokenize the result."""
        body = {key: request[key] for key in _TEMPLATE_FIELDS if key in request}
        try:
            rendered = self._post("/apply-template", body, timeout=10.0)
            prompt = rendered.get("prompt") if isinstance(rendered, dict) else None
            if not isinstance(prompt, str):
                return None
            tokens = self._post("/tokenize", {"content": prompt, "add_special": True, "parse_special": True}, timeout=10.0)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None
        ids = tokens.get("tokens") if isinstance(tokens, dict) else None
        return len(ids) if isinstance(ids, list) else None


class VllmAdapter(EngineAdapter):
    engine = "vllm"

    def observe(self) -> EngineObservation | None:
        try:
            models = self._get("/v1/models")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None
        try:
            version = self._get("/version")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            version = {}
        return self.parse(models, version)

    @staticmethod
    def parse(models: Any, version: Any) -> EngineObservation | None:
        data = (models or {}).get("data") if isinstance(models, dict) else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return None
        entry = data[0]
        return EngineObservation(
            engine="vllm",
            engine_version=(version or {}).get("version") if isinstance(version, dict) else None,
            model_path=entry.get("root"),
            model_alias=entry.get("id"),
            quantization=None,
            ctx_per_slot=_int(entry.get("max_model_len")),
            # vLLM batches continuously and does not publish a slot count; the inventory declares concurrency.
            slots_total=None,
            declared={"structured_output": True},
            observed_at=time.time(),
        )

    def count_prompt(self, request: dict[str, Any]) -> int | None:
        body = {key: request[key] for key in ("messages", "tools", "chat_template_kwargs") if key in request}
        body["model"] = request.get("model")
        body["add_generation_prompt"] = True
        try:
            counted = self._post("/tokenize", body, timeout=10.0)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None
        return _int(counted.get("count")) if isinstance(counted, dict) else None


_ADAPTERS: dict[str, type[EngineAdapter]] = {"llama.cpp": LlamaCppAdapter, "vllm": VllmAdapter}


def adapter_for(engine: str, endpoint: str | None, token: str | None) -> EngineAdapter | None:
    cls = _ADAPTERS.get(engine)
    if cls is None or not endpoint:
        return None
    return cls(endpoint, token or "")
