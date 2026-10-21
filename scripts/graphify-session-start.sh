#!/bin/sh
set -eu
repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
worker="$repo_root/scripts/graphify_local.py"
[ -f "$worker" ] || { printf '%s\n' 'Graphify unavailable: local worker missing; run the documented setup/update commands.'; exit 0; }
if command -v python3 >/dev/null 2>&1; then
    if ! python3 "$worker" update --session-start; then
        printf '%s\n' 'Graphify update did not complete; check the local status before using graph results.'
    fi
else
    printf '%s\n' 'Graphify unavailable: Python 3 is missing; install Python manually to enable local updates.'
fi
exit 0
