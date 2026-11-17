from orchestrator_runtime.watchdog import Action, Ladder, Policy, StallTracker


def test_stall_tracker_counts_only_running_work_without_progress():
    t = StallTracker()
    assert t.update("w", 0, 1, 10) == 0
    assert t.update("w", 60, 1, 10) == 60          # running, nothing moved
    assert t.update("w", 90, 1, 11) == 0           # progress resets
    assert t.update("w", 200, 0, 11) == 0          # idle engine is never stalled
    assert t.update("w", 300, None, 11) == 0       # unknown reading is never a stall
    assert t.update("w", 310, 1, None) == 0


def drive(ladder, now, stalled, results=None):
    """Ask, then report success for whatever was asked; returns the list of actions taken."""
    taken = []
    for _ in range(10):
        action = ladder.decide("w", stalled, now)
        if action is None:
            break
        taken.append(action)
        ladder.performed("w", action, now, (results or {}).get(action, True))
        if action in (Action.UNDRAIN, Action.ALERT):  # a restarted worker's stall clock starts over
            break
    return taken


def test_ladder_order_drain_then_stop_restart_readmit():
    p = Policy(stuck_after_s=120, drain_wait_s=30)
    ladder = Ladder(p)
    assert drive(ladder, 0, 119) == []                       # not stuck yet
    assert drive(ladder, 1, 121) == [Action.DRAIN]           # stuck: stop routing first
    assert drive(ladder, 20, 140) == []                      # drain_wait not elapsed
    assert drive(ladder, 40, 160) == [Action.STOP, Action.RESTART, Action.UNDRAIN]
    assert ladder.phase("w") == "healthy"


def test_ladder_forces_kill_only_after_graceful_stop_fails():
    ladder = Ladder(Policy(drain_wait_s=0))
    taken = drive(ladder, 0, 500, results={Action.STOP: False})
    assert taken == [Action.DRAIN, Action.STOP, Action.KILL, Action.RESTART, Action.UNDRAIN]


def test_ladder_undrains_a_worker_that_recovered_while_draining():
    ladder = Ladder(Policy(drain_wait_s=30))
    assert drive(ladder, 0, 200) == [Action.DRAIN]
    assert drive(ladder, 10, 0) == [Action.UNDRAIN]          # progress resumed before any stop
    assert ladder.phase("w") == "healthy"


def test_ladder_limits_restarts_per_hour_then_abandons_and_alerts_once():
    ladder = Ladder(Policy(drain_wait_s=0, max_restarts_per_hour=2))
    now = 0.0
    for _ in range(2):
        assert drive(ladder, now, 500)[-1] is Action.UNDRAIN
        now += 100
    assert drive(ladder, now, 500) == [Action.ALERT]
    assert ladder.phase("w") == "abandoned"
    assert drive(ladder, now + 10, 500) == []                # stays out of rotation, no repeat alerts
    ladder.reset("w")
    assert drive(ladder, now + 4000, 500)[0] is Action.DRAIN  # old restarts aged out, human reset


def test_failed_restart_or_kill_abandons_the_worker():
    ladder = Ladder(Policy(drain_wait_s=0))
    drive(ladder, 0, 500, results={Action.STOP: False, Action.KILL: False})
    assert ladder.phase("w") == "abandoned"


# ------------------------------------------------------------------------------------------------ executor
class FakeGateway:
    def __init__(self, stalled):
        self.stalled_map, self.calls, self.ready_now = stalled, [], True

    def stalled(self): return dict(self.stalled_map)
    def drain(self, w): self.calls.append(("drain", w)); return True
    def undrain(self, w): self.calls.append(("undrain", w)); self.stalled_map[w] = 0.0; return True
    def ready(self, w): return self.ready_now


class FakeSystemd:
    def __init__(self, stop_ok=True): self.calls, self.stop_ok = [], stop_ok
    def stop(self, u): self.calls.append(("stop", u)); return self.stop_ok
    def kill(self, u): self.calls.append(("kill", u)); return True
    def restart(self, u): self.calls.append(("restart", u)); return True


def test_parse_stalled_reads_the_gateway_series_by_worker():
    from scripts.worker_watchdog import parse_stalled
    text = ('# TYPE aihost_engine_stalled_seconds gauge\n'
            'aihost_engine_stalled_seconds{worker_id="w1",pool="lead",engine="llama.cpp"} 150\n'
            'aihost_engine_stalled_seconds{worker_id="w2",pool="deep",engine="llama.cpp"} 0\n'
            'aihost_engine_requests_running{worker_id="w1",pool="lead",engine="llama.cpp"} 1\n')
    assert parse_stalled(text) == {"w1": 150.0, "w2": 0.0}


def test_dry_run_logs_only_the_next_rung_and_touches_nothing():
    from scripts.worker_watchdog import run_once
    gw, sd, log = FakeGateway({"w1": 500}), FakeSystemd(), []
    recs = run_once(gw, sd, Ladder(Policy()), {"w1": "u1"}, 0.0, apply=False, evidence=log.append, verify_started={})
    assert [r["action"] for r in recs] == ["drain"] and recs[0]["applied"] is False
    assert gw.calls == [] and sd.calls == []


def test_apply_walks_the_ladder_in_order_and_records_every_rung():
    from scripts.worker_watchdog import run_once
    gw, sd, log = FakeGateway({"w1": 500}), FakeSystemd(), []
    ladder, verify = Ladder(Policy(drain_wait_s=0)), {}
    run_once(gw, sd, ladder, {"w1": "u1"}, 0.0, apply=True, evidence=log.append, verify_started=verify)
    assert [r["action"] for r in log] == ["drain", "stop", "restart", "undrain"]
    assert gw.calls == [("drain", "w1"), ("undrain", "w1")] and sd.calls == [("stop", "u1"), ("restart", "u1")]
    assert ladder.phase("w1") == "healthy" and all(r["ok"] for r in log)


def test_apply_forces_a_kill_when_the_graceful_stop_fails_and_never_touches_other_workers():
    from scripts.worker_watchdog import run_once
    gw, sd, log = FakeGateway({"w1": 500, "w2": 0}), FakeSystemd(stop_ok=False), []
    run_once(gw, sd, Ladder(Policy(drain_wait_s=0)), {"w1": "u1", "w2": "u2"}, 0.0, apply=True, evidence=log.append, verify_started={})
    assert [c[0] for c in sd.calls] == ["stop", "kill", "restart"] and all(c[1] == "u1" for c in sd.calls)


def test_a_worker_that_never_becomes_ready_is_abandoned_not_readmitted():
    from scripts.worker_watchdog import READY_WAIT_S, run_once
    gw, sd, log = FakeGateway({"w1": 500}), FakeSystemd(), []
    gw.ready_now = False
    ladder, verify = Ladder(Policy(drain_wait_s=0)), {}
    run_once(gw, sd, ladder, {"w1": "u1"}, 0.0, apply=True, evidence=log.append, verify_started=verify)
    assert ladder.phase("w1") == "verifying" and ("undrain", "w1") not in gw.calls
    run_once(gw, sd, ladder, {"w1": "u1"}, READY_WAIT_S + 1, apply=True, evidence=log.append, verify_started=verify)
    assert ladder.phase("w1") == "abandoned" and log[-1]["action"] == "abandon"
