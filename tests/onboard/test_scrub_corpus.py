"""WP16: every planted fake secret is scrubbed before any text reaches the ChatModel port.

The model port is wrapped so the test sees exactly what a model would receive.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.onboard.discover import discover
from supervisor.onboard.eval.labels import load_labels
from supervisor.onboard.eval.predict import CapturingChat
from supervisor.onboard.understand import understand
from tests.conftest import REPO_ROOT
from tests.test_no_secrets import PATTERNS

CORPUS = REPO_ROOT / "data" / "corpus"
LABELS = load_labels(CORPUS / "labels.yaml")
SECRET_REPOS = sorted(n for n, r in LABELS.repos.items() if r.secrets)


def test_corpus_plants_the_required_secret_shapes() -> None:
    kinds = {s.kind for n in SECRET_REPOS for s in LABELS.repos[n].secrets}
    assert {"aws_access_key", "llm_api_key", "databricks_token"} <= kinds


@pytest.mark.parametrize("repo", SECRET_REPOS)
def test_model_never_receives_a_planted_secret(repo: str) -> None:
    labels: Any = LABELS.repos[repo]
    d = discover(LocalGitRepoReader(CORPUS / "repos" / repo))
    chat = CapturingChat(MockChat(model_id="mock-onboarding-v1"))
    understand(d, chat, exercise_llm=True)  # type: ignore[arg-type]
    assert chat.seen, "the LLM step ran against the capturing port"
    sent = "\n".join(m["content"] for msgs in chat.seen for m in msgs)
    for s in labels.secrets:
        row = d.index.lines[s.file][s.line - 1]
        assert f"[REDACTED:{s.kind}]" in row, (s.file, s.line)
        assert s.needle not in row
        assert s.needle not in sent, f"{s.file}:{s.line} reached the model"
    for name, pat in PATTERNS.items():
        assert not pat.search(sent), name
    raw = "\n".join(
        (CORPUS / "repos" / repo / s.file).read_text(encoding="utf-8") for s in labels.secrets
    )
    assert all(s.needle in raw for s in labels.secrets), "the needles are really planted"
    assert re.search(r"\[REDACTED:[a-z_]+\]", sent)
    assert d.inventory.scrub["secrets_redacted"] >= len(labels.secrets)
