"""WP37 follow-up F13: adversarial probe rows are large enough to mean something."""

from __future__ import annotations

from tests.conftest import REPO_ROOT


def test_adversarial_rows_have_at_least_50_positives_per_detector() -> None:
    from supervisor.detectors import golden

    for slug in ("dlp_vn", "injection_regex", "judge_advisory"):
        probes = golden.load(slug, "adversarial")
        pos = [p for p in probes if p["label"] == 1]
        neg = [p for p in probes if p["label"] == 0]
        assert len(pos) >= 50, (slug, len(pos))
        assert len(neg) >= 10, (slug, len(neg))  # benign look-alikes
        assert len({p["id"] for p in probes}) == len(probes)


def test_the_report_keeps_the_indicative_wording() -> None:
    doc = (REPO_ROOT / "docs" / "detectors-validation-report.md").read_text(encoding="utf-8")
    assert "indicative" in doc.lower()
