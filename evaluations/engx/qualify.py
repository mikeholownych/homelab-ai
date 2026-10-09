#!/usr/bin/env python3
"""Operational qualification of a gateway alias from a remote client (Q-TOOLS, Q-LONGCTX).

  qualify.py tools   <label> <base_url> <keyfile|-> <model> [sessions_dir]
  qualify.py longctx <label> <base_url> <keyfile|-> <model> [sessions_dir]

Everything goes through the gateway: requests, token counts (/v1/tokenize with the worker's own tokenizer) and the
alias's advertised limits (/v1/models). Nothing here contacts a worker or runs on the inference host.

Nexus sessions are read-only replay inputs. Their content is sent to the gateway but never written to results: a
result records only shapes, tool names, token counts, timings and verdicts.

The result file carries `capability_evidence`, keyed by the serving artifact digest, in the shape the gateway reads
from `orchestrator_gateway_capability_evidence` (a pass or fail per capability, with evidence id and date), so a
VERIFIED capability always points at the run that verified it."""
import glob, hashlib, json, os, random, shutil, sys, tempfile, time, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engx import OUT_DIR, sandbox_pytest, write_tree  # noqa: E402

TRIALS = int(os.environ.get("QUALIFY_TRIALS", "3"))
# Reasoning precedes the tool call or answer; the gateway clamps this to what the context leaves.
MAX_TOKENS = int(os.environ.get("QUALIFY_MAX_TOKENS", "12288"))
REQUEST_TIMEOUT = 1500
SESSIONS_DIR = os.path.expanduser("~/.nexus/sessions")


class Gateway:
    def __init__(self, base, key, model):
        self.base, self.model = base.rstrip("/"), model
        self.headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}

    def post(self, path, body, timeout=REQUEST_TIMEOUT):
        """(status, json body, X-AIHost-* headers, seconds). HTTP errors are results, not exceptions."""
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), self.headers)
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, raw, hdrs = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, raw, hdrs = e.code, e.read(), e.headers
        secs = round(time.monotonic() - t0, 2)
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"raw": raw[:400].decode(errors="replace")}
        return status, data, {k: v for k, v in hdrs.items() if k.lower().startswith("x-aihost")}, secs

    def chat(self, messages, **extra):
        return self.post("/v1/chat/completions", {"model": self.model, "messages": messages, "max_tokens": MAX_TOKENS,
                                                  "temperature": 0, **extra})

    def stream(self, messages, **extra):
        """Assemble an SSE stream the way an OpenAI client does. Returns (status, message, finish, chunks, seconds)."""
        body = {"model": self.model, "messages": messages, "max_tokens": MAX_TOKENS, "temperature": 0, "stream": True, **extra}
        req = urllib.request.Request(self.base + "/v1/chat/completions", json.dumps(body).encode(), self.headers)
        msg, calls, finish, chunks, t0 = {"content": "", "reasoning_content": ""}, {}, None, 0, time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                for line in r:
                    line = line.decode().strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[5:])
                    for choice in chunk.get("choices") or []:
                        chunks += 1
                        delta = choice.get("delta") or {}
                        for key in ("content", "reasoning_content"):
                            msg[key] += delta.get(key) or ""
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["function"]["name"] += fn.get("name") or ""
                            slot["function"]["arguments"] += fn.get("arguments") or ""
                        finish = choice.get("finish_reason") or finish
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read()[:400].decode(errors="replace")}, None, chunks, round(time.monotonic() - t0, 2)
        if calls:
            msg["tool_calls"] = [calls[i] for i in sorted(calls)]
        return 200, msg, finish, chunks, round(time.monotonic() - t0, 2)

    def prompt_tokens(self, messages, tools=None):
        body = {"model": self.model, "messages": messages, **({"tools": tools} if tools else {})}
        status, counted, _, _ = self.post("/v1/tokenize", body, timeout=120)
        return counted.get("prompt_tokens") if status == 200 and counted.get("source") == "exact" else None

    def describe(self):
        req = urllib.request.Request(self.base + "/v1/models", headers=self.headers)
        for m in json.load(urllib.request.urlopen(req, timeout=30))["data"]:
            if m["id"] == self.model:
                return m
        raise SystemExit(f"{self.model} is not served by {self.base}")


def fn(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOLS = [
    fn("read_file", "Read a file from the repository.", {"path": {"type": "string"}}, ["path"]),
    fn("write_file", "Replace a file's entire contents.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    fn("run_tests", "Run the repository's tests and return the pytest output.", {}, []),
]
SYSTEM = "You are a software engineer working in a Python repository through the provided tools. Use them; do not guess file contents."

# A small repository with one real defect; the loop is graded by tests the model never sees.
REPO = {
    "invoice.py": ("def total(lines, tax_rate):\n"
                   "    \"\"\"Sum quantity * unit_price over lines, then apply tax_rate (0.13 = 13%). Rounded to cents.\"\"\"\n"
                   "    subtotal = sum(line['qty'] * line['price'] for line in lines)\n"
                   "    return round(subtotal * tax_rate, 2)\n"),
    "tests/test_invoice.py": ("from invoice import total\n\n\n"
                              "def test_total_applies_tax():\n"
                              "    assert total([{'qty': 2, 'price': 5.0}], 0.13) == 11.3\n"),
}
HIDDEN = {"hidden/test_hidden.py": ("from invoice import total\n\n\n"
                                    "def test_empty():\n    assert total([], 0.13) == 0\n\n\n"
                                    "def test_zero_tax():\n    assert total([{'qty': 3, 'price': 1.25}], 0) == 3.75\n\n\n"
                                    "def test_rounding():\n    assert total([{'qty': 1, 'price': 19.99}], 0.13) == 22.59\n")}


def tool_calls(message):
    return message.get("tool_calls") or []


def well_formed(call, names):
    """A tool call a client can execute: a known function name and arguments that parse to a JSON object."""
    f = call.get("function") or {}
    try:
        args = json.loads(f.get("arguments") or "{}")
    except ValueError:
        return False
    return f.get("name") in names and isinstance(args, dict)


def leaked_markup(message):
    """Tool-call syntax left in the text means the server failed to parse a call the model made."""
    text = (message.get("content") or "")
    return any(marker in text for marker in ("<tool_call>", "<function=", "\"name\": \"read_file\"", "<|tool"))


def summary(status, r, secs, hdrs):
    if status != 200:
        return {"http_status": status, "error": json.dumps(r)[:300], "secs": secs}
    choice = r["choices"][0]
    usage = r.get("usage") or {}
    return {"http_status": status, "finish": choice.get("finish_reason"), "secs": secs, "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"), "tool_calls": [c["function"]["name"] for c in tool_calls(choice["message"])],
            "gateway": hdrs}


def check_single(gw):
    names = {t["function"]["name"] for t in TOOLS}
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "What does invoice.py currently do? Look before answering."}]
    status, r, hdrs, secs = gw.chat(msgs, tools=TOOLS)
    s = summary(status, r, secs, hdrs)
    m = r["choices"][0]["message"] if status == 200 else {}
    calls = tool_calls(m)
    # Call order within one turn is the model's choice; what matters is that it looks (read_file) with executable calls.
    s["pass"] = (bool(calls) and all(well_formed(c, names) for c in calls) and "read_file" in {c["function"]["name"] for c in calls}
                 and not leaked_markup(m))
    return s


def check_choice_none(gw):
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "In one sentence, what is a unit test?"}]
    status, r, hdrs, secs = gw.chat(msgs, tools=TOOLS, tool_choice="none")
    s = summary(status, r, secs, hdrs)
    m = r["choices"][0]["message"] if status == 200 else {}
    s["pass"] = status == 200 and not tool_calls(m) and bool((m.get("content") or "").strip()) and not leaked_markup(m)
    return s


def check_choice_named(gw):
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Check whether the repository is healthy."}]
    status, r, hdrs, secs = gw.chat(msgs, tools=TOOLS, tool_choice={"type": "function", "function": {"name": "run_tests"}})
    s = summary(status, r, secs, hdrs)
    m = r["choices"][0]["message"] if status == 200 else {}
    calls = tool_calls(m)
    s["pass"] = bool(calls) and all(c["function"]["name"] == "run_tests" and well_formed(c, {"run_tests"}) for c in calls)
    return s


def check_parallel(gw):
    names = {t["function"]["name"] for t in TOOLS}
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Read invoice.py and tests/test_invoice.py. Request both files at once, in a single turn."}]
    status, r, hdrs, secs = gw.chat(msgs, tools=TOOLS, parallel_tool_calls=True)
    s = summary(status, r, secs, hdrs)
    m = r["choices"][0]["message"] if status == 200 else {}
    calls = tool_calls(m)
    s["pass"] = len(calls) >= 2 and all(well_formed(c, names) for c in calls)
    return s


def check_stream(gw):
    names = {t["function"]["name"] for t in TOOLS}
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "What does invoice.py currently do? Look before answering."}]
    status, m, finish, chunks, secs = gw.stream(msgs, tools=TOOLS)
    calls = tool_calls(m) if status == 200 else []
    return {"http_status": status, "finish": finish, "chunks": chunks, "secs": secs, "tool_calls": [c["function"]["name"] for c in calls],
            "pass": status == 200 and finish == "tool_calls" and bool(calls) and all(well_formed(c, names) and c.get("id") for c in calls)}


def check_structured(gw):
    schema = {"type": "object", "additionalProperties": False, "required": ["severity", "files", "summary"],
              "properties": {"severity": {"type": "string", "enum": ["low", "medium", "high"]},
                             "files": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"}}}
    msgs = [{"role": "user", "content": "Triage this defect report as JSON: invoice.py total() multiplies the subtotal by the tax rate "
                                        "instead of adding tax, so every invoice is wrong."}]
    status, r, hdrs, secs = gw.chat(msgs, response_format={"type": "json_schema", "json_schema": {"name": "triage", "schema": schema, "strict": True}})
    s = summary(status, r, secs, hdrs)
    try:
        doc = json.loads(r["choices"][0]["message"]["content"]) if status == 200 else None
    except (ValueError, TypeError):
        doc = None
    s["pass"] = (isinstance(doc, dict) and set(doc) == {"severity", "files", "summary"} and doc["severity"] in ("low", "medium", "high")
                 and isinstance(doc["files"], list) and all(isinstance(f, str) for f in doc["files"]) and isinstance(doc["summary"], str))
    return s


def check_loop(gw, max_steps=12):
    """A real multi-turn agent loop: tools execute against a scratch repository and the result is graded by hidden tests."""
    names = {t["function"]["name"] for t in TOOLS}
    root = tempfile.mkdtemp(prefix="qualify_")
    try:
        write_tree(root, REPO)
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "total() in invoice.py returns the wrong amount: it should add tax to the subtotal. Fix it, "
                                            "make sure the tests pass, then reply with a one-line summary."}]
        steps, calls_made, malformed, secs = 0, [], 0, 0.0
        for steps in range(1, max_steps + 1):
            status, r, _, t = gw.chat(msgs, tools=TOOLS)
            secs += t
            if status != 200:
                return {"pass": False, "steps": steps, "http_status": status, "error": json.dumps(r)[:300], "secs": round(secs, 1)}
            m = r["choices"][0]["message"]
            calls = tool_calls(m)
            if not calls:
                break
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            for c in calls:
                name, ok = c["function"]["name"], well_formed(c, names)
                calls_made.append(name)
                malformed += not ok
                args = json.loads(c["function"]["arguments"] or "{}") if ok else {}
                path = os.path.normpath(str(args.get("path", "")))
                if not ok:
                    out = "error: malformed tool call"
                elif name in ("read_file", "write_file") and (path.startswith("..") or os.path.isabs(path) or path.startswith("hidden")):
                    out = "error: path outside the repository"
                elif name == "read_file":
                    p = os.path.join(root, path)
                    out = open(p).read() if os.path.isfile(p) else f"error: {path} does not exist"
                elif name == "write_file":
                    write_tree(root, {path: str(args.get("content", ""))})
                    out = f"wrote {path}"
                else:
                    out = sandbox_pytest(root, "tests")[1][-2000:]
                msgs.append({"role": "tool", "tool_call_id": c.get("id") or "", "content": out})
        write_tree(root, HIDDEN)
        hidden_ok, _ = sandbox_pytest(root, "hidden")
        return {"pass": hidden_ok and malformed == 0 and "write_file" in calls_made, "hidden_tests": hidden_ok, "steps": steps,
                "calls": calls_made, "malformed_calls": malformed, "secs": round(secs, 1)}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def load_sessions(sessions_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(sessions_dir, "*.json"))):
        try:
            doc = json.load(open(path))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("messages"), list):
            out.append((os.path.basename(path), doc["messages"]))
    return out


def normalise(messages):
    """OpenAI-shaped copy of a stored conversation. Nexus redacts tool-call ids, so they are reassigned in order and
    each tool result is bound to the call it answers, exactly as the original pairing was."""
    out, pending, n = [], [], 0
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant", "tool"):
            continue
        if m["role"] == "tool":
            if not pending:
                return None
            out.append({"role": "tool", "tool_call_id": pending.pop(0), "content": str(m.get("content") or "")})
            continue
        item = {"role": m["role"], "content": m.get("content") if isinstance(m.get("content"), str) else ""}
        calls = m.get("tool_calls")
        if isinstance(calls, str):
            try:
                calls = json.loads(calls)
            except ValueError:
                return None
        if m["role"] == "assistant" and calls:
            item["tool_calls"] = []
            for c in calls:
                n += 1
                f = c.get("function") or {}
                args = f.get("arguments")
                item["tool_calls"].append({"id": f"call_{n}", "type": "function", "function": {
                    "name": f.get("name"), "arguments": args if isinstance(args, str) else json.dumps(args or {})}})
                pending.append(f"call_{n}")
        out.append(item)
    return out


def derived_tools(messages):
    """Tool definitions reconstructed from the calls a session made: each observed argument becomes a property."""
    props = {}
    for m in messages:
        for c in m.get("tool_calls") or []:
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except ValueError:
                args = {}
            props.setdefault(c["function"]["name"], set()).update(args if isinstance(args, dict) else {})
    return [fn(name, f"The {name} tool.", {k: {} for k in sorted(keys)}, []) for name, keys in sorted(props.items())]


def replay_points(sessions, limit, max_prompt_chars=120_000, seed=7):
    """Prefixes that end where the original agent decided to call a tool, sampled across sessions."""
    points = []
    for name, raw in sessions:
        msgs = normalise(raw)
        if not msgs:
            continue
        tools = derived_tools(msgs)
        for i, m in enumerate(msgs):
            if m["role"] == "assistant" and m.get("tool_calls") and i and msgs[i - 1]["role"] in ("user", "tool"):
                prefix = msgs[:i]
                if len(json.dumps(prefix)) <= max_prompt_chars:
                    points.append((name, i, prefix, tools, [c["function"]["name"] for c in m["tool_calls"]]))
    random.Random(seed).shuffle(points)
    picked, seen = [], {}
    for p in points:  # at most two cut points per session, so one long session cannot dominate
        if seen.get(p[0], 0) < 2:
            picked.append(p); seen[p[0]] = seen.get(p[0], 0) + 1
        if len(picked) == limit:
            break
    return picked


def check_replay(gw, point):
    name, index, prefix, tools, original = point
    status, r, hdrs, secs = gw.chat(prefix, tools=tools)
    s = summary(status, r, secs, hdrs)
    s.update({"session_digest": hashlib.sha256(name.encode()).hexdigest()[:12], "cut": index, "messages": len(prefix),
              "original_calls": original})
    if status != 200:
        s["pass"] = False
        return s
    m = r["choices"][0]["message"]
    calls = tool_calls(m)
    names = {t["function"]["name"] for t in tools}
    # Valid outcomes are a well-formed call to a declared tool, or a plain answer; the verdict is structural.
    s["pass"] = not leaked_markup(m) and (all(well_formed(c, names) for c in calls) if calls else bool((m.get("content") or "").strip()))
    s["same_tool_as_original"] = bool(calls) and calls[0]["function"]["name"] == original[0]
    return s


def needle_prompt(gw, filler, target, depth, secret):
    """A user message of ~`target` prompt tokens of real session text, with one fact planted at `depth`."""
    fact = f"\n\nNOTE FOR THE READER: the release passphrase is {secret}.\n\n"
    question = "\n\nWhat is the release passphrase stated in the material above? Reply with the passphrase only."
    chars = target * 3
    for _ in range(4):
        body = filler[:chars]
        cut = int(len(body) * depth)
        content = body[:cut] + fact + body[cut:] + question
        n = gw.prompt_tokens([{"role": "user", "content": content}])
        if n is None:
            raise SystemExit("the gateway could not count tokens exactly; long-context sizes would be guesses")
        if abs(n - target) <= target * 0.01:
            break
        chars = int(chars * target / n)
    return content, n


def check_needle(gw, filler, target, depth, max_tokens):
    secret = "-".join(random.Random(target * 100 + int(depth * 100)).choice(["amber", "cobalt", "delta", "falcon", "garnet", "harbor",
                                                                              "indigo", "juniper", "kepler", "lumen"]) for _ in range(3))
    content, n = needle_prompt(gw, filler, target, depth, secret)
    status, r, hdrs, secs = gw.post("/v1/chat/completions", {"model": gw.model, "messages": [{"role": "user", "content": content}],
                                                             "max_tokens": max_tokens, "temperature": 0})
    s = summary(status, r, secs, hdrs)
    timings = (r.get("timings") or {}) if status == 200 else {}
    answer = (r["choices"][0]["message"].get("content") or "") if status == 200 else ""
    s.update({"target_tokens": target, "counted_prompt_tokens": n, "depth": depth, "answer_correct": secret in answer,
              "prompt_ms": timings.get("prompt_ms"), "prompt_tok_per_s": timings.get("prompt_per_second"),
              "decode_tok_per_s": timings.get("predicted_per_second")})
    s["pass"] = status == 200 and secret in answer
    return s


def filler_text(sessions, need_chars):
    """Real engineering text (tool outputs and messages from replay inputs), deterministic order."""
    parts, total = [], 0
    for _, raw in sessions:
        for m in raw:
            c = m.get("content") if isinstance(m, dict) else None
            if isinstance(c, str) and len(c) > 400 and "passphrase" not in c.lower():
                parts.append(c); total += len(c)
                if total >= need_chars:
                    return "\n\n".join(parts)
    raise SystemExit("not enough replay text for the long-context sizes")


def run_tools(gw, sessions_dir):
    checks = {"tool_call_single": check_single, "tool_choice_none": check_choice_none, "tool_choice_named": check_choice_named,
              "parallel_tool_calls": check_parallel, "streaming_tool_calls": check_stream, "structured_output": check_structured,
              "agent_loop": check_loop}
    results = {}
    for name, check in checks.items():
        results[name] = []
        for trial in range(1, TRIALS + 1):
            r = check(gw); r["trial"] = trial
            results[name].append(r)
            print(f"{name} trial={trial} {'PASS' if r['pass'] else 'FAIL'} secs={r.get('secs')}", flush=True)
    results["nexus_replay"] = []
    for point in replay_points(load_sessions(sessions_dir), int(os.environ.get("QUALIFY_REPLAYS", "20"))):
        r = check_replay(gw, point)
        results["nexus_replay"].append(r)
        print(f"nexus_replay {r['session_digest']}@{r['cut']} {'PASS' if r['pass'] else 'FAIL'} calls={r.get('tool_calls')} secs={r.get('secs')}", flush=True)
    return results


def run_longctx(gw, sessions_dir, limits):
    context = limits["context_length"]
    # Room for the alias's full reasoning budget plus the answer, so a miss is the model's and never a clamp's.
    answer_tokens = int((limits.get("reasoning") or {}).get("budget") or 0) + 1024
    # The largest prompt that still leaves that room (1% sizing tolerance and the gateway's margin), in 1K steps.
    largest = int((context - answer_tokens - 64) / 1.01) // 1024 * 1024
    targets = [int(t) for t in os.environ.get("QUALIFY_LONGCTX_TOKENS", f"16384,32768,49152,{largest}").split(",")]
    if max(targets) > largest:
        raise SystemExit(f"{max(targets)} prompt tokens cannot leave {answer_tokens} for reasoning and the answer in {context}")
    filler = filler_text(load_sessions(sessions_dir), max(targets) * 4 + 200_000)
    results = {"needle": [], "over_context": []}
    for target in targets:
        for depth in (0.1, 0.5, 0.9):
            r = check_needle(gw, filler, target, depth, answer_tokens)
            results["needle"].append(r)
            print(f"needle {target}@{depth} {'PASS' if r['pass'] else 'FAIL'} prompt={r['counted_prompt_tokens']} "
                  f"pp={r.get('prompt_tok_per_s')} tg={r.get('decode_tok_per_s')} secs={r.get('secs')}", flush=True)
    # The limit contract: a prompt that cannot fit is refused up front with the counted size, never sent to the worker.
    content, n = needle_prompt(gw, filler, context + 2048, 0.5, "x")
    status, r, hdrs, secs = gw.post("/v1/chat/completions", {"model": gw.model, "messages": [{"role": "user", "content": content}],
                                                             "max_tokens": 1024}, timeout=120)
    err = (r.get("error") or {}) if isinstance(r, dict) else {}
    results["over_context"].append({"counted_prompt_tokens": n, "http_status": status, "secs": secs, "gateway": hdrs,
                                    "error_type": err.get("type") or err.get("code"), "message": str(err.get("message"))[:300],
                                    "pass": status == 400 and secs < 30 and "context" in json.dumps(r).lower()})
    print(f"over_context prompt={n} status={status} secs={secs} {'PASS' if results['over_context'][0]['pass'] else 'FAIL'}", flush=True)
    return results


def rate(rows):
    return sum(r["pass"] for r in rows) / len(rows) if rows else 0.0


def capability_evidence(kind, results, evidence_id, date):
    """Verdicts the gateway can serve as VERIFIED. A capability passes only if every trial passed."""
    if kind != "tools":
        return {}
    verdict = lambda *names: "pass" if all(results[n] and rate(results[n]) == 1.0 for n in names) else "fail"
    return {cap: {"result": verdict(*checks), "evidence_id": evidence_id, "date": date} for cap, checks in {
        "tools": ("tool_call_single", "tool_choice_none", "tool_choice_named", "agent_loop"),
        "parallel_tool_calls": ("parallel_tool_calls",),
        "structured_output": ("structured_output",),
        "streaming": ("streaming_tool_calls",)}.items()}


def main(argv):
    if len(argv) < 5 or argv[0] not in ("tools", "longctx"):
        raise SystemExit(__doc__)
    kind, label, base, keyfile, model = argv[:5]
    sessions_dir = argv[5] if len(argv) > 5 else SESSIONS_DIR
    key = sys.stdin.read().strip() if keyfile == "-" else open(keyfile).read().strip()
    gw = Gateway(base, key, model)
    alias = gw.describe()
    expected = os.environ.get("QUALIFY_EXPECT_BUDGET")
    if expected is not None and (alias.get("reasoning") or {}).get("budget") != int(expected):
        raise SystemExit(f"the gateway reports {alias.get('reasoning')} for {model}, not budget {expected}; refusing to qualify")
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results = run_tools(gw, sessions_dir) if kind == "tools" else run_longctx(gw, sessions_dir, alias)
    evidence_id = f"qualify-{kind}-{label}-{started[:10]}"
    out = {"kind": kind, "label": label, "model": model, "base_url": base, "started": started,
           "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "trials": TRIALS, "max_tokens": MAX_TOKENS,
           "alias": {k: alias.get(k) for k in ("context_length", "max_completion_tokens", "limits_version", "reasoning", "serving")},
           "pass_rates": {name: round(rate(rows), 3) for name, rows in results.items()}, "results": results}
    digests = {s["artifact_digest"] for s in alias.get("serving") or [] if s.get("artifact_digest")}
    if len(digests) == 1:
        out["capability_evidence"] = {digests.pop(): capability_evidence(kind, results, evidence_id, started[:10])}
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{evidence_id}.json")
    json.dump(out, open(path, "w"), indent=1)
    print("RESULT", label, json.dumps(out["pass_rates"]), "->", path)


if __name__ == "__main__":
    main(sys.argv[1:])
