"""R4 candidate swaps restore production capacity when they fail part-way (2026-10-10: the lead pool stayed down)."""
from pathlib import Path

import yaml

PLAY = yaml.safe_load((Path(__file__).resolve().parents[1] / "playbooks/candidate.yml").read_text())[0]


def test_production_configuration_is_remembered_before_the_merge_and_restored_on_failure():
    names = [t["name"] for t in PLAY["pre_tasks"]]
    assert names.index("Remember the production configuration (restored if the swap fails part-way)") < names.index(
        "Merge the candidate into the worker and gateway configuration")
    remembered = set(PLAY["pre_tasks"][names.index("Remember the production configuration (restored if the swap fails "
                                                   "part-way)")]["ansible.builtin.set_fact"]["_candidate_production"])
    merged = set(PLAY["pre_tasks"][names.index("Merge the candidate into the worker and gateway configuration")]
                 ["ansible.builtin.set_fact"])
    assert remembered == merged  # everything the merge changes is restorable

    swap = PLAY["tasks"][0]
    assert "roles" not in PLAY and [t["ansible.builtin.include_role"]["name"] for t in swap["block"]
                                    if "ansible.builtin.include_role" in t] == [
        "inference_policy", "llama_cpp_container", "orchestrator_gateway"]
    rescue = swap["rescue"]
    restored = set(rescue[0]["ansible.builtin.set_fact"]) - {"_candidate_failed_task"}
    assert restored == merged
    assert [t["ansible.builtin.include_role"]["name"] for t in rescue if "ansible.builtin.include_role" in t] == [
        "llama_cpp_container", "orchestrator_gateway"]
    assert "ansible.builtin.fail" in rescue[-1]  # the run still fails: a restored abort is not a success
