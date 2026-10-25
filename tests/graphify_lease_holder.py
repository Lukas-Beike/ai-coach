"""Hold a Graphify environment lease until stdin closes (test helper)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import graphify_local as graph

with graph.environment_lease(Path(sys.argv[1]), time.monotonic() + 30):
    print("leased", flush=True)
    sys.stdin.read()
