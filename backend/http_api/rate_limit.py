"""In-memory rate limiting for HTTP authentication and API requests."""

from __future__ import annotations

import threading
import time

RATE_LIMIT_CLEANUP_INTERVAL_SECONDS = 15 * 60
RATE_LIMIT_CLEANUP_BATCH_SIZE = 100
RATE_LIMIT_BUCKET_MAX_AGE_SECONDS = 15 * 60


class RateLimiter:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.buckets: dict[str, list[float]] = {}
        self.last_cleanup_monotonic = 0.0

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            if now - self.last_cleanup_monotonic >= RATE_LIMIT_CLEANUP_INTERVAL_SECONDS:
                for inspected, bucket_key in enumerate(tuple(self.buckets), start=1):
                    if inspected > RATE_LIMIT_CLEANUP_BATCH_SIZE:
                        break
                    recent_bucket = [
                        stamp
                        for stamp in self.buckets[bucket_key]
                        if now - stamp < RATE_LIMIT_BUCKET_MAX_AGE_SECONDS
                    ]
                    if recent_bucket:
                        self.buckets[bucket_key] = recent_bucket
                    else:
                        self.buckets.pop(bucket_key, None)
                self.last_cleanup_monotonic = now

            recent = [
                stamp
                for stamp in self.buckets.get(key, [])
                if now - stamp < window_seconds
            ]
            allowed = len(recent) < limit
            if allowed:
                recent.append(now)
            self.buckets[key] = recent
            retry_after = max(1, int(window_seconds - (now - min(recent or [now]))))
            return allowed, retry_after
