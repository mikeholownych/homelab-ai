"""Harder engineering corpus (H01-H10), same shape as engx_tasks.py.

Calibrated against the 2026-10-03 results: the base corpus only separates models on 5 of 12 tasks. These tasks
are spec-dense (many edge cases stated once in a docstring), contain several interacting defects, or need
an algorithmic change, so a model has to read carefully rather than pattern-match. Hidden tests check only
behaviour the instruction or docstrings state."""

TASKS = []


def task(**kw):
    TASKS.append(kw)


# ----------------------------------------------------------------------------------------------- H01
task(
    id="H01-semver-range", discipline="spec_implementation",
    instruction="Implement `satisfies` in semver.py exactly as its docstring specifies.",
    files={
        "semver.py": '''def satisfies(version, rng):
    """Return True if `version` satisfies the range `rng`, else False.

    Versions are "MAJOR.MINOR.PATCH" optionally followed by "-PRERELEASE", where PRERELEASE is one or more
    dot-separated identifiers made of [0-9A-Za-z-]. MAJOR, MINOR, PATCH and purely numeric prerelease identifiers
    are non-negative integers without leading zeros ("0" is fine). Build metadata ("+...") is not allowed.
    An invalid version or range raises ValueError; the WHOLE range is validated even if an earlier part matches.

    Precedence (SemVer 2.0.0): compare MAJOR, MINOR, PATCH numerically. A version with a prerelease is lower than
    the same version without one. Prerelease identifiers are compared left to right: numeric ones numerically,
    alphanumeric ones in ASCII order, numeric always lower than alphanumeric, and if all shared identifiers are
    equal the version with fewer identifiers is lower.

    Range grammar: one or more comparator sets separated by "||" (whitespace around "||" is ignored). The range
    is satisfied if ANY set is satisfied. A set is one or more comparators separated by whitespace; it is
    satisfied if ALL its comparators are. An empty set (e.g. "1.0.0 ||") is invalid. Comparators, with no
    whitespace between operator and version:
        "V" or "=V"   equal to V
        ">V" ">=V" "<V" "<=V"
        "^V"          >=V and below the next "significant" version: < (MAJOR+1).0.0 if MAJOR > 0,
                      else < 0.(MINOR+1).0 if MINOR > 0, else < 0.0.(PATCH+1)
        "~V"          >=V and < MAJOR.(MINOR+1).0

    Prerelease rule: a version that HAS a prerelease satisfies a set only if, in addition, some comparator in that
    set names a version with the same MAJOR.MINOR.PATCH that also has a prerelease (for ^V and ~V the named
    version is V). Versions without a prerelease are not affected by this rule.
    """
    raise NotImplementedError
''',
    },
    visible={"tests/test_semver.py": '''from semver import satisfies


def test_basic():
    assert satisfies("1.2.3", "1.2.3")
    assert satisfies("1.4.0", "^1.2.3")
    assert not satisfies("2.0.0", "^1.2.3")
'''},
    hidden={"hidden/test_semver_hidden.py": '''from semver import satisfies


def raises(v, r):
    try:
        satisfies(v, r)
    except ValueError:
        return True
    return False


def test_precedence_chain():
    chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
             "1.0.0-rc.1", "1.0.0"]
    for lo, hi in zip(chain, chain[1:]):
        assert satisfies(hi, ">" + lo), (hi, lo)
        assert not satisfies(lo, ">" + hi), (lo, hi)
        assert satisfies(lo, "<" + hi) == ("-" in hi), (lo, hi)
    assert satisfies("1.0.0-1", "<1.0.0-a") and satisfies("1.0.0-2", ">1.0.0-1") and satisfies("1.0.0-10", ">1.0.0-9")


def test_caret_and_tilde():
    assert satisfies("1.2.3", "^1.2.3") and satisfies("1.9.9", "^1.2.3")
    assert not satisfies("1.2.2", "^1.2.3") and not satisfies("2.0.0", "^1.2.3")
    assert satisfies("0.2.9", "^0.2.3") and not satisfies("0.3.0", "^0.2.3")
    assert satisfies("0.0.3", "^0.0.3") and not satisfies("0.0.4", "^0.0.3")
    assert satisfies("1.2.9", "~1.2.3") and not satisfies("1.3.0", "~1.2.3") and not satisfies("1.2.2", "~1.2.3")
    assert satisfies("0.1.5", "~0.1.0") and not satisfies("0.2.0", "~0.1.0")


def test_prerelease_rule():
    assert not satisfies("1.2.4-beta", "^1.2.3")
    assert not satisfies("2.0.0-rc.1", "<2.0.0")
    assert satisfies("1.2.3-beta.2", ">=1.2.3-beta.1 <2.0.0")
    assert not satisfies("1.2.4-beta", ">=1.2.3-beta.1")
    assert satisfies("1.2.3-beta.5", "^1.2.3-beta.2")
    assert satisfies("1.2.4-beta", "1.2.4-beta")
    assert satisfies("1.2.4-beta", "^9.0.0 || >=1.2.4-alpha")
    assert satisfies("1.5.0", ">=1.2.3-beta.1 <2.0.0")


def test_sets_and_whitespace():
    assert satisfies("0.9.0", "<1.0.0 || >=2.0.0") and satisfies("2.0.0", "<1.0.0 || >=2.0.0")
    assert not satisfies("1.5.0", "<1.0.0 || >=2.0.0")
    assert satisfies("1.0.5", "  >=1.0.0    <1.1.0  ")
    assert satisfies("3.1.0", "1.2.3||^3.0.0")
    assert satisfies("1.2.3", "=1.2.3") and not satisfies("1.2.4", "=1.2.3")
    assert satisfies("1.2.3", ">=1.2.3 <=1.2.3") and not satisfies("1.2.3", ">1.2.3")


def test_invalid():
    for v, r in [("1.2", "*"), ("01.2.3", ">=0.0.0"), ("1.2.3+build", ">=0.0.0"), ("a.b.c", ">=0.0.0"), ("1.2.3-", ">=0.0.0"),
                 ("1.2.3-01", ">=0.0.0"), ("1.2.3-a..b", ">=0.0.0"),
                 ("1.2.3", ""), ("1.2.3", "^"), ("1.2.3", ">=1.2"), ("1.2.3", "1.2.3 ||"), ("1.2.3", "|| 1.2.3"),
                 ("1.2.3", ">= 1.2.3"), ("1.2.3", "1.2.3 || ^x"), ("1.2.3", "=>1.2.3")]:
        assert raises(v, r), (v, r)
'''},
    reference={
        "semver.py": '''import re

_NUM = r"(0|[1-9][0-9]*)"
_ID = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_VER = re.compile(_NUM + r"\\." + _NUM + r"\\." + _NUM + r"(?:-(" + _ID + r"(?:\\." + _ID + r")*))?")
_CMP = re.compile(r"(>=|<=|>|<|=|\\^|~)?(.+)")


def _parse(v):
    m = _VER.fullmatch(v)
    if not m:
        raise ValueError("invalid version: %r" % (v,))
    pre = tuple(m.group(4).split(".")) if m.group(4) else ()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), pre


def _cmp(a, b):
    (ta, pa), (tb, pb) = a, b
    if ta != tb:
        return -1 if ta < tb else 1
    if pa == pb:
        return 0
    if not pa:
        return 1
    if not pb:
        return -1
    key = lambda pre: [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre]
    return -1 if key(pa) < key(pb) else 1


def _comparators(text):
    m = _CMP.fullmatch(text)
    if not m:
        raise ValueError("invalid comparator: %r" % (text,))
    op, v = m.group(1) or "=", _parse(m.group(2))
    (major, minor, patch), _ = v
    if op == "^":
        hi = (major + 1, 0, 0) if major else (0, minor + 1, 0) if minor else (0, 0, patch + 1)
        return [(">=", v), ("<", (hi, ()))], v
    if op == "~":
        return [(">=", v), ("<", ((major, minor + 1, 0), ()))], v
    return [(op, v)], v


_OPS = {"=": lambda c: c == 0, ">": lambda c: c > 0, ">=": lambda c: c >= 0, "<": lambda c: c < 0, "<=": lambda c: c <= 0}


def satisfies(version, rng):
    v = _parse(version)
    if not isinstance(rng, str):
        raise ValueError("range must be a string")
    sets = []
    for part in rng.split("||"):
        words = part.split()
        if not words:
            raise ValueError("empty comparator set")
        tests, named = [], []
        for w in words:
            t, n = _comparators(w)
            tests += t
            named.append(n)
        sets.append((tests, named))
    for tests, named in sets:
        if not all(_OPS[op](_cmp(v, cv)) for op, cv in tests):
            continue
        if v[1] and not any(n[0] == v[0] and n[1] for n in named):
            continue
        return True
    return False
'''},
)

# ----------------------------------------------------------------------------------------------- H02
task(
    id="H02-cron-next", discipline="spec_implementation",
    instruction="Implement `next_fire` in cron.py exactly as its docstring specifies.",
    files={
        "cron.py": '''from datetime import datetime, timedelta


def next_fire(expr, after):
    """Return the first naive datetime STRICTLY after `after` (a naive datetime) that matches cron expression `expr`.
    Results always have second == 0 and microsecond == 0.

    `expr` has exactly 5 whitespace-separated fields: minute (0-59), hour (0-23), day-of-month (1-31),
    month (1-12), day-of-week (0-7, where both 0 and 7 mean Sunday, 1 = Monday ... 6 = Saturday).
    Each field is a comma-separated list of items. An item is "*" (the whole field range), "N", or "A-B" (A <= B),
    optionally followed by "/S" (S >= 1): take every S-th value of the item starting at its first value.
    "*/S" starts at the field minimum and "N/S" means N through the field maximum in steps of S.

    Day matching: a field is "unrestricted" only if it is exactly "*". If both day-of-month and day-of-week are
    restricted, a day matches when EITHER matches; otherwise both must match.

    Empty items, out-of-range values, A > B, S < 1, non-digit characters, or a wrong number of fields raise
    ValueError. If the expression has no match within 3000 days after `after` (e.g. "0 0 30 2 *"), raise ValueError.
    """
    raise NotImplementedError
''',
    },
    visible={"tests/test_cron.py": '''from datetime import datetime
from cron import next_fire


def test_basic():
    assert next_fire("*/15 * * * *", datetime(2026, 10, 6, 10, 7)) == datetime(2026, 10, 6, 10, 15)
    assert next_fire("0 0 1 * *", datetime(2026, 10, 6, 10, 7)) == datetime(2026, 11, 1, 0, 0)
'''},
    hidden={"hidden/test_cron_hidden.py": '''from datetime import datetime as dt
from cron import next_fire


def raises(expr, after=dt(2026, 10, 6)):
    try:
        next_fire(expr, after)
    except ValueError:
        return True
    return False


def test_strictly_after_and_seconds():
    assert next_fire("*/15 * * * *", dt(2026, 10, 6, 10, 15)) == dt(2026, 10, 6, 10, 30)
    assert next_fire("*/15 * * * *", dt(2026, 10, 6, 10, 14, 59, 999999)) == dt(2026, 10, 6, 10, 15)
    assert next_fire("*/15 * * * *", dt(2026, 10, 6, 23, 50)) == dt(2026, 10, 7, 0, 0)
    assert next_fire("* * * * *", dt(2026, 10, 6, 10, 15, 30)) == dt(2026, 10, 6, 10, 16)


def test_lists_ranges_steps():
    assert next_fire("0-10/5,30 * * * *", dt(2026, 10, 6, 10, 0)) == dt(2026, 10, 6, 10, 5)
    assert next_fire("0-10/5,30 * * * *", dt(2026, 10, 6, 10, 10)) == dt(2026, 10, 6, 10, 30)
    assert next_fire("5/20 * * * *", dt(2026, 10, 6, 10, 5)) == dt(2026, 10, 6, 10, 25)
    assert next_fire("5/20 * * * *", dt(2026, 10, 6, 10, 45)) == dt(2026, 10, 6, 11, 5)
    assert next_fire("0  12   * * *", dt(2026, 10, 6, 12, 0)) == dt(2026, 10, 7, 12, 0)


def test_rollovers():
    assert next_fire("0 0 1 * *", dt(2026, 12, 31, 23, 59, 30)) == dt(2027, 1, 1, 0, 0)
    assert next_fire("59 23 31 12 *", dt(2026, 12, 31, 23, 59)) == dt(2027, 12, 31, 23, 59)
    assert next_fire("0 0 29 2 *", dt(2026, 3, 1)) == dt(2028, 2, 29, 0, 0)


def test_day_of_week():
    assert next_fire("30 9 * * 1-5", dt(2026, 10, 2, 10, 0)) == dt(2026, 10, 5, 9, 30)
    assert next_fire("0 0 * * 7", dt(2026, 10, 6)) == dt(2026, 10, 11, 0, 0)
    assert next_fire("0 0 * * 0", dt(2026, 10, 6)) == dt(2026, 10, 11, 0, 0)
    assert next_fire("0 12 * * 5", dt(2026, 10, 9, 12, 0)) == dt(2026, 10, 16, 12, 0)


def test_dom_dow_or_semantics():
    assert next_fire("0 12 13 * 5", dt(2026, 10, 6)) == dt(2026, 10, 9, 12, 0)
    assert next_fire("0 12 13 * *", dt(2026, 10, 6)) == dt(2026, 10, 13, 12, 0)
    assert next_fire("0 0 */2 * *", dt(2026, 10, 6)) == dt(2026, 10, 7, 0, 0)
    assert next_fire("0 0 */2 * 1", dt(2026, 10, 7, 1, 0)) == dt(2026, 10, 9, 0, 0)
    assert next_fire("0 0 2 * 1", dt(2026, 10, 6)) == dt(2026, 10, 12, 0, 0)


def test_invalid():
    for e in ["60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "* * * * 8", "* * * *", "* * * * * *",
              "*/0 * * * *", "5-1 * * * *", "a * * * *", "1,,2 * * * *", "-1 * * * *", "1-2-3 * * * *", "",
              "0 0 30 2 *", "0 0 31 4 *"]:
        assert raises(e), e
'''},
    reference={
        "cron.py": '''import re
from datetime import datetime, timedelta

_BOUNDS = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
_ITEM = re.compile(r"(\\*|[0-9]+|[0-9]+-[0-9]+)(?:/([0-9]+))?")


def _field(text, lo, hi):
    vals = set()
    for item in text.split(","):
        m = _ITEM.fullmatch(item)
        if not m:
            raise ValueError("bad item %r" % (item,))
        base, step = m.group(1), m.group(2)
        s = int(step) if step is not None else 1
        if s < 1:
            raise ValueError("bad step")
        if base == "*":
            a, b = lo, hi
        elif "-" in base:
            a, b = (int(x) for x in base.split("-"))
            if a > b:
                raise ValueError("bad range")
        else:
            a = int(base)
            b = hi if step is not None else a
        if a < lo or b > hi:
            raise ValueError("out of range")
        vals.update(range(a, b + 1, s))
    return vals


def next_fire(expr, after):
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("need 5 fields")
    mins, hours, doms, months, dows = (_field(p, lo, hi) for p, (lo, hi) in zip(parts, _BOUNDS))
    dows = {d % 7 for d in dows}
    either = parts[2] != "*" and parts[4] != "*"
    start = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for i in range(3001):
        d = start.date() + timedelta(days=i)
        if d.month not in months:
            continue
        dom_ok, dow_ok = d.day in doms, d.isoweekday() % 7 in dows
        if not ((dom_ok or dow_ok) if either else (dom_ok and dow_ok)):
            continue
        for h in sorted(hours):
            for m in sorted(mins):
                cand = datetime(d.year, d.month, d.day, h, m)
                if cand >= start:
                    return cand
    raise ValueError("expression never fires")
'''},
)

# ----------------------------------------------------------------------------------------------- H03
task(
    id="H03-json-patch", discipline="spec_implementation",
    instruction="Implement `apply_patch` in jsonpatch.py exactly as its docstring specifies.",
    files={
        "jsonpatch.py": '''class PatchError(ValueError):
    pass


def apply_patch(doc, ops):
    """Apply a JSON Patch (RFC 6902 subset) to `doc` and return the resulting NEW document.

    `doc` and `ops` must never be modified, and the result must share no mutable object (dict/list) with either.
    The patch is all-or-nothing: on any error, raise PatchError.

    `ops` is a list of dicts. Each has "op" (one of add, remove, replace, move, copy, test) and "path";
    add/replace/test also need "value" (which may be None); move/copy also need "from". Missing keys are errors.

    Paths are JSON Pointers: "" is the whole document; otherwise "/" followed by "/"-separated tokens in which
    "~1" stands for "/" and "~0" for "~" ("~01" is the key "~1"). A "~" not followed by 0 or 1 is an error.
    A token addressing a list must be a base-10 index without leading zeros ("0" is fine). "-" means "past the
    end of the list" and is only allowed as the final token of an add (or of the target of move/copy).

    add:     object -> set the member (replacing any existing value); list -> insert BEFORE the index
             (index == len appends, index > len is an error). Adding at "" replaces the whole document.
             The parent container must exist.
    remove:  the target must exist. Removing "" is an error.
    replace: the target must exist. Replacing "" replaces the whole document.
    move:    remove the value at "from", then add it at "path". It is an error if "path" lies strictly inside
             "from" (a proper descendant). from == path is a no-op, but "from" must still exist.
    copy:    add a deep copy of the value at "from" at "path".
    test:    the target must exist and equal "value". Equality is JSON equality: numbers by value (1 == 1.0),
             booleans are never equal to numbers, objects by keys and values, lists elementwise.
    """
    raise NotImplementedError
''',
    },
    visible={"tests/test_patch.py": '''from jsonpatch import apply_patch


def test_basic():
    assert apply_patch({"a": 1}, [{"op": "add", "path": "/b", "value": 2}]) == {"a": 1, "b": 2}
    assert apply_patch({"a": [1, 2]}, [{"op": "remove", "path": "/a/0"}]) == {"a": [2]}
'''},
    hidden={"hidden/test_patch_hidden.py": '''import copy
from jsonpatch import apply_patch, PatchError


def fails(doc, ops):
    before = copy.deepcopy(doc)
    try:
        apply_patch(doc, ops)
    except PatchError:
        assert doc == before
        return True
    return False


def test_lists():
    d = {"a": [1, 2, 3]}
    assert apply_patch(d, [{"op": "add", "path": "/a/1", "value": 9}]) == {"a": [1, 9, 2, 3]}
    assert apply_patch(d, [{"op": "add", "path": "/a/3", "value": 9}]) == {"a": [1, 2, 3, 9]}
    assert apply_patch(d, [{"op": "add", "path": "/a/-", "value": 9}]) == {"a": [1, 2, 3, 9]}
    assert fails(d, [{"op": "add", "path": "/a/4", "value": 9}])
    assert fails(d, [{"op": "add", "path": "/a/01", "value": 9}])
    assert fails(d, [{"op": "replace", "path": "/a/3", "value": 9}])
    assert fails(d, [{"op": "remove", "path": "/a/-"}])
    assert fails(d, [{"op": "add", "path": "/a/-/x", "value": 9}])
    assert apply_patch([1, 2], [{"op": "replace", "path": "/1", "value": [5]}]) == [1, [5]]


def test_pointer_escapes():
    d = {"a/b": 1, "m~n": 2, "~1": 3, "": 4}
    assert apply_patch(d, [{"op": "test", "path": "/a~1b", "value": 1}, {"op": "test", "path": "/m~0n", "value": 2},
                           {"op": "test", "path": "/~01", "value": 3}, {"op": "test", "path": "/", "value": 4}]) == d
    assert fails(d, [{"op": "test", "path": "/m~2n", "value": 2}])
    assert fails(d, [{"op": "add", "path": "nope", "value": 1}])


def test_root_operations():
    assert apply_patch({"a": 1}, [{"op": "add", "path": "", "value": [1]}]) == [1]
    assert apply_patch({"a": 1}, [{"op": "replace", "path": "", "value": None}]) is None
    assert fails({"a": 1}, [{"op": "remove", "path": ""}])


def test_move_copy():
    d = {"a": {"b": [1, 2]}, "c": 0}
    assert apply_patch(d, [{"op": "move", "from": "/a/b/0", "path": "/c"}]) == {"a": {"b": [2]}, "c": 1}
    assert apply_patch(d, [{"op": "move", "from": "/a/b", "path": "/a/b"}]) == d
    assert fails(d, [{"op": "move", "from": "/a", "path": "/a/b/x"}])
    assert apply_patch(d, [{"op": "move", "from": "/a/b", "path": "/a/bb"}]) == {"a": {"bb": [1, 2]}, "c": 0}
    assert apply_patch([1, 2, 3], [{"op": "move", "from": "/0", "path": "/-"}]) == [2, 3, 1]
    assert fails(d, [{"op": "move", "from": "/zz", "path": "/zz"}])
    r = apply_patch(d, [{"op": "copy", "from": "/a", "path": "/z"}])
    r["z"]["b"].append(99)
    assert r["a"] == {"b": [1, 2]}


def test_test_op_equality():
    d = {"n": 1, "t": True, "f": 1.0, "o": {"x": [1, {"y": None}]}}
    assert apply_patch(d, [{"op": "test", "path": "/n", "value": 1.0}, {"op": "test", "path": "/f", "value": 1}]) == d
    assert apply_patch(d, [{"op": "test", "path": "/o", "value": {"x": [1, {"y": None}]}}]) == d
    assert fails(d, [{"op": "test", "path": "/t", "value": 1}])
    assert fails(d, [{"op": "test", "path": "/n", "value": True}])
    assert fails(d, [{"op": "test", "path": "/o", "value": {"x": [1, {"y": None}], "z": 1}}])
    assert fails(d, [{"op": "test", "path": "/missing", "value": None}])


def test_atomic_and_no_aliasing():
    d = {"a": [1], "b": {"c": 1}}
    assert fails(d, [{"op": "add", "path": "/a/-", "value": 2}, {"op": "remove", "path": "/nope"}])
    v = {"deep": [1]}
    ops = [{"op": "add", "path": "/v", "value": v}]
    r = apply_patch(d, ops)
    r["v"]["deep"].append(2)
    r["b"]["c"] = 5
    assert v == {"deep": [1]} and d == {"a": [1], "b": {"c": 1}} and ops[0]["value"] == {"deep": [1]}


def test_malformed_ops():
    for ops in [[{"op": "add", "path": "/x"}], [{"op": "nope", "path": "/x"}], [{"op": "move", "path": "/x"}],
                [{"path": "/x", "value": 1}], [{"op": "remove"}], [{"op": "add", "path": "/x/y", "value": 1}]]:
        assert fails({"a": 1}, ops), ops
    assert apply_patch({"a": 1}, [{"op": "add", "path": "/a", "value": None}]) == {"a": None}
'''},
    reference={
        "jsonpatch.py": '''import copy
import re


class PatchError(ValueError):
    pass


def _tokens(path):
    if not isinstance(path, str):
        raise PatchError("path must be a string")
    if path == "":
        return []
    if not path.startswith("/") or re.search(r"~(?![01])", path):
        raise PatchError("bad pointer %r" % (path,))
    return [t.replace("~1", "/").replace("~0", "~") for t in path[1:].split("/")]


def _index(tok, n, for_add):
    if for_add and tok == "-":
        return n
    if not re.fullmatch(r"0|[1-9][0-9]*", tok):
        raise PatchError("bad index %r" % (tok,))
    i = int(tok)
    if i > n or (i == n and not for_add):
        raise PatchError("index out of range")
    return i


def _get(doc, toks):
    cur = doc
    for t in toks:
        if isinstance(cur, dict):
            if t not in cur:
                raise PatchError("missing member %r" % (t,))
            cur = cur[t]
        elif isinstance(cur, list):
            cur = cur[_index(t, len(cur), False)]
        else:
            raise PatchError("cannot descend into scalar")
    return cur


def _add(doc, toks, value):
    if not toks:
        return value
    parent, last = _get(doc, toks[:-1]), toks[-1]
    if isinstance(parent, dict):
        parent[last] = value
    elif isinstance(parent, list):
        parent.insert(_index(last, len(parent), True), value)
    else:
        raise PatchError("parent is not a container")
    return doc


def _remove(doc, toks):
    if not toks:
        raise PatchError("cannot remove the root")
    parent, last = _get(doc, toks[:-1]), toks[-1]
    if isinstance(parent, dict):
        if last not in parent:
            raise PatchError("missing member")
        return parent.pop(last)
    if isinstance(parent, list):
        return parent.pop(_index(last, len(parent), False))
    raise PatchError("parent is not a container")


def _equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _need(op, key):
    if key not in op:
        raise PatchError("missing %r" % (key,))
    return op[key]


def apply_patch(doc, ops):
    doc = copy.deepcopy(doc)
    for op in ops:
        if not isinstance(op, dict):
            raise PatchError("operation must be an object")
        kind, toks = _need(op, "op"), _tokens(_need(op, "path"))
        if kind == "add":
            doc = _add(doc, toks, copy.deepcopy(_need(op, "value")))
        elif kind == "remove":
            _remove(doc, toks)
        elif kind == "replace":
            value = copy.deepcopy(_need(op, "value"))
            if not toks:
                doc = value
            else:
                _get(doc, toks)
                parent, last = _get(doc, toks[:-1]), toks[-1]
                if isinstance(parent, list):
                    parent[_index(last, len(parent), False)] = value
                else:
                    parent[last] = value
        elif kind in ("move", "copy"):
            src = _tokens(_need(op, "from"))
            if kind == "move":
                if src == toks:
                    _get(doc, src)
                    continue
                if toks[:len(src)] == src:
                    raise PatchError("cannot move a value into itself")
                doc = _add(doc, toks, _remove(doc, src))
            else:
                doc = _add(doc, toks, copy.deepcopy(_get(doc, src)))
        elif kind == "test":
            if not _equal(_get(doc, toks), _need(op, "value")):
                raise PatchError("test failed")
        else:
            raise PatchError("unknown op %r" % (kind,))
    return doc
'''},
)

# ----------------------------------------------------------------------------------------------- H04
task(
    id="H04-build-order", discipline="spec_implementation",
    instruction="Implement `build_order` in graph.py exactly as its docstring specifies.",
    files={
        "graph.py": '''class CycleError(Exception):
    def __init__(self, cycle):
        super().__init__("dependency cycle: " + " -> ".join(cycle))
        self.cycle = cycle


def build_order(deps):
    """`deps` maps each target (str) to an iterable of targets it depends on (duplicates allowed). Targets that only
    appear as dependencies are leaves. Return a list of ALL targets in which every target comes after all of its
    dependencies. Whenever several targets are ready, the lexicographically smallest is placed first, so the
    order is unique.

    If the graph has a cycle (including a target depending on itself), raise CycleError(cycle) where `cycle`
    lists the targets on the cycle: it starts with the lexicographically smallest target ON the cycle, each element
    depends on the next one, and it ends by repeating the first element (e.g. ["a", "b", "a"], or ["x", "x"]).
    Targets that merely lead into a cycle are not part of it. Inputs with cycles contain exactly one cycle.
    `deps` must not be modified.
    """
    raise NotImplementedError
''',
    },
    visible={"tests/test_graph.py": '''from graph import build_order


def test_simple():
    assert build_order({"app": ["lib"], "lib": []}) == ["lib", "app"]
'''},
    hidden={"hidden/test_graph_hidden.py": '''from graph import build_order, CycleError


def cycle_of(deps):
    try:
        build_order(deps)
    except CycleError as e:
        return e.cycle
    return None


def test_order_and_ties():
    deps = {"d": ["b", "c"], "b": ["a"], "c": ["a"], "e": []}
    assert build_order(deps) == ["a", "b", "c", "d", "e"]
    assert build_order({"z": ["y", "y"], "a": ["y"]}) == ["y", "a", "z"]
    assert build_order({"b": ["c"], "a": []}) == ["a", "c", "b"]
    assert build_order({}) == []
    assert build_order({"m": set(), "k": ("m",)}) == ["m", "k"]


def test_ready_set_not_global_sort():
    deps = {"a": ["z"], "b": [], "z": []}
    assert build_order(deps) == ["b", "z", "a"]


def test_cycles():
    assert cycle_of({"a": ["b"], "b": ["a"]}) == ["a", "b", "a"]
    assert cycle_of({"x": ["x"]}) == ["x", "x"]
    assert cycle_of({"c": ["a"], "a": ["b"], "b": ["c"]}) == ["a", "b", "c", "a"]
    assert cycle_of({"start": ["q"], "q": ["r"], "r": ["s"], "s": ["q"], "ok": []}) == ["q", "r", "s", "q"]
    assert cycle_of({"a": ["m"], "m": ["n", "z"], "n": ["m"], "z": []}) == ["m", "n", "m"]


def test_input_untouched():
    deps = {"a": ["b"], "b": []}
    build_order(deps)
    assert deps == {"a": ["b"], "b": []}
'''},
    reference={
        "graph.py": '''import heapq


class CycleError(Exception):
    def __init__(self, cycle):
        super().__init__("dependency cycle: " + " -> ".join(cycle))
        self.cycle = cycle


def build_order(deps):
    graph = {}
    for t, ds in deps.items():
        graph.setdefault(t, set()).update(ds)
        for d in ds:
            graph.setdefault(d, set())
    pending = {t: len(ds) for t, ds in graph.items()}
    users = {t: [] for t in graph}
    for t, ds in graph.items():
        for d in ds:
            users[d].append(t)
    ready = [t for t, n in pending.items() if n == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        t = heapq.heappop(ready)
        order.append(t)
        for u in users[t]:
            pending[u] -= 1
            if pending[u] == 0:
                heapq.heappush(ready, u)
    if len(order) == len(graph):
        return order
    left = {t for t in graph if pending[t] > 0}

    def reaches(src, dst):
        seen, stack = set(), [src]
        while stack:
            n = stack.pop()
            if n == dst:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(d for d in graph[n] if d in left)
        return False

    start = min(t for t in left if any(reaches(d, t) for d in graph[t] if d in left))
    cycle, cur = [start], start
    while True:
        cur = min(d for d in graph[cur] if d in left and reaches(d, start))
        cycle.append(cur)
        if cur == start:
            raise CycleError(cycle)
'''},
)

# ----------------------------------------------------------------------------------------------- H05
task(
    id="H05-retry", discipline="defect_repair",
    instruction=("The `retry` helper misbehaves in production: backoff delays are wrong, it sleeps after the final attempt, "
                 "deadlines are sometimes ignored and the error it raises is misleading. Make `retry` behave exactly as its "
                 "docstring specifies. Keep the signature."),
    files={
        "retry.py": '''import time


class RetryError(Exception):
    def __init__(self, attempts, last):
        super().__init__("gave up after %d attempts: %r" % (attempts, last))
        self.attempts = attempts
        self.last = last


def retry(fn, *, attempts=3, base_delay=0.1, max_delay=2.0, retry_on=(Exception,), deadline=None, clock=None, sleep=None):
    """Call fn() until it returns, and return its result.

    - At most `attempts` calls in total; attempts < 1 raises ValueError before fn is called.
    - Only exceptions that are instances of `retry_on` are retried. Any other exception propagates immediately,
      unchanged (no RetryError, no sleep).
    - Before retry number k (k = 1 before the second call, 2 before the third, ...) sleep exactly
      min(max_delay, base_delay * 2 ** (k - 1)) seconds. Never sleep after the last allowed call.
    - `deadline` (seconds, optional; 0 is a valid deadline) limits total time, measured with clock() from just before
      the first call. If the time already elapsed plus the next delay would reach or exceed the deadline, give up
      instead of sleeping.
    - Giving up raises RetryError whose `.attempts` is the number of calls actually made and whose `.last` is the
      last exception; the RetryError is chained to it (`raise ... from last`).
    - `clock` and `sleep` default to time.monotonic and time.sleep.
    """
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    start = clock()
    last = None
    for k in range(attempts):
        try:
            return fn()
        except retry_on as e:
            last = e
        delay = min(max_delay, base_delay * 2 ** (k + 1))
        if deadline and clock() - start + delay > deadline:
            break
        sleep(delay)
    raise RetryError(attempts, last)
''',
        "client.py": '''from retry import retry


def fetch_config(transport, *, clock=None, sleep=None):
    """Fetch the config, retrying only connection problems, for at most 5 calls and 10 seconds."""
    return retry(transport.get, attempts=5, base_delay=0.5, max_delay=4.0, retry_on=(ConnectionError,), deadline=10,
                 clock=clock, sleep=sleep)
''',
    },
    visible={"tests/test_retry.py": '''from retry import retry


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_backoff_sequence():
    c = Clock()
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise OSError("flaky")
        return "ok"

    assert retry(fn, attempts=3, base_delay=0.1, clock=c.now, sleep=c.sleep) == "ok"
    assert c.sleeps == [0.1, 0.2]
'''},
    hidden={"hidden/test_retry_hidden.py": '''from retry import retry, RetryError
from client import fetch_config


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def failing(exc, counter):
    def fn():
        counter.append(1)
        raise exc
    return fn


def test_no_sleep_after_last_and_error_details():
    c, n = Clock(), []
    err = ConnectionError("down")
    try:
        retry(failing(err, n), attempts=4, base_delay=1, max_delay=3, clock=c.now, sleep=c.sleep)
        assert False
    except RetryError as e:
        assert e.attempts == 4 and e.last is err and e.__cause__ is err
    assert len(n) == 4 and c.sleeps == [1, 2, 3]


def test_non_retryable_propagates():
    c, n = Clock(), []
    try:
        retry(failing(KeyError("k"), n), retry_on=(ConnectionError,), clock=c.now, sleep=c.sleep)
        assert False
    except KeyError:
        pass
    assert len(n) == 1 and c.sleeps == []


def test_deadline():
    c, n = Clock(), []
    try:
        retry(failing(OSError("x"), n), attempts=10, base_delay=1, max_delay=100, deadline=7, clock=c.now, sleep=c.sleep)
        assert False
    except RetryError as e:
        assert e.attempts == 3
    assert c.sleeps == [1, 2]
    c, n = Clock(), []
    try:
        retry(failing(OSError("x"), n), attempts=10, base_delay=1, deadline=3, clock=c.now, sleep=c.sleep)
        assert False
    except RetryError as e:
        assert e.attempts == 2 and c.sleeps == [1]
    c, n = Clock(), []
    try:
        retry(failing(OSError("x"), n), attempts=10, deadline=0, clock=c.now, sleep=c.sleep)
        assert False
    except RetryError as e:
        assert e.attempts == 1 and c.sleeps == []


def test_deadline_counts_time_spent_in_fn():
    c, n = Clock(), []

    def slow():
        n.append(1)
        c.t += 4
        raise OSError("slow")

    try:
        retry(slow, attempts=10, base_delay=1, deadline=10, clock=c.now, sleep=c.sleep)
        assert False
    except RetryError as e:
        assert e.attempts == 2 and c.sleeps == [1]


def test_attempts_validation():
    n = []
    for bad in (0, -1):
        try:
            retry(failing(OSError(), n), attempts=bad, sleep=lambda s: None)
            assert False
        except ValueError:
            pass
    assert n == []
    c = Clock()
    try:
        retry(failing(OSError("x"), n), attempts=1, clock=c.now, sleep=c.sleep)
        assert False
    except RetryError as e:
        assert e.attempts == 1 and c.sleeps == []


def test_client():
    c = Clock()

    class T:
        n = 0

        def get(self):
            T.n += 1
            if T.n < 4:
                raise ConnectionError()
            return {"ok": True}

    assert fetch_config(T(), clock=c.now, sleep=c.sleep) == {"ok": True}
    assert c.sleeps == [0.5, 1.0, 2.0]
'''},
    reference={
        "retry.py": '''import time


class RetryError(Exception):
    def __init__(self, attempts, last):
        super().__init__("gave up after %d attempts: %r" % (attempts, last))
        self.attempts = attempts
        self.last = last


def retry(fn, *, attempts=3, base_delay=0.1, max_delay=2.0, retry_on=(Exception,), deadline=None, clock=None, sleep=None):
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    start = clock()
    calls = 0
    while True:
        calls += 1
        try:
            return fn()
        except retry_on as e:
            last = e
        if calls >= attempts:
            break
        delay = min(max_delay, base_delay * 2 ** (calls - 1))
        if deadline is not None and clock() - start + delay >= deadline:
            break
        sleep(delay)
    raise RetryError(calls, last) from last
'''},
)

# ----------------------------------------------------------------------------------------------- H06
task(
    id="H06-allocate", discipline="spec_implementation",
    instruction="Implement `allocate` in money.py exactly as its docstring specifies.",
    files={
        "money.py": '''def allocate(amount, ratios):
    """Split the integer `amount` (cents; may be negative) into len(ratios) integer parts proportional to `ratios`,
    returned as a list in the same order, whose sum is exactly `amount`.

    Work on the magnitude |amount|: each part first gets its exact proportional share rounded toward zero. The
    cents left over are then handed out one at a time to the parts with the largest fractional remainder of their
    exact share; ties go to the lower index. Finally every part takes the sign of `amount`. A part whose ratio
    is 0 always gets 0. Results must be exact for any size of amount (no floating point error).

    `amount` must be an int (bool is not accepted), else TypeError. `ratios` must be a non-empty list of
    non-negative ints (bools not accepted) with a positive sum, else ValueError.
    """
    raise NotImplementedError
''',
    },
    visible={"tests/test_money.py": '''from money import allocate


def test_basic():
    assert allocate(100, [1, 1, 1]) == [34, 33, 33]
    assert allocate(10, [1, 3]) == [3, 7]
'''},
    hidden={"hidden/test_money_hidden.py": '''from money import allocate


def err(exc, *a):
    try:
        allocate(*a)
    except exc:
        return True
    return False


def test_remainders_and_ties():
    assert allocate(5, [1, 1, 1]) == [2, 2, 1]
    assert allocate(7, [2, 3, 5]) == [1, 2, 4]
    assert allocate(1, [1, 1]) == [1, 0]
    assert allocate(2, [1, 2, 2]) == [0, 1, 1]
    assert allocate(3, [3, 1, 1, 1]) == [2, 1, 0, 0]


def test_negative_amounts_mirror():
    for amt, r in [(100, [1, 1, 1]), (7, [2, 3, 5]), (5, [1, 1, 1]), (999, [7, 3, 1])]:
        assert allocate(-amt, r) == [-x for x in allocate(amt, r)]
    assert allocate(0, [1, 2]) == [0, 0]


def test_zero_ratio_and_exactness():
    assert allocate(10, [0, 1, 0, 1]) == [0, 5, 0, 5]
    assert allocate(1, [0, 1, 1]) == [0, 1, 0]
    big = 10 ** 30 + 7
    parts = allocate(big, [1, 2, 3])
    assert sum(parts) == big and parts == [166666666666666666666666666668, 333333333333333333333333333336, 500000000000000000000000000003]
    p = allocate(2 ** 63 + 1, [1, 1])
    assert p == [2 ** 62 + 1, 2 ** 62]


def test_validation():
    assert err(TypeError, 1.0, [1]) and err(TypeError, True, [1]) and err(TypeError, "5", [1])
    assert err(ValueError, 5, []) and err(ValueError, 5, [0, 0]) and err(ValueError, 5, [1, -1])
    assert err(ValueError, 5, [1.5, 1]) and err(ValueError, 5, [True, 1])
'''},
    reference={
        "money.py": '''def allocate(amount, ratios):
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError("amount must be an int")
    if not isinstance(ratios, list) or not ratios:
        raise ValueError("ratios must be a non-empty list")
    for r in ratios:
        if isinstance(r, bool) or not isinstance(r, int) or r < 0:
            raise ValueError("ratios must be non-negative ints")
    total = sum(ratios)
    if total <= 0:
        raise ValueError("ratios must have a positive sum")
    mag = abs(amount)
    shares = [divmod(mag * r, total) for r in ratios]
    parts = [q for q, _ in shares]
    left = mag - sum(parts)
    for i in sorted(range(len(ratios)), key=lambda i: (-shares[i][1], i))[:left]:
        parts[i] += 1
    sign = -1 if amount < 0 else 1
    return [sign * p for p in parts]
'''},
)

# ----------------------------------------------------------------------------------------------- H07
task(
    id="H07-sqlite-rebuild", discipline="data_migration",
    instruction=("Implement `migrate(conn)` in shop.py to upgrade a version-1 database to version 2. In v2 the `orders` table is "
                 "(id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), amount_cents INTEGER NOT NULL) with columns "
                 "in exactly that order: `legacy_flag` is gone and the REAL dollar `amount` becomes `amount_cents`, computed from the "
                 "shortest decimal representation of the stored value (Python's repr of the float) times 100, rounded half away from "
                 "zero (so 1.005 becomes 101 and -1.005 becomes -101). Keep every order id, customer and order item; keep the index "
                 "`idx_orders_customer` on orders(customer_id); `order_items` must still reference `orders` with its ON DELETE "
                 "CASCADE working; PRAGMA foreign_key_check must be clean; the connection's foreign_keys setting must be the same "
                 "afterwards as before. Set the single `schema_version` row to 2. Running migrate on a v2 database does nothing."),
    files={
        "shop.py": '''import sqlite3


def init_v1(conn):
    conn.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                             amount REAL NOT NULL, legacy_flag INTEGER);
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                                  sku TEXT NOT NULL);
        CREATE TABLE schema_version (version INTEGER);
        INSERT INTO schema_version VALUES (1);
    """)


def version(conn):
    return conn.execute("SELECT version FROM schema_version").fetchone()[0]


def migrate(conn):
    raise NotImplementedError
''',
    },
    visible={"tests/test_shop.py": '''import sqlite3
import shop


def test_basic():
    conn = sqlite3.connect(":memory:")
    shop.init_v1(conn)
    conn.execute("INSERT INTO customers VALUES (1, 'ann')")
    conn.execute("INSERT INTO orders VALUES (10, 1, 12.34, 0)")
    conn.commit()
    shop.migrate(conn)
    assert shop.version(conn) == 2
    assert conn.execute("SELECT id, customer_id, amount_cents FROM orders").fetchall() == [(10, 1, 1234)]
'''},
    hidden={"hidden/test_shop_hidden.py": '''import sqlite3
import shop


def populated(fk=True):
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=%s" % ("ON" if fk else "OFF"))
    shop.init_v1(conn)
    conn.executemany("INSERT INTO customers VALUES (?, ?)", [(1, "ann"), (2, "bob")])
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)",
                     [(1, 1, 12.34, 1), (2, 1, 1.005, None), (3, 2, 0.1 + 0.2, 0), (4, 2, -1.005, 0), (5, None, 19.99, 1),
                      (6, 1, 5, 0), (7, 2, -2.5, 0)])
    conn.executemany("INSERT INTO order_items (order_id, sku) VALUES (?, ?)", [(1, "a"), (1, "b"), (2, "c"), (7, "d")])
    conn.commit()
    return conn


def test_amounts_and_rows():
    conn = populated()
    shop.migrate(conn)
    got = conn.execute("SELECT id, customer_id, amount_cents FROM orders ORDER BY id").fetchall()
    assert got == [(1, 1, 1234), (2, 1, 101), (3, 2, 30), (4, 2, -101), (5, None, 1999), (6, 1, 500), (7, 2, -250)], got
    assert conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 4
    assert conn.execute("SELECT * FROM customers ORDER BY id").fetchall() == [(1, "ann"), (2, "bob")]


def test_schema_shape():
    conn = populated()
    shop.migrate(conn)
    cols = [(r[1], r[2].upper(), r[3], r[5]) for r in conn.execute("PRAGMA table_info(orders)")]
    assert cols == [("id", "INTEGER", 0, 1), ("customer_id", "INTEGER", 0, 0), ("amount_cents", "INTEGER", 1, 0)], cols
    idx = {r[1] for r in conn.execute("PRAGMA index_list(orders)")}
    assert "idx_orders_customer" in idx
    assert [r[2] for r in conn.execute("PRAGMA index_info(idx_orders_customer)")] == ["customer_id"]
    fks = [(r[2], r[3], r[4]) for r in conn.execute("PRAGMA foreign_key_list(orders)")]
    assert fks == [("customers", "customer_id", "id")]
    item_fks = [(r[2], r[3], r[4], r[6]) for r in conn.execute("PRAGMA foreign_key_list(order_items)")]
    assert item_fks == [("orders", "order_id", "id", "CASCADE")], item_fks
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"customers", "orders", "order_items", "schema_version"}, tables


def test_integrity_and_cascade():
    conn = populated()
    shop.migrate(conn)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.execute("DELETE FROM orders WHERE id = 1")
    conn.commit()
    assert conn.execute("SELECT sku FROM order_items ORDER BY sku").fetchall() == [("c",), ("d",)]


def test_fk_setting_preserved_when_off():
    conn = populated(fk=False)
    shop.migrate(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0


def test_idempotent_and_version():
    conn = populated()
    shop.migrate(conn)
    before = conn.execute("SELECT * FROM orders ORDER BY id").fetchall()
    shop.migrate(conn)
    assert conn.execute("SELECT * FROM orders ORDER BY id").fetchall() == before
    assert shop.version(conn) == 2 and conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1


def test_persisted():
    import os, tempfile
    path = os.path.join(tempfile.mkdtemp(), "shop.db")
    conn = sqlite3.connect(path)
    shop.init_v1(conn)
    conn.execute("INSERT INTO customers VALUES (1, 'ann')")
    conn.execute("INSERT INTO orders VALUES (1, 1, 2.5, 0)")
    conn.commit()
    shop.migrate(conn)
    conn.close()
    again = sqlite3.connect(path)
    assert again.execute("SELECT amount_cents FROM orders").fetchall() == [(250,)]
    assert shop.version(again) == 2
'''},
    reference={
        "shop.py": '''import sqlite3
from decimal import Decimal, ROUND_HALF_UP


def init_v1(conn):
    conn.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                             amount REAL NOT NULL, legacy_flag INTEGER);
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                                  sku TEXT NOT NULL);
        CREATE TABLE schema_version (version INTEGER);
        INSERT INTO schema_version VALUES (1);
    """)


def version(conn):
    return conn.execute("SELECT version FROM schema_version").fetchone()[0]


def _cents(amount):
    return int((Decimal(repr(float(amount))) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def migrate(conn):
    if version(conn) >= 2:
        return
    fk_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("CREATE TABLE orders_new (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), "
                     "amount_cents INTEGER NOT NULL)")
        rows = conn.execute("SELECT id, customer_id, amount FROM orders").fetchall()
        conn.executemany("INSERT INTO orders_new VALUES (?, ?, ?)", [(i, c, _cents(a)) for i, c, a in rows])
        conn.execute("DROP TABLE orders")
        conn.execute("ALTER TABLE orders_new RENAME TO orders")
        conn.execute("CREATE INDEX idx_orders_customer ON orders(customer_id)")
        conn.execute("UPDATE schema_version SET version = 2")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys=%s" % ("ON" if fk_on else "OFF"))
'''},
)

# ----------------------------------------------------------------------------------------------- H08
task(
    id="H08-glob", discipline="spec_implementation",
    instruction="Implement `glob_match` in globber.py exactly as its docstring specifies.",
    files={
        "globber.py": r'''def glob_match(pattern, path):
    """Return True if the "/"-separated relative `path` matches `pattern` (case-sensitive, whole path).

    Pattern syntax:
    - `?` matches exactly one character other than "/".
    - `*` matches zero or more characters other than "/".
    - `[...]` matches one character other than "/" that is in the set; `[!...]` one that is NOT in the set.
      The set holds literal characters and ranges `a-z`. A `]` right after `[` or `[!` is a literal member, and a
      `-` first or last in the set is literal. Backslash has no special meaning inside a set.
      An unterminated `[` raises ValueError.
    - `\x` (backslash then any character) matches x literally. A trailing lone backslash raises ValueError.
    - A pattern segment (text between unescaped "/" outside sets) that is exactly `**` matches zero or more whole
      path segments. Elsewhere `**` is just two `*`.
    - Any other character matches itself.
    Matching must stay fast for patterns with many `*` or `**` (no exponential backtracking).
    """
    raise NotImplementedError
''',
    },
    visible={"tests/test_glob.py": '''from globber import glob_match


def test_basic():
    assert glob_match("src/*.py", "src/app.py")
    assert not glob_match("src/*.py", "src/app.txt")
'''},
    hidden={"hidden/test_glob_hidden.py": r'''import time
from globber import glob_match


def bad(p):
    try:
        glob_match(p, "x")
    except ValueError:
        return True
    return False


def test_star_and_question():
    assert not glob_match("*.txt", "dir/a.txt") and glob_match("*/*.txt", "dir/a.txt")
    assert glob_match("a?c", "abc") and not glob_match("a?c", "a/c") and not glob_match("a?c", "ac")
    assert glob_match("a*b", "ab") and glob_match("a**b", "axxb") and not glob_match("a**b", "a/b")
    assert not glob_match("src/*.py", "src/app.pyc") and not glob_match("src/*.py", "srcx/app.py")


def test_globstar():
    assert glob_match("src/**/*.py", "src/a.py") and glob_match("src/**/*.py", "src/x/y/a.py")
    assert glob_match("**", "a") and glob_match("**", "a/b/c")
    assert glob_match("**/b", "b") and glob_match("**/b", "x/y/b") and not glob_match("**/b", "ab")
    assert glob_match("a/**/b/**/c", "a/b/c") and glob_match("a/**/b/**/c", "a/x/b/y/z/c") and not glob_match("a/**/b/**/c", "a/c")
    assert glob_match("a/**", "a/b") and not glob_match("a/**", "ab")
    assert not glob_match("x**/y", "x/z/y") and glob_match("x**/y", "xz/y")


def test_sets():
    assert glob_match("[abc]x", "bx") and not glob_match("[abc]x", "dx")
    assert glob_match("[!abc]x", "dx") and not glob_match("[!abc]x", "ax") and not glob_match("[!abc]x", "x")
    assert glob_match("[a-c][0-9]", "b7") and not glob_match("[a-c][0-9]", "d7")
    assert glob_match("[]a]", "]") and glob_match("[]a]", "a") and not glob_match("[]a]", "b")
    assert glob_match("[!]a]", "b") and not glob_match("[!]a]", "]")
    assert glob_match("[a-]", "-") and glob_match("[-a]", "-") and not glob_match("[a-]", "b")
    assert glob_match("[\\]", "\\") and glob_match("x[*]", "x*") and not glob_match("x[*]", "xy")
    assert not glob_match("a[/]b", "a/b") and not glob_match("a[!x]b", "a/b")
    assert glob_match("[a/b]x/y", "ax/y")


def test_escapes():
    assert glob_match(r"a\*b", "a*b") and not glob_match(r"a\*b", "axb")
    assert glob_match(r"\[x", "[x") and glob_match(r"\?", "?") and not glob_match(r"\?", "a")
    assert glob_match(r"\*\*/x", "**/x") and not glob_match(r"\*\*/x", "a/b/x")


def test_errors():
    assert bad("[") and bad("a[b") and bad("[!") and bad("[]") and bad("x\\") and bad("ok/[abc")


def test_no_exponential_backtracking():
    t = time.monotonic()
    assert not glob_match("a*a*a*a*a*a*a*a*a*b", "a" * 60)
    assert not glob_match("**/**/**/**/**/**/**/z", "/".join("a" * 25))
    assert glob_match("*a*a*a*a*a*a*a*a*", "a" * 60)
    assert time.monotonic() - t < 5
'''},
    reference={
        "globber.py": r'''def _parse(pattern):
    segs, toks, raw = [], [], ""
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "/":
            segs.append((raw == "**", toks))
            toks, raw = [], ""
            i += 1
        elif c == "\\":
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            toks.append(("lit", pattern[i + 1]))
            raw += pattern[i:i + 2]
            i += 2
        elif c == "*":
            if not toks or toks[-1] != ("star",):
                toks.append(("star",))
            raw += c
            i += 1
        elif c == "?":
            toks.append(("one",))
            raw += c
            i += 1
        elif c == "[":
            j, neg = i + 1, False
            if j < n and pattern[j] == "!":
                neg, j = True, j + 1
            items, first = [], True
            while True:
                if j >= n:
                    raise ValueError("unterminated [")
                ch = pattern[j]
                if ch == "]" and not first:
                    break
                if j + 2 < n and pattern[j + 1] == "-" and pattern[j + 2] != "]":
                    items.append((ch, pattern[j + 2]))
                    j += 3
                else:
                    items.append((ch, ch))
                    j += 1
                first = False
            toks.append(("set", tuple(items), neg))
            raw += pattern[i:j + 1]
            i = j + 1
        else:
            toks.append(("lit", c))
            raw += c
            i += 1
    segs.append((raw == "**", toks))
    return segs


def _seg_match(toks, s):
    memo = {}

    def m(i, j):
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(toks):
            r = j == len(s)
        elif toks[i][0] == "star":
            r = m(i + 1, j) or (j < len(s) and m(i, j + 1))
        elif j == len(s):
            r = False
        else:
            t, c = toks[i], s[j]
            if t[0] == "lit":
                ok = c == t[1]
            elif t[0] == "one":
                ok = True
            else:
                ok = any(lo <= c <= hi for lo, hi in t[1]) != t[2]
            r = ok and m(i + 1, j + 1)
        memo[key] = r
        return r

    return m(0, 0)


def glob_match(pattern, path):
    segs = _parse(pattern)
    parts = path.split("/")
    memo = {}

    def m(i, j):
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(segs):
            r = j == len(parts)
        elif segs[i][0]:
            r = m(i + 1, j) or (j < len(parts) and m(i, j + 1))
        else:
            r = j < len(parts) and _seg_match(segs[i][1], parts[j]) and m(i + 1, j + 1)
        memo[key] = r
        return r

    return m(0, 0)
'''},
)

# ----------------------------------------------------------------------------------------------- H09
task(
    id="H09-ledger-root-cause", discipline="root_cause_investigation",
    instruction=("Finance reports three symptoms in the ledger service: (1) after a deposit of 0.10 and one of 0.20, account B shows "
                 "0.30000000000000004 instead of 0.30; (2) a malformed transfer with no target still took money out of the source "
                 "account; (3) an event that was rejected once (for example for insufficient funds) is silently ignored when it is "
                 "retried after the account was topped up. Find and fix the root causes so that the ledger follows every rule in "
                 "the Ledger docstring and parse_event's docstring."),
    files={
        "events.py": '''from collections import namedtuple

Event = namedtuple("Event", "id kind account target amount")


def parse_event(raw):
    """Validate a raw event dict and return an Event.

    Required keys: "id" (non-empty str), "kind" ("deposit", "withdraw" or "transfer"), "account" (non-empty str) and
    "amount" (a str of digits, optionally followed by "." and one or two digits, e.g. "5", "0.1", "12.34"; its value
    must be > 0). A transfer also needs "target" (non-empty str, different from "account"); other kinds ignore it.
    Anything else (missing keys, wrong types, "1e2", "1.234", "-5", "0.00", ...) raises ValueError.
    """
    kind = raw["kind"]
    if kind not in ("deposit", "withdraw", "transfer"):
        raise ValueError("bad kind")
    amount = float(raw["amount"])
    if amount <= 0:
        raise ValueError("amount must be positive")
    return Event(raw["id"], kind, raw["account"], raw.get("target"), amount)
''',
        "ledger.py": '''from events import parse_event


class Ledger:
    """In-memory account ledger.

    - balance(acct) returns a decimal.Decimal with exactly two decimal places; unknown accounts have Decimal("0.00").
    - apply(raw) returns True when the event is applied, or False when an event with the same id was already APPLIED
      (it is then ignored).
    - Invalid events (see events.parse_event) and events that would make any balance negative raise ValueError,
      change nothing, and are not remembered: a later event with the same id is processed normally.
    - withdraw and transfer may bring a balance down to exactly zero.
    - A transfer moves the amount from `account` to `target` atomically.
    """

    def __init__(self):
        self._bal = {}
        self._seen = set()

    def balance(self, acct):
        return self._bal.get(acct, 0)

    def apply(self, raw):
        if raw.get("id") in self._seen:
            return False
        self._seen.add(raw.get("id"))
        ev = parse_event(raw)
        if ev.kind == "deposit":
            self._credit(ev.account, ev.amount)
        elif ev.kind == "withdraw":
            self._debit(ev.account, ev.amount)
        else:
            self._debit(ev.account, ev.amount)
            self._credit(ev.target, ev.amount)
        return True

    def _credit(self, acct, amount):
        self._bal[acct] = self._bal.get(acct, 0) + amount

    def _debit(self, acct, amount):
        bal = self._bal.get(acct, 0)
        if bal - amount <= 0:
            raise ValueError("insufficient funds")
        self._bal[acct] = bal - amount
''',
    },
    visible={"tests/test_ledger.py": '''from ledger import Ledger


def test_cents_are_exact():
    l = Ledger()
    l.apply({"id": "1", "kind": "deposit", "account": "B", "amount": "0.10"})
    l.apply({"id": "2", "kind": "deposit", "account": "B", "amount": "0.20"})
    assert str(l.balance("B")) == "0.30"
'''},
    hidden={"hidden/test_ledger_hidden.py": '''from decimal import Decimal
from ledger import Ledger


def rejects(l, raw):
    before = {a: l.balance(a) for a in ("A", "B", "C", "None")}
    try:
        l.apply(raw)
    except ValueError:
        assert {a: l.balance(a) for a in before} == before
        return True
    return False


def ev(i, kind, acct, amount, target=None):
    d = {"id": i, "kind": kind, "account": acct, "amount": amount}
    if target is not None:
        d["target"] = target
    return d


def test_balances_are_two_place_decimals():
    l = Ledger()
    assert isinstance(l.balance("nobody"), Decimal) and str(l.balance("nobody")) == "0.00"
    l.apply(ev("1", "deposit", "A", "5"))
    assert str(l.balance("A")) == "5.00"
    l.apply(ev("2", "withdraw", "A", "0.1"))
    assert str(l.balance("A")) == "4.90"


def test_transfer_validation_is_atomic():
    l = Ledger()
    l.apply(ev("d", "deposit", "A", "10"))
    assert rejects(l, ev("t1", "transfer", "A", "3"))
    assert rejects(l, ev("t2", "transfer", "A", "3", target="A"))
    assert rejects(l, ev("t3", "transfer", "A", "3", target=""))
    assert rejects(l, ev("t4", "transfer", "A", "10.01", target="B"))
    assert l.apply(ev("t5", "transfer", "A", "10", target="B"))
    assert str(l.balance("A")) == "0.00" and str(l.balance("B")) == "10.00"


def test_rejected_events_can_be_retried():
    l = Ledger()
    assert rejects(l, ev("w", "withdraw", "A", "5"))
    l.apply(ev("d", "deposit", "A", "5"))
    assert l.apply(ev("w", "withdraw", "A", "5")) is True
    assert str(l.balance("A")) == "0.00"
    assert rejects(l, ev("bad", "deposit", "A", "1.234"))
    assert l.apply(ev("bad", "deposit", "A", "1.23")) is True


def test_duplicates_of_applied_events():
    l = Ledger()
    assert l.apply(ev("x", "deposit", "A", "1")) is True
    assert l.apply(ev("x", "deposit", "A", "1")) is False
    assert str(l.balance("A")) == "1.00"


def test_parse_rules():
    l = Ledger()
    for bad in [ev("a", "deposit", "A", "1e2"), ev("b", "deposit", "A", "-5"), ev("c", "deposit", "A", "0.00"),
                ev("d", "deposit", "A", "0"), ev("e", "deposit", "A", 5), ev("f", "deposit", "A", ".5"),
                ev("g", "deposit", "A", "5."), ev("h", "refund", "A", "5"), ev("", "deposit", "A", "5"),
                ev("i", "deposit", "", "5"), {"id": "j", "kind": "deposit", "account": "A"},
                {"kind": "deposit", "account": "A", "amount": "1"}, ev("k", "deposit", "A", " 5")]:
        assert rejects(l, bad), bad
    assert l.apply(ev("ok", "deposit", "A", "007.5")) and str(l.balance("A")) == "7.50"
    assert l.apply(ev("ok2", "deposit", "C", "1", target="ignored"))
'''},
    reference={
        "events.py": '''import re
from collections import namedtuple
from decimal import Decimal

Event = namedtuple("Event", "id kind account target amount")

_AMOUNT = re.compile(r"[0-9]+(?:\\.[0-9]{1,2})?")


def _text(raw, key):
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("bad or missing %r" % (key,))
    return value


def parse_event(raw):
    if not isinstance(raw, dict):
        raise ValueError("event must be a dict")
    eid, kind, account = _text(raw, "id"), _text(raw, "kind"), _text(raw, "account")
    if kind not in ("deposit", "withdraw", "transfer"):
        raise ValueError("bad kind")
    amount = raw.get("amount")
    if not isinstance(amount, str) or not _AMOUNT.fullmatch(amount):
        raise ValueError("bad amount")
    value = Decimal(amount)
    if value <= 0:
        raise ValueError("amount must be positive")
    target = None
    if kind == "transfer":
        target = _text(raw, "target")
        if target == account:
            raise ValueError("transfer to same account")
    return Event(eid, kind, account, target, value)
''',
        "ledger.py": '''from decimal import Decimal
from events import parse_event

_CENT = Decimal("0.01")


class Ledger:
    def __init__(self):
        self._bal = {}
        self._seen = set()

    def balance(self, acct):
        return self._bal.get(acct, Decimal(0)).quantize(_CENT)

    def apply(self, raw):
        ev = parse_event(raw)
        if ev.id in self._seen:
            return False
        get = lambda a: self._bal.get(a, Decimal(0))
        changes = {}
        if ev.kind == "deposit":
            changes[ev.account] = get(ev.account) + ev.amount
        else:
            changes[ev.account] = get(ev.account) - ev.amount
            if ev.kind == "transfer":
                changes[ev.target] = get(ev.target) + ev.amount
        if any(v < 0 for v in changes.values()):
            raise ValueError("insufficient funds")
        self._bal.update(changes)
        self._seen.add(ev.id)
        return True
'''},
)

# ----------------------------------------------------------------------------------------------- H10
task(
    id="H10-perf-report", discipline="performance",
    instruction=("The nightly report job times out on production-size inputs (hundreds of thousands of rows). `top_k` and "
                 "`merge_ranges` in report.py are correct but far too slow. Make both fast enough for 200,000-item inputs "
                 "(well under a second each) without changing their behaviour in any way, including ordering, tie-breaking, "
                 "return types, error handling, and not modifying the inputs."),
    files={
        "report.py": '''def top_k(scores, k):
    """Return the k (user, total) pairs with the highest totals, highest first; ties are broken by user ascending.
    `scores` is a list of (user, points) pairs; a user may appear many times and their points are summed.
    k <= 0 returns []. If fewer than k users exist, all are returned."""
    totals = []
    for user, points in scores:
        for i, (u, s) in enumerate(totals):
            if u == user:
                totals[i] = (u, s + points)
                break
        else:
            totals.append((user, points))
    result = []
    while totals and len(result) < k:
        best = totals[0]
        for t in totals:
            if t[1] > best[1] or (t[1] == best[1] and t[0] < best[0]):
                best = t
        totals.remove(best)
        result.append(best)
    return result


def merge_ranges(ranges):
    """Merge closed integer ranges (a, b) with a <= b. Ranges that overlap or touch (e.g. (1, 2) and (3, 4)) are merged.
    Returns a sorted list of (start, end) tuples. A range with a > b raises ValueError."""
    out = []
    for a, b in ranges:
        if a > b:
            raise ValueError("bad range")
        out.append((a, b))
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                (a, b), (c, d) = out[i], out[j]
                if a <= d + 1 and c <= b + 1:
                    out[i] = (min(a, c), max(b, d))
                    del out[j]
                    changed = True
                    break
            if changed:
                break
    return sorted(out)
''',
    },
    visible={"tests/test_report.py": '''import time
from report import top_k, merge_ranges


def test_small():
    assert top_k([("a", 1), ("b", 3), ("a", 5)], 1) == [("a", 6)]
    assert merge_ranges([(5, 6), (1, 2), (3, 3)]) == [(1, 3), (5, 6)]


def test_medium_input_speed():
    scores = [("u%d" % (i % 8000), i % 13) for i in range(20000)]
    ranges = [(i * 10, i * 10 + 3) for i in range(5000)]
    t = time.monotonic()
    top_k(scores, 10)
    merge_ranges(ranges)
    assert time.monotonic() - t < 2
'''},
    hidden={"hidden/test_report_hidden.py": '''import random
import time
from report import top_k, merge_ranges


def test_top_k_semantics():
    s = [("b", 2), ("a", 2), ("c", 5), ("b", 0), ("d", -1)]
    assert top_k(s, 3) == [("c", 5), ("a", 2), ("b", 2)]
    assert top_k(s, 0) == [] and top_k(s, -3) == []
    assert top_k(s, 99) == [("c", 5), ("a", 2), ("b", 2), ("d", -1)]
    assert top_k([], 3) == []
    original = list(s)
    top_k(s, 2)
    assert s == original


def test_merge_semantics():
    assert merge_ranges([]) == []
    assert merge_ranges([(1, 5), (2, 3)]) == [(1, 5)]
    assert merge_ranges([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]
    assert merge_ranges([(-5, -3), (-2, 0), (10, 10), (10, 10)]) == [(-5, 0), (10, 10)]
    r = [[3, 4], [1, 2]]
    assert merge_ranges(r) == [(1, 4)] and r == [[3, 4], [1, 2]]
    assert all(type(x) is tuple for x in merge_ranges([[1, 2], [7, 8]]))
    try:
        merge_ranges([(1, 2), (5, 4)])
        assert False
    except ValueError:
        pass


def test_large_inputs_are_fast():
    rnd = random.Random(7)
    scores = [("user%05d" % rnd.randrange(60000), rnd.randrange(-50, 100)) for _ in range(200000)]
    ranges = []
    for _ in range(200000):
        a = rnd.randrange(0, 10 ** 7)
        ranges.append((a, a + rnd.randrange(0, 40)))
    t = time.monotonic()
    best = top_k(scores, 25)
    merged = merge_ranges(ranges)
    assert time.monotonic() - t < 5
    totals = {}
    for u, p in scores:
        totals[u] = totals.get(u, 0) + p
    assert best == sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:25]
    assert sum(1 for _ in merged) > 1000 and merged == sorted(merged)
    assert all(merged[i][1] + 1 < merged[i + 1][0] for i in range(len(merged) - 1))
'''},
    reference={
        "report.py": '''import heapq


def top_k(scores, k):
    if k <= 0:
        return []
    totals = {}
    for user, points in scores:
        totals[user] = totals.get(user, 0) + points
    return heapq.nsmallest(k, totals.items(), key=lambda t: (-t[1], t[0]))


def merge_ranges(ranges):
    items = []
    for a, b in ranges:
        if a > b:
            raise ValueError("bad range")
        items.append((a, b))
    items.sort()
    out = []
    for a, b in items:
        if out and a <= out[-1][1] + 1:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out
'''},
)
