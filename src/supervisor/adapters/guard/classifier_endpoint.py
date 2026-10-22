"""ClassifierEndpointGuard: a direct classifier endpoint (WP-D3).

    POST <url>   {"inputs": ["text 1", "text 2"]}

The shape of a Databricks model-serving endpoint (or a Hugging Face text-classification server)
that hosts a prompt-guard class model. Accepted answers, one entry per input in order:

* ``[[{"label": "JAILBREAK", "score": 0.97}, {"label": "BENIGN", "score": 0.02}], ...]``
  (all labels per text), or ``[{"label": "...", "score": 0.97}, ...]`` (top label only);
* the same list inside ``{"predictions": [...]}``.

Scores are probabilities between 0 and 1. A label this version does not know, a wrong count or a
score outside 0 to 1 is an error (``execution_failed``), never a silent pass. The adapter sends
the texts it is given (the detector masks first), keeps the key out of ``repr`` and messages, and
puts only an error class or an HTTP status in a message, never a response body (it may echo the
input).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

from supervisor.adapters.guard.labels import bp_from_probability, normalise_label, top_attack
from supervisor.core.errors import GuardModelError
from supervisor.core.ports import GuardScore

HeaderFactory = Callable[[], Mapping[str, str]]


def _is_loopback(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ClassifierEndpointGuard:
    name = "classifier_endpoint"
    is_mock = False

    def __init__(
        self,
        url: str,
        *,
        model_id: str = "",
        api_key: str | None = None,
        headers: HeaderFactory | None = None,
        timeout_s: float = 0.4,
        max_batch: int = 16,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not url:
            raise GuardModelError("GUARD_MODEL_URL is empty")
        self.url = url
        self.model_id = (
            model_id or urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or "classifier"
        )
        self.timeout_s = float(timeout_s)
        self.max_batch = max(1, int(max_batch))
        self.__api_key = api_key or None
        self._headers = headers
        self._client = httpx.Client(transport=transport, trust_env=not _is_loopback(url))

    def __repr__(self) -> str:
        return (
            f"ClassifierEndpointGuard(url={self.url!r}, model_id={self.model_id!r}, "
            f"key={'set' if self.__api_key else 'none'})"
        )

    def close(self) -> None:
        self._client.close()

    # -- port ----------------------------------------------------------------------------
    def score(self, texts: Sequence[str]) -> list[GuardScore]:
        out: list[GuardScore] = []
        for i in range(0, len(texts), self.max_batch):
            out.extend(self._post(list(texts[i : i + self.max_batch])))
        return out

    # -- internals -----------------------------------------------------------------------
    def _auth(self) -> dict[str, str]:
        head = {"Content-Type": "application/json"}
        if self._headers is not None:
            try:
                head.update(dict(self._headers()))
            except Exception as exc:  # noqa: BLE001 - SDK auth errors; never echo credentials
                raise GuardModelError(
                    f"cannot get credentials for the guard endpoint: {type(exc).__name__}"
                ) from exc
        elif self.__api_key:
            head["Authorization"] = f"Bearer {self.__api_key}"
        return head

    def _post(self, batch: list[str]) -> list[GuardScore]:
        try:
            resp = self._client.post(
                self.url,
                json={"inputs": batch},
                headers=self._auth(),
                timeout=self.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise GuardModelError("guard endpoint did not answer in time", "timed_out") from exc
        except httpx.HTTPError as exc:
            raise GuardModelError(
                f"cannot reach the guard endpoint: {type(exc).__name__}", "execution_failed"
            ) from exc
        if resp.status_code >= 400:
            raise GuardModelError(f"guard endpoint answered HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise GuardModelError("guard endpoint sent a body that is not JSON") from exc
        return self.parse(data, len(batch))

    @staticmethod
    def parse(data: Any, expected: int) -> list[GuardScore]:
        """The answer of the endpoint as one :class:`GuardScore` per input."""
        if isinstance(data, Mapping):
            data = data.get("predictions", data.get("outputs"))
        if not isinstance(data, list) or len(data) != expected:
            raise GuardModelError("guard endpoint sent an answer with the wrong shape or count")
        out: list[GuardScore] = []
        for item in data:
            rows = item if isinstance(item, list) else [item]
            pairs: list[tuple[str, int]] = []
            for row in rows:
                if not isinstance(row, Mapping) or "label" not in row or "score" not in row:
                    raise GuardModelError("guard endpoint sent an entry without label and score")
                pairs.append((normalise_label(row["label"]), bp_from_probability(row["score"])))
            if not pairs:
                raise GuardModelError("guard endpoint sent an empty entry")
            out.append(top_attack(pairs))
        return out
