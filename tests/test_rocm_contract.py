from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def test_rocm_defaults_are_fail_closed_and_pinned():
    d = load("roles/rocm/defaults/main.yml")
    assert d["rocm_install_enabled"] is False
    assert d["rocm_release"] == "7.2.0"
    assert d["rocm_apt_suite"] == "noble"
    assert d["rocm_signing_key_sha256"] == (
        "3e660bdc559b34781b5498e79b9c117394b46ce55592812db0b84d65986b4df2"
    )
    assert d["rocm_signing_key_fingerprint"] == "CA8BB4727A47B4D09B4EE8969386B48A1A693C5C"
    assert d["rocm_packages"]["rocm-core"] == "7.2.0.70200-43~24.04"
    assert d["rocm_packages"]["rocminfo"] == "1.0.0.70200-43~24.04"
    assert d["rocm_expected_gpu_agent"] == "gfx1151"
    assert d["rocm_expected_npu_agent"] == "aie2p"
    assert "latest" not in d["rocm_repository_urls"]["rocm"]

def test_rocm_main_includes_task_graph_when_enabled():
    tasks = load("roles/rocm/tasks/main.yml")
    by_file = {t["ansible.builtin.include_tasks"]: t["when"] for t in tasks}
    assert list(by_file) == [
        "preflight.yml",
        "repos.yml",
        "packages.yml",
        "access.yml",
        "validate.yml",
    ]
    for name in ("preflight.yml", "repos.yml", "packages.yml", "access.yml"):
        assert by_file[name] == "rocm_install_enabled | bool"
    assert by_file["validate.yml"] == ["rocm_install_enabled | bool", "not ansible_check_mode"]
    for name in by_file:
        assert (ROOT / "roles/rocm/tasks" / name).is_file()


def test_rocm_templates_pin_noble_and_7_2_paths():
    rocm_list = (ROOT / "roles/rocm/templates/rocm.list.j2").read_text()
    amdgpu_list = (ROOT / "roles/rocm/templates/amdgpu.list.j2").read_text()
    d = load("roles/rocm/defaults/main.yml")
    assert "latest" not in rocm_list + amdgpu_list
    assert "{{ rocm_repository_urls.rocm }} {{ rocm_apt_suite }} main" in rocm_list
    assert "[arch=amd64 signed-by={{ rocm_keyring_path }}]" in rocm_list
    assert "{{ rocm_repository_urls.graphics }} {{ rocm_apt_suite }} main" in amdgpu_list
    assert "{{ rocm_repository_urls.amdgpu }} {{ rocm_apt_suite }} main" in amdgpu_list
    assert amdgpu_list.count("[arch=amd64,i386 signed-by={{ rocm_keyring_path }}]") == 2
    assert d["rocm_apt_suite"] == "noble"
    assert d["rocm_repository_urls"]["rocm"].endswith("/rocm/apt/7.2")
    assert d["rocm_repository_urls"]["graphics"].endswith("/graphics/7.2/ubuntu")
    assert d["rocm_repository_urls"]["amdgpu"].endswith("/amdgpu/30.30/ubuntu")
    assert all("latest" not in url for url in d["rocm_repository_urls"].values())


def test_rocm_task_files_are_valid_yaml_with_gates():
    for name in ("preflight", "repos", "packages", "access", "validate"):
        assert isinstance(load(f"roles/rocm/tasks/{name}.yml"), list)
    repos = (ROOT / "roles/rocm/tasks/repos.yml").read_text()
    assert "rocm_signing_key_sha256" in repos and "rocm_signing_key_fingerprint" in repos
    validate = (ROOT / "roles/rocm/tasks/validate.yml").read_text()
    for needle in ("rocminfo", "rocm-smi", "rocm_npu_module", "rocm_npu_device_node", "physical_acceptance"):
        assert needle in validate


def test_rocm_templates_render_live_working_lines():
    import jinja2

    d = load("roles/rocm/defaults/main.yml")
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    ctx = {k: v for k, v in d.items() if not k.startswith("host_")}
    lines = []
    for name in ("rocm.list.j2", "amdgpu.list.j2"):
        text = env.from_string((ROOT / "roles/rocm/templates" / name).read_text()).render(**ctx)
        lines += [ln for ln in text.splitlines() if ln.startswith("deb ")]
    k = d["rocm_keyring_path"]
    assert lines == [
        f"deb [arch=amd64 signed-by={k}] https://repo.radeon.com/rocm/apt/7.2 noble main",
        f"deb [arch=amd64,i386 signed-by={k}] https://repo.radeon.com/graphics/7.2/ubuntu noble main",
        f"deb [arch=amd64,i386 signed-by={k}] https://repo.radeon.com/amdgpu/30.30/ubuntu noble main",
    ]


def test_site_includes_rocm_role_gated_and_excludes_intel_when_rocm_enabled():
    tasks = [t for play in load("playbooks/site.yml") for t in play.get("tasks", [])]
    rocm = next(t for t in tasks if t.get("ansible.builtin.include_role", {}).get("name") == "rocm")
    assert rocm["when"] == "rocm_install_enabled | default(false) | bool"
    assert "rocm" in rocm["tags"]
    intel = next(t for t in tasks if t.get("ansible.builtin.include_role", {}).get("name") == "intel_gpu")
    assert "not (rocm_install_enabled | default(false) | bool)" in intel["when"]


def test_commission_does_not_force_omix_when_rocm_enabled():
    plays = load("playbooks/commission.yml")
    phase5 = next(p for p in plays if p["name"].startswith("Phase 5:"))
    intel = next(t for t in phase5["tasks"] if t.get("ansible.builtin.include_role", {}).get("name") == "intel_gpu")
    assert intel["vars"] == {"intel_gpu_install_enabled": True}
    assert "not (rocm_install_enabled | default(false) | bool)" in intel["when"]


def test_commission_has_rocm_phase_5b_with_deferred_engines():
    plays = load("playbooks/commission.yml")
    phase5b = next(p for p in plays if p["name"].startswith("Phase 5b:"))
    assert phase5b["tags"] == ["rocm"]
    include = next(t for t in phase5b["tasks"] if t.get("ansible.builtin.include_role", {}).get("name") == "rocm")
    assert include["when"] == "rocm_install_enabled | default(false) | bool"
    text = (ROOT / "playbooks/commission.yml").read_text()
    assert "checkpoints/rocm.json" in text
    assert "'engines_deferred': true" in text
    names = [p["name"] for p in plays]
    assert names.index(phase5b["name"]) < next(i for i, n in enumerate(names) if n.startswith("Phase 6:"))


def test_commission_omix_checkpoint_tasks_skip_on_rocm_hosts():
    plays = load("playbooks/commission.yml")
    phase5 = next(p for p in plays if p["name"].startswith("Phase 5:"))
    guard = "not (rocm_install_enabled | default(false) | bool)"
    gated = [
        t for t in phase5["tasks"]
        if "ansible.builtin.include_role" not in t
    ]
    assert len(gated) == 5
    for task in gated:
        assert guard in task["when"], task["name"]
    persist = next(t for t in gated if t["name"] == "Persist OMIX evidence checkpoint")
    assert persist["ansible.builtin.copy"]["dest"].endswith("checkpoints/omix.json")
