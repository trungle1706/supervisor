from __future__ import annotations

from types import SimpleNamespace

from supervisor.ops.readiness import readiness


class _State:
    def __init__(self, fail=False):
        self.fail = fail

    def query(self, *a, **k):
        if self.fail:
            raise RuntimeError("secret-host.bank.local /var/db/x.sqlite")
        return []


def _rt(fail=False, key="k1"):
    return SimpleNamespace(
        adapters=SimpleNamespace(state=_State(fail)),
        chain=SimpleNamespace(signer=SimpleNamespace(key_id=key)),
    )


S = SimpleNamespace(scheduler_on=True)


def test_ready_ok_with_scheduler_states():
    r = readiness(S, _rt(), SimpleNamespace(running=True))
    assert r["ready"] and r["checks"]["scheduler"] == "running"
    assert readiness(SimpleNamespace(scheduler_on=False), _rt())["checks"]["scheduler"] == "off"
    assert (
        readiness(S, _rt(), SimpleNamespace(running=False))["checks"]["scheduler"] == "not-leader"
    )


def test_failures_named_without_error_text():
    r = readiness(S, _rt(fail=True, key=""))
    assert not r["ready"] and r["failed"] == ["store", "signer"]
    assert "secret-host" not in str(r) and ".sqlite" not in str(r)
    assert readiness(S, None)["failed"] == ["runtime", "store", "signer"]
