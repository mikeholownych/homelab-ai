"""Appliance-local verifier, executed only through Ansible; emit no credentials."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import uuid


def main():
    inputs = json.load(sys.stdin)
    base = "http://127.0.0.1:" + str(inputs["gateway_port"])
    qualification = Path("/etc/local-ai/orchestrator/clients/qualification.token").read_text().strip()

    def request(path, key=qualification, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "Cache-Control": "no-store", "X-AIHost-Cache": "bypass", "X-AIHost-Reasoning": "off"})
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)

    services = {}
    for worker in inputs["workers"].values():
        output = subprocess.check_output(["systemctl", "show", worker["service_name"],
            "--property=ActiveState,SubState,MainPID,NRestarts,ActiveEnterTimestamp,ExecMainStartTimestamp"], text=True)
        state = dict(line.split("=", 1) for line in output.splitlines())
        assert state["ActiveState"] == "active" and int(state["MainPID"]) > 0, worker["service_name"]
        services[worker["service_name"]] = state
    candidates = subprocess.check_output(["systemctl", "list-units", "--all", "--plain", "--no-legend",
                                          "aihost-llama-candidate*.service"], text=True)
    assert not any(" running " in line or " activating " in line for line in candidates.splitlines()), candidates
    health = request("/health?strict=true")
    assert health["scheduler"]["available_workers"] == len(inputs["workers"]), health["scheduler"]
    assert health["scheduler"]["configured_workers"] == len(inputs["workers"])
    registry_digest = hashlib.sha256(Path("/etc/local-ai/orchestrator/clients.json").read_bytes()).hexdigest()
    gateway = subprocess.check_output(["systemctl", "show", "aihost-orchestrator-gateway.service",
                                       "--property=ActiveState,WorkingDirectory"], text=True)
    assert "ActiveState=active" in gateway
    expected_release = inputs["gateway_release"]
    assert "WorkingDirectory=" + expected_release in gateway
    before = inputs.get("baseline")
    if before:
        assert before["registry_sha256"] == registry_digest, "client registry changed"
        for name, state in services.items():
            if name != inputs["replaced_service"]:
                assert state == before["services"][name], "unaffected worker changed"
        assert before["kernel"] == subprocess.check_output(["uname", "-r"], text=True).strip()
    print(json.dumps({"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "services": services, "gateway_release": expected_release,
        "registry_sha256": registry_digest, "scheduler": health["scheduler"],
        "kernel": subprocess.check_output(["uname", "-r"], text=True).strip(),
        "appliance_verified": True}, sort_keys=True))


if __name__ == "__main__":
    main()
