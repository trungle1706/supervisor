from __future__ import annotations

import re

from .wp39_fixtures import plant, v2adapters, v2console  # noqa: F401


def test_smoke(v2console):
    ids = plant(v2console)
    d = v2console.get(f"/console/decisions/{ids['a']}/drawer?tab=request").text
    body = d.split('id="tab-body"')[1].split("masked-record")[0]
    print(re.sub(r"\s+", " ", body)[:1800])
    d = v2console.get(f"/console/decisions/{ids['c']}/drawer?tab=detections").text
    print(re.sub(r"\s+", " ", d.split('id="tab-body"')[1])[:1500])
