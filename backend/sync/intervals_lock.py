"""Exclusion boundary the Intervals.icu data purge takes while it writes."""

import threading

INTERVALS_SYNC_LOCK = threading.Lock()
