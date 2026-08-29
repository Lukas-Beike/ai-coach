# Development instructions for Intervals Coach

## Project scope

Intervals Coach is a private, mobile-first PWA for one athlete. The backend is a
Python standard-library HTTP server. It reads Intervals.icu data, sends a
sanitised training context to the OpenAI Responses API, stores the persistent
conversation and local chat history in SQLite, and creates local workout drafts
that require explicit approval before being pushed to Intervals.icu.

## Important boundaries

- Keep the app standalone; do not replace it with a Custom GPT or webhook flow.
- The app intentionally has no application password. It must stay on a trusted
  LAN or private VPN and must not be exposed directly to the public internet.
- Never read, print, commit, or copy `.env` secrets into source, logs, tests, or
  diagnostics. Preserve the user's `.env` and `data/` directory.
- Do not delete or reset the SQLite database. It contains chat history, drafts,
  the OpenAI conversation ID, profile, and model selection.
- Workouts are drafts until the athlete explicitly pushes them.

## Architecture

- `server.py`: HTTP API, SQLite persistence (including structured competitions),
  Intervals.icu client, derived performance context, OpenAI client, logging,
  synchronization, morning check-in, and workout draft handling.
- `public/`: browser/PWA client. Keep Markdown rendering safe and preserve
  Enter-to-send (Shift+Enter inserts a newline).
- `data/`: runtime-only state and logs; never ship it in a Docker build.
- `tests/test_server.py`: standard-library unit tests.
- `.env.example`: documented configuration template; `.env` is local-only.

## Behaviour requirements

- Perform one Intervals.icu sync at startup. Further refreshes happen only when
  the user requests current data in chat or presses the refresh button.
- The saved profile must be included in `build_training_context()` on every
  coach request.
- User-confirmed profile fields and competitions are authoritative in SQLite.
  Current performance is derived from the latest Intervals.icu snapshot. Treat
  OpenAI Conversation state as dialogue continuity, not as the athlete database.
- Never let a chat response silently mutate durable profile or competition data.
- Use the GPT-5.6 model family (`gpt-5.6-sol`, `gpt-5.6-terra`,
  `gpt-5.6-luna`) in the model selector.
- Keep API credentials server-side and redact them from logs and diagnostics.
- When changing frontend assets, update the asset query/cache version so that
  installed PWAs receive the new JavaScript/CSS.

## Git conventions

- Every commit must use the Conventional Commits format:
  `<type>(<optional-scope>): <description>`.
- Every pull request title must use the same format. Allowed types are
  `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`,
  `style`, and `test`; breaking changes use `!` before the colon.
- Pull requests must be created with squash auto-merge enabled when repository
  permissions and required checks allow it.
- The `Conventional commits and PR titles` workflow validates commit subjects
  and pull request titles for manually created pull requests.

## Validation

Run before handing off changes:

```powershell
python -m unittest discover -s tests -v
python -m py_compile server.py tests/test_server.py
```

## Docker / Unraid deployment

The deployment uses Docker CLI (not Compose) with image/container name
`ai-coach` and port `8090`. Build from the project root and preserve the data
bind mount and `.env` file. Do not use `docker rm -v`.

```bash
docker build -t ai-coach:local .
docker stop ai-coach || true
docker rm ai-coach || true
```

The persistent host data directory must remain mounted at `/data`.
