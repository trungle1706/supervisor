"""Small PEP 440 subset: parse and compare versions for OSV ECOSYSTEM ranges.

Written from the PEP 440 text (https://peps.python.org/pep-0440/), not copied from
``packaging`` (which is not a direct dependency). Supported: epoch (``1!``), release
segments, pre-releases (``a``/``b``/``rc``, also ``alpha``/``beta``/``c``/``pre``/``preview``),
post-releases (``.post1``, ``-1``), dev releases (``.dev3``), a leading ``v``, and a local
part (``+abc``), which is ignored for ordering. Anything else returns ``None`` from
:func:`parse`; callers then fall back to exact string match.

Order: ``1.0.dev1 < 1.0a1 < 1.0b1 < 1.0rc1 < 1.0 < 1.0.post1 < 1.0.1``.
Trailing zeros in the release do not matter (``1.0 == 1.0.0``).
"""

from __future__ import annotations

import re
from typing import NamedTuple

_RE = re.compile(
    r"""^\s*v?
    (?:(?P<epoch>\d+)!)?
    (?P<release>\d+(?:\.\d+)*)
    (?:[-_.]?(?P<pre_l>alpha|a|beta|b|preview|pre|c|rc)[-_.]?(?P<pre_n>\d*))?
    (?:(?:-(?P<post_n1>\d+))|(?:[-_.]?(?:post|rev|r)[-_.]?(?P<post_n2>\d*)))?
    (?:[-_.]?dev[-_.]?(?P<dev_n>\d*))?
    (?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?
    \s*$""",
    re.VERBOSE | re.IGNORECASE,
)

_PRE_RANK = {
    "a": 0,
    "alpha": 0,
    "b": 1,
    "beta": 1,
    "c": 2,
    "rc": 2,
    "pre": 2,
    "preview": 2,
}
_NEG = (-1, 0)  # lower than any pre-release (a dev release of a final version)
_INF = (9, 0)  # higher than any pre-release (a final release)


class Version(NamedTuple):
    """Sortable key. Compare with the normal tuple operators."""

    epoch: int
    release: tuple[int, ...]
    pre: tuple[int, int]
    post: int
    dev: int


def parse(text: str) -> Version | None:
    """Parse ``text``; return ``None`` when it is not a PEP 440 version."""
    m = _RE.match(text or "")
    if not m:
        return None
    release = [int(p) for p in m.group("release").split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    pre: tuple[int, int] | None = None
    if m.group("pre_l"):
        pre = (_PRE_RANK[m.group("pre_l").lower()], int(m.group("pre_n") or 0))
    post: int | None = None
    if m.group("post_n1") is not None:
        post = int(m.group("post_n1"))
    elif m.group("post_n2") is not None:
        post = int(m.group("post_n2") or 0)
    dev: int | None = None
    if re.search(r"dev", text, re.IGNORECASE) and m.group("dev_n") is not None:
        dev = int(m.group("dev_n") or 0)
    if pre is None and post is None and dev is not None:
        pre_key = _NEG
    elif pre is None:
        pre_key = _INF
    else:
        pre_key = pre
    return Version(
        epoch=int(m.group("epoch") or 0),
        release=tuple(release),
        pre=pre_key,
        post=-1 if post is None else post,
        dev=10**9 if dev is None else dev,
    )


def compare(a: str, b: str) -> int | None:
    """-1, 0 or 1; ``None`` when either side does not parse."""
    va, vb = parse(a), parse(b)
    if va is None or vb is None:
        return None
    return (va > vb) - (va < vb)


def equal(a: str, b: str) -> bool:
    c = compare(a, b)
    return a == b if c is None else c == 0


def in_ecosystem_range(version: str, events: list[dict[str, str]]) -> bool:
    """OSV ECOSYSTEM range test.

    ``events`` are OSV events: ``introduced`` (``"0"`` = from the start), ``fixed``
    (exclusive end), ``last_affected`` (inclusive end). Events are sorted by version;
    a version is affected after an ``introduced`` it has reached and until the next
    ``fixed`` it has reached or ``last_affected`` it has passed. A version or event that
    does not parse makes that event ignored (never a crash, never a false hit)."""
    cur = parse(version)
    if cur is None:
        return False
    parsed: list[tuple[Version, int, str]] = []
    for ev in events:
        for kind in ("introduced", "fixed", "last_affected"):
            if kind not in ev:
                continue
            raw = str(ev[kind])
            key = parse("0") if kind == "introduced" and raw == "0" else parse(raw)
            if key is not None:
                # at equal versions, process introduced first, then last_affected, then fixed
                order = {"introduced": 0, "last_affected": 1, "fixed": 2}[kind]
                parsed.append((key, order, kind))
    parsed.sort(key=lambda t: (t[0], t[1]))
    affected = False
    for key, _order, kind in parsed:
        if kind == "introduced":
            if cur >= key:
                affected = True
        elif kind == "fixed":
            if cur >= key:
                affected = False
        elif cur > key:  # last_affected
            affected = False
    return affected
