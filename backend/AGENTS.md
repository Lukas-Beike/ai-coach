# Backend ownership

Use the root domain map. Domain services own use-case orchestration and
transaction boundaries; provider adapters own external transport, not local
authorization or persistence policy. Assembly modules wire explicit dependencies.
Never import or indirectly reach `server.py` globals.

For Coach changes trace schema, authorization, dispatcher, durable effect, receipt,
and HTTP/UI refresh. Preserve local authority, source/freshness labels, explicit
remote writes, adaptive preview/apply, session/CSRF, and maintenance boundaries.
Use temporary storage and mocked providers; never weaken SQLCipher startup.

Validate focused tests, architecture guards, syntax, and CI-equivalent Ruff/mypy
checks for changed backend files. Follow the root secret-scan protocol.
