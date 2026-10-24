"""Used-nonce store: in memory, with an optional JSON file so a restart does not forget.

One store holds several namespaces ("mandate" for mandate nonces, "tap" for signed-request nonces).
`consume` is the only way to record a use, and it is atomic under a lock: the first caller gets
True, every later caller gets False (a replay). A corrupt file raises instead of loading empty,
because an empty store would let every old nonce be replayed (fail closed).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Optional

NS_MANDATE = "mandate"
NS_TAP = "tap"


class NonceStore:
    def __init__(self, path: Optional[str] = None):
        self._path = path
        self._lock = threading.Lock()
        self._used: dict[str, dict[str, float]] = {}
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    raise ValueError(f"nonce store file is corrupt: {path}") from e
            if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
                raise ValueError(f"nonce store file has the wrong shape: {path}")
            self._used = {ns: {str(k): float(t) for k, t in v.items()} for ns, v in data.items()}

    def seen(self, namespace: str, nonce: str) -> bool:
        with self._lock:
            return nonce in self._used.get(namespace, {})

    def consume(self, namespace: str, nonce: str, now: Optional[float] = None) -> bool:
        """Record a use. True if this is the first use, False if it was already used."""
        if not isinstance(nonce, str) or not nonce:
            raise ValueError("nonce must be a non-empty string")
        with self._lock:
            ns = self._used.setdefault(namespace, {})
            if nonce in ns:
                return False
            ns[nonce] = time.time() if now is None else now
            self._flush()
            return True

    def _flush(self) -> None:
        if not self._path:
            return
        directory = os.path.dirname(os.path.abspath(self._path))
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._used, f, sort_keys=True)
            os.replace(tmp, self._path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
