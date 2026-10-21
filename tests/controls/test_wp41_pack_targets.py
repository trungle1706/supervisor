"""WP41 (D28): a pack result on any target bound to the agent is evidence for a control.

The benchmark stored a failing `pii_canary` on the `traces:` target; the reader took the `agent`
target only, so the control stayed `no_data` instead of `failing`.
"""

from __future__ import annotations

from supervisor.controls.harness_env import CtlEnv


def _status(env: CtlEnv, control: str, agent: str = "pay") -> dict[str, object]:
    env.controls.run_status()
    comp = env.controls.agent_compliance(agent)
    return next(c for c in comp["controls"] if c["control_id"] == control)


def _setup(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-A", evidence=[("pack", "pack_a")])


def test_failing_pack_on_the_traces_target_is_failing_not_no_data(env: CtlEnv) -> None:
    _setup(env)
    env.pack("pay", "pack_a", "fail", env.window_time(), target_kind="traces")
    s = _status(env, "CTL-A")
    assert (s["status"], s["reason"]) == ("failing", "source_failing")


def test_ok_pack_on_the_traces_target_is_working(env: CtlEnv) -> None:
    _setup(env)
    env.pack("pay", "pack_a", "ok", env.window_time(), target_kind="traces")
    assert _status(env, "CTL-A")["status"] == "working"


def test_a_fail_on_either_target_wins_over_an_ok_on_the_other(env: CtlEnv) -> None:
    _setup(env)
    env.pack("pay", "pack_a", "ok", env.window_time(), target_kind="agent")
    env.pack("pay", "pack_a", "fail", env.window_time(), target_kind="traces")
    assert _status(env, "CTL-A")["status"] == "failing"


def test_the_agent_target_still_counts_as_before(env: CtlEnv) -> None:
    _setup(env)
    env.pack("pay", "pack_a", "fail", env.window_time())
    assert _status(env, "CTL-A")["status"] == "failing"


def test_mock_traces_result_and_a_judge_target_are_not_evidence(env: CtlEnv) -> None:
    _setup(env)
    env.pack("pay", "pack_a", "fail", env.window_time(), mock=True, target_kind="traces")
    env.pack("pay", "pack_a", "fail", env.window_time(), target_kind="judge")
    assert _status(env, "CTL-A")["status"] == "no_data"


def test_a_traces_result_of_another_agent_does_not_leak_across(env: CtlEnv) -> None:
    _setup(env)
    env.agent("svc")
    env.pack("svc", "pack_a", "fail", env.window_time(), target_kind="traces")
    assert _status(env, "CTL-A")["status"] == "no_data"
