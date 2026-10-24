"""Controller-only authenticated TLS production verification; secrets on stdin."""
import json
import hashlib
import ssl
import sys
import urllib.request


def main():
    inputs = json.load(sys.stdin)
    context = ssl.create_default_context(cafile=inputs["ca"])

    def request(path, key, body=None):
        req = urllib.request.Request(inputs["base"] + path,
            json.dumps(body).encode() if body is not None else None,
            {"Authorization": "Bearer " + key, "Content-Type": "application/json",
             "Cache-Control": "no-store", "X-AIHost-Cache": "bypass", "X-AIHost-Reasoning": "off"})
        with urllib.request.urlopen(req, context=context, timeout=120) as response:
            return json.load(response)
    models = request("/v1/models", inputs["qualification"])["data"]
    ids = [model["id"] for model in models]
    assert not any(model.startswith("candidate/") for model in ids), ids
    workers = request("/admin/workers", inputs["admin"])["workers"]
    assert set(workers) == set(inputs["worker_ids"]), list(workers)
    assert all(w.get("drain", {}).get("state") != "drained" for w in workers.values())
    completions = []
    probe_id = inputs["probe_id"]
    for model in ["engineering/lead", "engineering/deep"]:
        assert model in ids, ids
        payload = {
            "model": model, "cache": False, "messages": [
                {"role": "system", "content": "Reply with exactly READY."},
                {"role": "user", "content": "Recovery verifier " + probe_id + ". Reply with exactly READY."}],
            "temperature": 0, "max_tokens": 128, "grammar": 'root ::= "READY"'}
        response = request("/v1/chat/completions", inputs["qualification"], payload)
        choice = response["choices"][0]
        content = choice["message"].get("content") or ""
        evidence = {"model": model, "finish_reason": choice.get("finish_reason"),
            "content_chars": len(content), "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "reasoning_chars": len(choice["message"].get("reasoning_content") or ""),
            "request_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "passed": content.strip() == "READY" and choice.get("finish_reason") == "stop"}
        if not evidence["passed"]:
            raise RuntimeError(json.dumps(evidence, sort_keys=True))
        completions.append(evidence)
    print(json.dumps({**inputs["appliance"], "gateway_workers": workers,
                      "completions": completions, "tls_verified": True, "production_verified": True}))


if __name__ == "__main__":
    main()
