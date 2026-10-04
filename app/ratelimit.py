"""Sliding-window rate limiter, in memory, per process.

A cost/abuse guard, not an exact quota: with gunicorn's two workers the
effective limit is up to double, and it resets on restart. Keys with no
recent calls are dropped so a stream of distinct clients cannot grow the
dict without bound."""

import hashlib
import threading
import time
from collections import deque
from collections.abc import Hashable

_PURGE_AT_KEYS = 5000


class RateLimiter:
    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self.max_calls = max_calls
        self.window = window_seconds
        self._calls: dict[Hashable, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_purge = time.monotonic()

    def allow(self, key: Hashable) -> bool:
        now = time.monotonic()
        with self._lock:
            self._maybe_purge(now)
            calls = self._calls.setdefault(key, deque())
            while calls and now - calls[0] > self.window:
                calls.popleft()
            if len(calls) >= self.max_calls:
                return False
            calls.append(now)
            return True

    def blocked(self, key: Hashable) -> bool:
        """True if `key` has used up its window — without recording a call.
        Pair with hit() to count only certain outcomes (e.g. failed logins)."""
        now = time.monotonic()
        with self._lock:
            calls = self._calls.get(key)
            if not calls:
                return False
            while calls and now - calls[0] > self.window:
                calls.popleft()
            return len(calls) >= self.max_calls

    def hit(self, key: Hashable) -> None:
        now = time.monotonic()
        with self._lock:
            self._maybe_purge(now)
            self._calls.setdefault(key, deque()).append(now)

    def _maybe_purge(self, now: float) -> None:
        # By age as well as by size: stale keys used to be freed only after 5000
        # distinct keys piled up, so a few giant ones could sit in memory for ever.
        if len(self._calls) >= _PURGE_AT_KEYS or now - self._last_purge > self.window:
            self._purge(now)
            self._last_purge = now

    def _purge(self, now: float) -> None:
        stale = [k for k, c in self._calls.items() if not c or now - c[-1] > self.window]
        for key in stale:
            del self._calls[key]

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()


def key_for(*parts: object) -> tuple[str, ...]:
    """A fixed-size key from arbitrary user input: hashing means a request body
    carrying a multi-megabyte "email" cannot pin that string in memory."""
    return tuple(hashlib.sha256(str(p).encode("utf-8", "replace")).hexdigest()[:24] for p in parts)


def enforce(limiters: dict[str, "RateLimiter"], name: str, key: Hashable, message: str) -> None:
    """Raise the shared 429 error when `key` has used up limiter `name`."""
    if not limiters[name].allow(key):
        from app.errors import ApiError

        raise ApiError("rate_limited", message, 429)
