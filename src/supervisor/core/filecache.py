"""Cache for parsed config files (audit E1).

The key is the loader, the resolved path, ``st_mtime_ns`` and ``st_size``, so an edited file is
picked up on the next call.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

_MAX_ENTRIES = 64
_lock = threading.Lock()
_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()


def load_cached(path: Path | str, loader: Callable[[Path], T]) -> T:
    """``loader(path)``, remembered while the file stays the same. A missing file raises
    ``OSError`` (from ``stat``) as it would without the cache. A loader error is not cached.
    The loader result is shared: callers must not change it."""
    p = Path(path).resolve()
    st = p.stat()
    key = (loader, str(p), st.st_mtime_ns, st.st_size)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]  # type: ignore[no-any-return]
    value = loader(p)
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > _MAX_ENTRIES:
            _cache.popitem(last=False)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()
