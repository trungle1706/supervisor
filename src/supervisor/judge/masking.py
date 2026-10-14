"""Masker plumbing for the judge. Judges read masked text only (analysis 07 section 3).

The real masker (``vn_regex``, optional presidio) comes from WP4 through the ``Masker``
port. The judge takes it as a dependency; :class:`IdentityMasker` is the default for
tests and for traces that the recorder has already masked at capture.
"""

from __future__ import annotations

from supervisor.core.ports import Masker


class IdentityMasker:
    """Returns text unchanged. Use only on text that was masked at capture (WP4)."""

    version = "identity-v1"

    def mask(self, text: str) -> str:
        return text


def mask_version_of(masker: Masker) -> str:
    """``version`` attribute of a masker, else its class name (logged in each verdict)."""
    version = getattr(masker, "version", None) or getattr(masker, "mask_version", None)
    return str(version) if version else type(masker).__name__
