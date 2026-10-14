"""Optional Presidio masker. Off by default; needs the ``presidio-analyzer`` package."""

from __future__ import annotations

from typing import Any

from supervisor.core.errors import ConfigError


class PresidioMasker:
    """Stub behind an optional extra. Raises ConfigError when Presidio is not installed."""

    def __init__(self, language: str = "en") -> None:
        try:
            from presidio_analyzer import AnalyzerEngine  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ConfigError(
                "PresidioMasker needs the optional package presidio-analyzer. "
                "Install it, or set the masker to vn_regex (the default)."
            ) from exc
        self.mask_version = "presidio-0"
        self.language = language
        self._engine: Any = AnalyzerEngine()

    def mask(self, text: str) -> str:
        results = sorted(
            self._engine.analyze(text=text, language=self.language),
            key=lambda r: r.start,
            reverse=True,
        )
        for r in results:
            text = f"{text[: r.start]}<{r.entity_type}>{text[r.end :]}"
        return text
