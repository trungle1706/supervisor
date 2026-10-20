"""Judge model family: derived, not declared (D05).

The family-independence rule (judge family != agent family) is only as good as the family
of the judge. A free-text ``JUDGE_T1_FAMILY=anything`` would let a qwen judge watch a qwen
agent. So the family comes from:

1. the model id prefix table (``adapters.llm.openai_compatible.model_family``), and, when
   ``JUDGE_FAMILY_PROBE=1``, the endpoint's own ``GET /v1/models`` metadata (``root``, ``id``,
   ``display_name``). If both name a family and they disagree, startup is refused.
2. A declared ``JUDGE_*_FAMILY`` is accepted only if it agrees with the derived family
   (``family_source = derived``). A declared family that disagrees, or that is given for a
   model whose family cannot be derived, is refused unless ``JUDGE_FAMILY_OVERRIDE_TEST_ONLY=1``
   (never allowed in ``databricks_app`` mode). The row then says
   ``family_source = declared-test-only``.

``family_source`` is written to every judge verdict row and chain record, the model card and
the validation report. Mock judges carry ``mock``.
"""

from __future__ import annotations

import logging
from typing import Literal

from supervisor.core.errors import ConfigError

log = logging.getLogger("supervisor.judge")

FamilySource = Literal["derived", "declared-test-only", "mock"]
SOURCE_DERIVED: FamilySource = "derived"
SOURCE_DECLARED: FamilySource = "declared-test-only"
SOURCE_MOCK: FamilySource = "mock"


class FamilyDeclarationError(ConfigError):
    """A declared judge family cannot be trusted (disagrees with the model, or no override)."""


def resolve_family(
    role_var: str,
    model_id: str,
    declared: str | None,
    *,
    override_test_only: bool,
    endpoint_family: str | None = None,
) -> tuple[str, FamilySource]:
    """``(family, family_source)`` for one judge. Raises :class:`FamilyDeclarationError`.

    ``role_var`` names the setting for messages (``JUDGE_T1_FAMILY``)."""
    from supervisor.adapters.llm.openai_compatible import model_family
    from supervisor.judge.router import normalize_family

    from_id = normalize_family(model_family(model_id))
    from_endpoint = normalize_family(endpoint_family) if endpoint_family else "unknown"
    if "unknown" not in (from_id, from_endpoint) and from_id != from_endpoint:
        raise FamilyDeclarationError(
            f"judge model {model_id!r}: the model id says family {from_id!r} but the endpoint "
            f"metadata says {from_endpoint!r}; refusing to guess (fix the model id or endpoint)"
        )
    derived = from_id if from_id != "unknown" else from_endpoint
    want = normalize_family(declared) if declared and declared.strip() else ""
    if not want:
        return derived, SOURCE_DERIVED  # may be "unknown": the router refuses that
    if want == derived:
        return derived, SOURCE_DERIVED
    if override_test_only:
        log.warning(
            "%s=%s overrides the derived family %r for model %s: TEST ONLY, "
            "family_source=declared-test-only is written to every verdict",
            role_var,
            want,
            derived,
            model_id,
        )
        return want, SOURCE_DECLARED
    what = (
        f"does not match the family derived from the model ({derived!r})"
        if derived != "unknown"
        else "was given for a model whose family cannot be derived from its id or endpoint"
    )
    raise FamilyDeclarationError(
        f"{role_var}={declared!r} {what}. A declared family is not trusted: use a model id "
        "that shows its family, or (tests only, refused in databricks_app mode) set "
        "JUDGE_FAMILY_OVERRIDE_TEST_ONLY=1"
    )
