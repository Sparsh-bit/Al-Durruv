"""In-process sliding-window limiter for expensive endpoints (AI, uploads). One API process (see DEPLOY.md)."""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def hit(key: str, limit: int, per_s: int = 60) -> None:
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > per_s:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(
                429, "Too many requests. Wait a minute and try again.", headers={"Retry-After": str(per_s)}
            )
        q.append(now)
