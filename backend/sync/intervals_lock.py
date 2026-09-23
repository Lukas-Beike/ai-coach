"""Shared exclusion boundary for Intervals.icu synchronization."""

import threading

INTERVALS_SYNC_LOCK = threading.Lock()
