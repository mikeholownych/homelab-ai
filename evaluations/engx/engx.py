#!/usr/bin/env python3
"""Engineering-outcome evaluation: can a model, given a repository and a task, produce a change that passes
hidden external tests - and how many attempts, how much time and how many tokens does it take?

  engx.py selfcheck
  engx.py run <label> <base_url> <keyfile|-> <model> [max_attempts=3] [task-id-prefix,...]

Set ENGX_PYTHON to a client interpreter with pytest installed when the default system Python lacks pytest.

Each attempt: the model replies with full replacement files; they are written into a throwaway copy of the repo
(never tests/ or hidden/), then run under bubblewrap (no network, read-only system, scratch dir only) with pytest.
Visible failures are fed back as in a normal agent loop; a hidden-test failure is reported like CI (failing test
name and assertion message only). Success = hidden tests pass (T11: model tests pass on the correct class and
kill at least 4 of 5 broken variants)."""
import json, os, re, shutil, statistics, subprocess, sys, tempfile, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engx_tasks import TASKS as BASE_TASKS  # noqa: E402
from engx_tasks_hard import TASKS as HARD_TASKS  # noqa: E402

CORPORA = {"base": BASE_TASKS, "hard": HARD_TASKS, "all": BASE_TASKS + HARD_TASKS}
CORPUS = os.environ.get("ENGX_CORPUS", "base")
TASKS = CORPORA[CORPUS]
# Thinking models spend output tokens on reasoning before the files; 4096 truncates them.
MAX_TOKENS = int(os.environ.get("ENGX_MAX_TOKENS", "4096"))
OUT_DIR = os.environ.get("ENGX_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))


def corpus_digest(tasks):
    """Identity of the task corpus, so results from different corpus versions are never compared."""
    import hashlib
    blob = json.dumps([{k: t[k] for k in ("id", "instruction", "files", "visible", "hidden")} for t in tasks], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def sandbox_pytest(root, target, timeout=90):
    """Run pytest on `target` inside `root` under bubblewrap. Returns (ok, output)."""
    mounts = (["--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64"]
              if os.path.islink("/bin") else ["--ro-bind", "/bin", "/bin", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64"])
    python = "python3"
    override = os.environ.get("ENGX_PYTHON")
    if override:
        host_python = os.path.abspath(override)
        venv = os.path.dirname(os.path.dirname(host_python))
        if os.path.isfile(os.path.join(venv, "pyvenv.cfg")):
            mounts += ["--ro-bind", venv, "/opt/engx-python"]
            python = "/opt/engx-python/bin/" + os.path.basename(host_python)
        else:
            python = override
    cmd = ["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc/alternatives", "/etc/alternatives", *mounts,
           "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--bind", root, root, "--chdir", root,
           "--unshare-all", "--die-with-parent", "--clearenv", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
           "--setenv", "PYTHONPATH", root, "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
           "timeout", str(timeout), python, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", "-rN", "--tb=short", target]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
        return r.returncode == 0, (r.stdout + r.stderr)
    except Exception as e:
        return False, repr(e)


def write_tree(root, files):
    for rel, content in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p) or root, exist_ok=True)
        open(p, "w").write(content)


def fresh_repo(task, extra=None):
    d = tempfile.mkdtemp(prefix="eng_", dir="/tmp")
    write_tree(d, task["files"]); write_tree(d, task["visible"])
    if extra: write_tree(d, extra)
    return d


def tail(text, n=1400):
    text = text.strip()
    return text if len(text) <= n else "...\n" + text[-n:]


def failing_summary(output):
    """CI-style: failing test id(s) plus the assertion/exception lines; no source of the hidden tests."""
    lines = [l for l in output.splitlines() if l.startswith(("FAILED", "E  ", "ERROR")) or "Error" in l[:40]]
    return tail("\n".join(lines[:12]) or output, 900)


def validate(task, root, model_files):
    """Apply to a fresh repo, run visible then hidden. Returns (ok, stage, message)."""
    if task.get("mutation"):
        return validate_mutation(task, model_files)
    d = fresh_repo(task)
    try:
        write_tree(d, model_files)
        ok, out = sandbox_pytest(d, "tests")
        if not ok:
            return False, "visible", tail(out)
        write_tree(d, task["hidden"])
        ok, out = sandbox_pytest(d, "hidden")
        if not ok:
            return False, "hidden", failing_summary(out)
        return True, "hidden", "all hidden tests pass"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def validate_mutation(task, model_files):
    deliverable = task["deliverable"]
    tests = model_files.get(deliverable)
    if not tests:
        return False, "visible", f"no {deliverable} was provided"
    d = fresh_repo(task)
    try:
        write_tree(d, {deliverable: tests})
        ok, out = sandbox_pytest(d, "tests")
        m = re.search(r"(\d+) passed", out)
        if not ok:
            return False, "visible", "your tests do not all pass on the correct implementation:\n" + failing_summary(out)
        if not m or int(m.group(1)) < 5:
            return False, "hidden", "too few test functions; cover every behaviour in the docstring"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    killed = 0
    for name, mutant in task["mutants"].items():
        d = tempfile.mkdtemp(prefix="eng_mut_", dir="/tmp")
        try:
            write_tree(d, {"lru.py": mutant, deliverable: tests})
            if not sandbox_pytest(d, "tests")[0]:
                killed += 1
        finally:
            shutil.rmtree(d, ignore_errors=True)
    need = 4
    if killed >= need:
        return True, "hidden", f"killed {killed}/{len(task['mutants'])} broken variants"
    return False, "hidden", f"your tests detected only {killed} of {len(task['mutants'])} deliberate behaviour changes; cover more behaviours and edge cases"


def selfcheck():
    bad = 0
    for t in TASKS:
        d = fresh_repo(t)
        try:
            if t.get("mutation"):
                ok_ref, _, msg = validate(t, d, t["reference"])
                ok_empty, _, _ = validate(t, d, {t["deliverable"]: "def test_nothing():\n    assert True\n"})
                good = ok_ref and not ok_empty
                print(f"{t['id']:24s} reference={'PASS' if ok_ref else 'FAIL'} ({msg}) trivial-tests={'rejected' if not ok_empty else 'ACCEPTED'}  {'ok' if good else 'BROKEN'}")
                bad += not good; continue
            init_vis, _ = sandbox_pytest(d, "tests")
            write_tree(d, t["hidden"]); init_hid, hid_out = sandbox_pytest(d, "hidden")
            ok_ref, stage, msg = validate(t, d, t["reference"])
            good = (not init_vis) and (not init_hid) and ok_ref
            print(f"{t['id']:24s} initial: visible={'fails' if not init_vis else 'PASSES'} hidden={'fails' if not init_hid else 'PASSES'}  reference={'PASS' if ok_ref else 'FAIL: ' + msg[:160]}  {'ok' if good else 'BROKEN'}")
            bad += not good
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print("SELFCHECK", "OK" if not bad else f"{bad} broken task(s)")
    return bad


def parse_files(text):
    """Map relative .py path -> content from fenced code blocks. The path may be named by the nearest preceding
    non-empty line (`### FILE: a.py`, `### a.py`, `**a.py**`, `File: a.py`, `a.py:`) or by the fence info string;
    equivalent labelling styles are accepted because they carry the same information."""
    files = {}
    path_re = re.compile(r"([A-Za-z0-9_./\-]+\.py)\b")
    for m in re.finditer(r"```([^\n]*)\n(.*?)```", text, re.S):
        before = [l for l in text[:m.start()].splitlines() if l.strip()]
        head = before[-1] if before else ""
        found = path_re.findall(head) or path_re.findall(m.group(1))
        if found:
            files[found[-1].lstrip("./") if found[-1].startswith("./") else found[-1]] = m.group(2)
    if not files:
        # Same information without fences: `### FILE: path` followed directly by the file body, up to the next header.
        heads = list(re.finditer(r"^#{1,6}\s*(?:FILE:\s*)?`?([A-Za-z0-9_./\-]+\.py)`?\s*$", text, re.M))
        for i, h in enumerate(heads):
            body = text[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip("\n")
            if body.strip():
                files[h.group(1)[2:] if h.group(1).startswith("./") else h.group(1)] = body.rstrip() + "\n"
    return files



def _parse_selftest():
    cases = {
        "### FILE: a.py\n```python\nx=1\n```": {"a.py": "x=1\n"},
        "### a.py\n```python\nx=1\n```\n\n### pkg/b.py\n```python\ny=2\n```": {"a.py": "x=1\n", "pkg/b.py": "y=2\n"},
        "**users.py**\n```python\nz=3\n```": {"users.py": "z=3\n"},
        "File: tests/test_x.py:\n```python\nassert 1\n```": {"tests/test_x.py": "assert 1\n"},
        "Here is the fix.\n```python title=\"m.py\"\nq=4\n```": {"m.py": "q=4\n"},
        "```python\nno_name=1\n```": {},
        "### FILE: a.py\nx=1\ny=2\n\n### FILE: pkg/b.py\nz=3\n": {"a.py": "x=1\ny=2\n", "pkg/b.py": "z=3\n"},
        "Here you go.\n\nNo files.": {},
    }
    for text, want in cases.items():
        got = parse_files(text)
        assert got == want, (text, got, want)
    print("PARSE SELFTEST OK")


def allowed(task, path):
    if path.startswith("/") or ".." in path.split("/") or path.startswith("hidden/") or path == "conftest.py":
        return False
    if path.startswith("tests/"):
        return path == task.get("deliverable")
    return path.endswith(".py")


def render_repo(task):
    parts = []
    for rel, content in {**task["files"], **task["visible"]}.items():
        parts.append(f"--- {rel} ---\n{content.rstrip()}\n")
    return "\n".join(parts)


REASONING_BUDGET = int(os.environ["ENGX_REASONING_BUDGET"]) if os.environ.get("ENGX_REASONING_BUDGET") else None
REASONING_BUDGET_MESSAGE = os.environ.get("ENGX_REASONING_BUDGET_MESSAGE", "")


def count_tokens(base, headers, text):
    """Exact token count from the serving engine's own tokenizer (llama.cpp /tokenize); None if unavailable."""
    if not text:
        return 0
    try:
        req = urllib.request.Request(base + "/tokenize", json.dumps({"content": text}).encode(), headers)
        return len(json.load(urllib.request.urlopen(req, timeout=60)).get("tokens") or [])
    except Exception:
        return None


def attempt_metrics(r, base, headers, text, reasoning, files):
    """Per-attempt serving evidence, kept separate from the validator result."""
    choice = r["choices"][0]
    usage = r.get("usage") or {}
    timings = r.get("timings") or {}
    reasoning_tokens = count_tokens(base, headers, reasoning)
    answer_tokens = count_tokens(base, headers, text)
    prompt_ms, predicted_ms, predicted_n = timings.get("prompt_ms"), timings.get("predicted_ms"), timings.get("predicted_n")
    ttft_ms = None
    if isinstance(prompt_ms, (int, float)):
        ttft_ms = round(prompt_ms + ((predicted_ms / predicted_n) if predicted_ms and predicted_n else 0), 1)
    budget_reached = None
    if REASONING_BUDGET is not None and reasoning_tokens is not None:
        budget_reached = reasoning_tokens >= REASONING_BUDGET - 8 or bool(REASONING_BUDGET_MESSAGE and REASONING_BUDGET_MESSAGE in reasoning)
    finish = choice.get("finish_reason")
    return {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": reasoning_tokens, "answer_tokens": answer_tokens, "reasoning_chars": len(reasoning),
            "ttft_ms_est": ttft_ms, "prompt_ms": prompt_ms, "predicted_ms": predicted_ms, "predicted_n": predicted_n,
            "reasoning_budget": REASONING_BUDGET, "budget_reached": budget_reached,
            "valid_final_answer": bool(files), "termination": "output_limit" if finish == "length" else finish}


def classify_error(text):
    t = text.lower()
    if "context" in t and ("exceed" in t or "size" in t or "length" in t):
        return "context_limit"
    if "timed out" in t or "timeout" in t:
        return "timeout"
    return "error"


def run_task(task, base, headers, model, max_attempts):
    d = fresh_repo(task)
    try:
        init_out = ""
        if task["visible"]:
            _, init_out = sandbox_pytest(d, "tests")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    system = ("You are an autonomous software engineer working in a Python repository. Reply with the COMPLETE new contents of every file "
              "you change, each introduced by a line `### FILE: <relative/path.py>` followed by a fenced code block. Do not omit unchanged "
              "parts of a file you change, do not modify files under tests/ (unless the task asks you to write one), and add no commentary "
              "beyond a sentence or two.")
    user = (f"Task: {task['instruction']}\n\nRepository:\n\n{render_repo(task)}\n"
            + (f"Current visible test output:\n```\n{tail(init_out)}\n```\n" if init_out else ""))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    rec = {"id": task["id"], "discipline": task["discipline"], "success": False, "attempts": 0, "model_secs": 0.0, "tokens": 0, "history": []}
    t_start = time.monotonic()
    for attempt in range(1, max_attempts + 1):
        body = {"model": model, "messages": messages, "max_tokens": MAX_TOKENS, "temperature": 0}
        if os.environ.get("NOTHINK"): body["chat_template_kwargs"] = {"enable_thinking": False}
        t0 = time.monotonic()
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(base + "/v1/chat/completions", json.dumps(body).encode(), headers), timeout=1500))
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:400]
            rec["history"].append({"attempt": attempt, "error": msg, "termination": classify_error(msg), "wall_secs": round(time.monotonic() - t0, 1)}); break
        except Exception as e:
            rec["history"].append({"attempt": attempt, "error": repr(e)[:400], "termination": classify_error(repr(e)), "wall_secs": round(time.monotonic() - t0, 1)}); break
        rec["model_secs"] += time.monotonic() - t0
        usage = r.get("usage") or {}
        rec["tokens"] += (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        rec["attempts"] = attempt
        text = r["choices"][0]["message"].get("content") or ""
        reasoning = r["choices"][0]["message"].get("reasoning_content") or ""
        attempt_secs = round(time.monotonic() - t0, 1)
        files = {p: c for p, c in parse_files(text).items() if allowed(task, p)}
        ignored = [p for p in parse_files(text) if p not in files]
        if not files:
            feedback = "No usable `### FILE:` blocks were found (or they targeted forbidden paths). Reply with complete files in the required format."
            ok, stage = False, "format"
        else:
            ok, stage, feedback = validate(task, None, files)
        rec["history"].append({"attempt": attempt, "stage": stage, "ok": ok, "files": sorted(files), "ignored": ignored, "finish": r["choices"][0].get("finish_reason"),
                               "feedback": feedback[:1500], "response": text[:12000], "reasoning_tail": reasoning[-2000:],
                               "wall_secs": attempt_secs, **attempt_metrics(r, base, headers, text, reasoning, files)})
        if ok:
            rec["success"] = True; break
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": f"Validation failed ({stage} stage):\n```\n{feedback}\n```\nFix the problem and reply again with the complete changed files."}]
    rec["wall_secs"] = round(time.monotonic() - t_start, 1); rec["model_secs"] = round(rec["model_secs"], 1)
    return rec


def run_meta(model, base, tasks, max_attempts, only):
    return {"model": model, "base_url": base, "corpus": CORPUS, "corpus_digest": corpus_digest(tasks), "max_tokens": MAX_TOKENS,
            "max_attempts": max_attempts, "only": only, "condition": os.environ.get("ENGX_CONDITION"),
            "client_thinking_disabled": bool(os.environ.get("NOTHINK")), "reasoning_budget": REASONING_BUDGET,
            "reasoning_budget_message": REASONING_BUDGET_MESSAGE or None, "temperature": 0}


def run(label, base, keyfile, model, max_attempts=3, only=None):
    # `-` reads a scoped client token from stdin so remote qualification can pipe it directly from
    # the protected provisioner without writing it to a file, argv, or captured task output.
    key = subprocess.run(["sudo", "cat", keyfile], capture_output=True, text=True).stdout.strip() if keyfile != "-" else sys.stdin.read().strip()
    headers = {"Content-Type": "application/json"}
    if key: headers["Authorization"] = "Bearer " + key
    tasks = [t for t in TASKS if not only or any(t["id"].startswith(p) for p in only)]
    reps = int(os.environ.get("ENGX_REPS", "1"))
    all_results = []
    for rep in range(1, reps + 1):
        results = []
        for t in tasks:
            r = run_task(t, base, headers, model, max_attempts); r["rep"] = rep
            results.append(r)
            print(f"{label} rep{rep} {t['id']:24s} {'PASS' if r['success'] else 'FAIL'} attempts={r['attempts']} wall={r['wall_secs']}s tokens={r['tokens']}", flush=True)
            # Partial results after every task, so an interrupted run keeps its per-attempt evidence.
            os.makedirs(OUT_DIR, exist_ok=True)
            json.dump({"label": label, "meta": {**run_meta(model, base, tasks, max_attempts, only), "partial": True},
                       "results": all_results + results}, open(os.path.join(OUT_DIR, f"eng-{CORPUS}-{label}.partial.json"), "w"))
        all_results += results
    n = len(all_results)
    ok = [r for r in all_results if r["success"]]
    per_task = {}
    for r in all_results: per_task.setdefault(r["id"], []).append(r["success"])
    summary = {"reps": reps, "tasks": len(tasks), "validated_rate": round(100 * len(ok) / n, 1),
               "validated_per_rep": [sum(1 for r in all_results if r["rep"] == k and r["success"]) for k in range(1, reps + 1)],
               "first_attempt_rate": round(100 * sum(1 for r in ok if r["attempts"] == 1) / n, 1),
               "median_secs_to_validated": round(statistics.median([r["wall_secs"] for r in ok]), 1) if ok else None,
               "mean_secs_per_task": round(sum(r["wall_secs"] for r in all_results) / n, 1),
               "mean_tokens_per_task": round(sum(r["tokens"] for r in all_results) / n),
               "per_task_pass": {k: f"{sum(v)}/{len(v)}" for k, v in per_task.items()},
               "always_fail": [k for k, v in per_task.items() if not any(v)], "flaky": [k for k, v in per_task.items() if any(v) and not all(v)]}
    print("RESULT", label, json.dumps(summary))
    meta = {**run_meta(model, base, tasks, max_attempts, only), "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump({"label": label, "meta": meta, "summary": summary, "results": all_results},
              open(os.path.join(OUT_DIR, f"eng-{CORPUS}-{label}.json"), "w"))


if __name__ == "__main__":
    if sys.argv[1] == "selfcheck":
        _parse_selftest(); sys.exit(1 if selfcheck() else 0)
    run(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6]) if len(sys.argv) > 6 else 3,
        sys.argv[7].split(",") if len(sys.argv) > 7 else None)
