from __future__ import annotations

import re

from supervisor.jobs import decision_rollup

from .wp39_fixtures import plant, v2adapters, v2console  # noqa: F401


def test_smoke(v2console):  # noqa: F811
    ids = plant(v2console)
    from supervisor.monitors.common import MonitorContext

    mctx = MonitorContext.from_adapters(v2console.runtime.adapters, v2console.runtime.chain)
    out = decision_rollup.run(mctx, v2console.ctx.settings)
    print(out)
    for tab in ("gate", "detectors"):
        r = v2console.get(f"/console/analytics?tab={tab}")
        assert r.status_code == 200, r.text[:500]
        print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text.split('id="tab-body"')[1]))[:1500])
    r = v2console.get(f"/console/traces/{ids['trace']}")
    assert r.status_code == 200, r.text[:500]
    assert "corr-planted-0001" in r.text
    r = v2console.get("/console/traces?corr=corr-planted-0001")
    assert r.status_code == 200
    r = v2console.get("/console/decisions?correlation=corr-planted-0001")
    assert r.status_code == 200 and 'data-strip="correlation"' in r.text
