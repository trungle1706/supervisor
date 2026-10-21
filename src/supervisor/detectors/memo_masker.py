"""A masker that remembers its last answers for long texts (WP41, D30).

Several detectors mask the same tool result in the same call (dlp_vn, injection_regex, the
classifier). On an 8 KB text the masker is most of the cost, so the second and third pass should
cost a hash. The cache keeps the MASKED text only, keyed by a SHA-256 of the input: no raw text
is held (R2). Short texts bypass it (they are cheap). It is small, bounded and thread safe.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

from supervisor.core.ports import Masker

MIN_CACHED_CHARS = 256
MAX_ENTRIES = 64


class MemoMasker:
    def __init__(self, inner: Masker, max_entries: int = MAX_ENTRIES) -> None:
        self.inner = inner
        self._max = max_entries
        self._lock = threading.Lock()
        self._memo: OrderedDict[str, str] = OrderedDict()

    def mask(self, text: str) -> str:
        if len(text) < MIN_CACHED_CHARS:
            return self.inner.mask(text)
        key = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        with self._lock:
            hit = self._memo.get(key)
            if hit is not None:
                self._memo.move_to_end(key)
                return hit
        out = self.inner.mask(text)
        with self._lock:
            self._memo[key] = out
            while len(self._memo) > self._max:
                self._memo.popitem(last=False)
        return out

    def __getattr__(self, name: str) -> object:  # mask_version and the like
        return getattr(self.inner, name)
