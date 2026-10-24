# Dependency upgrade evidence

Use this reference for dependency changes; keep the executable lock-regeneration
recipe in [README.md](../../../../README.md#dependency-lock-maintenance).

1. Record old/new versions and inspect upstream release notes and migration
   guidance. Search actual imports and call sites, including startup, tests, and
   browser consumers. Separate required code changes from optional features.
2. Check Python 3.14, SQLCipher/encrypted startup, platform wheels, transitive
   changes, licenses, and any Node/browser constraints relevant to the package.
   A successful resolver does not establish runtime compatibility.
3. Change direct pins in `requirements.in` or `requirements-dev.in` and regenerate
   the corresponding hash-locked outputs with the README recipe. Inspect the
   complete lock diff; do not manually substitute hashes or broaden unrelated pins.
   JavaScript dependencies use the existing package manifest and lock workflow.
4. Run affected contract tests and the required Docker build for dependency
   changes. Check application call sites affected by an upstream behavior change,
   not only import success. Report unavailable platform/integration checks.
5. Summarize behavior changes, compatibility evidence, required adaptations, and
   optional opportunities. Follow the existing PR workflow only when authorized;
   an upgrade does not authorize release, deployment, or new account configuration.
