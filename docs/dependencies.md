# Dependency lock maintenance

`requirements.in`, `requirements-dev.in` and `requirements-graphify.in` contain
direct requirements. Their matching `.txt` files are pip-tools outputs with
hashes. Docker and CI install only the app/development locks with `--require-hashes`;
the Graphify lock is used only by its separate shared development environment.
Dependabot recognizes this `.in`/`.txt` pairing and updates both files. When
regenerating locally, use Python 3.14 on Linux (the SQLCipher wheel is not
available on native Windows):

```text
pip-compile --allow-unsafe --generate-hashes --output-file=requirements.txt requirements.in
pip-compile --allow-unsafe --generate-hashes --output-file=requirements-dev.txt requirements-dev.in
pip-compile --allow-unsafe --generate-hashes --strip-extras --output-file=requirements-graphify.txt requirements-graphify.in
```

Compile the Graphify pair on Windows/Python 3.14 instead: a Linux resolution
drops the Windows-only `pywin32` pin that `mcp` needs, and a hash-only Windows
setup then fails. Dependabot therefore ignores `graphifyy` (#2554): when
`python scripts/prepare_worktree.py` reports a newer version, raise the pin in
`requirements-graphify.in` and run the Graphify command above on Windows. The
lock contract test accepts the options in any order, as pip-tools releases
differ, but requires exactly the options shown.

The incremental quality check also records the `ruff` and `mypy` versions in
`tests/fixtures/quality_baseline.json`. After changing either pin, record the new
versions without running the tools, then commit the baseline with the lock files:

```text
python tools/quality_baseline.py --align-versions
```

This changes only the version record. New diagnostics from the newer tool still
fail the check until the code is fixed or the baseline is regenerated on purpose.
