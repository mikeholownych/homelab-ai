"""The llama worker unit renders optional per-worker environment variables and is unchanged without them."""
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")
TEMPLATE = Path(__file__).resolve().parents[1] / "roles/llama_cpp_container/templates/llama-worker.service.j2"


def render(worker, slot_persistence=False):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, lstrip_blocks=False)
    return env.from_string(TEMPLATE.read_text()).render(
        llama_worker=worker,
        llama_cpp_container_uid=999, llama_cpp_container_user="aihost-runtime", llama_cpp_container_home="/h",
        llama_cpp_container_model_dir="/m", llama_cpp_container_image="img", llama_cpp_container_digest="sha256:" + "0" * 64,
        llama_cpp_container_host="127.0.0.1", llama_cpp_container_default_args=["-ngl", "99"],
        llama_cpp_container_reasoning_budget_message="m", llama_cpp_container_log_dir="/l",
        llama_cpp_container_slot_persistence=slot_persistence, llama_cpp_container_slot_dir="/h/slots",
    )


BASE = {"worker_id": 1, "container_name": "c", "gpu": 0, "config_dir": "/c", "model_file": "a.gguf",
        "context": 65536, "port": 8000, "served_name": "n"}


def test_no_env_adds_no_extra_flags():
    out = render(BASE)
    assert out.count(" -e ") == 3 and "XMX_ESIMD" not in out


def test_env_rendered_per_worker():
    out = render({**BASE, "env": {"GGML_SYCL_ENABLE_XMX_ESIMD": 0}})
    assert "-e GGML_SYCL_ENABLE_XMX_ESIMD=0 \\" in out
    assert out.index("XMX_ESIMD") < out.index("-v /dev/dri/by-path")


def test_slot_persistence_adds_a_private_mount_and_the_flag_only_when_enabled():
    off, on = render(BASE), render(BASE, slot_persistence=True)
    assert "--slot-save-path" not in off and "/slots" not in off
    assert "-v /h/slots/1:/slots:rw \\" in on and "--slot-save-path /slots \\" in on
    assert on.index("/slots:rw") < on.index("--slot-save-path")           # the mount precedes the image; the flag is a server argument
    assert render(BASE, slot_persistence="false") == off                    # a string from -e is not enabling it
