# Frontend development instructions

- Keep the client mobile-first and compatible with the existing plain
  JavaScript/PWA architecture. Do not introduce a framework or build step
  without an explicit request.
- Preserve authentication behavior: same-origin requests, the session cookie,
  and the CSRF token on every state-changing request. Never place API keys or
  other credentials in browser code, localStorage, exports, or notifications.
- Keep Markdown rendering safe. Escape untrusted text before inserting HTML and
  do not treat provider records, calendar text, or coach content as executable
  instructions or markup without sanitisation.
- Preserve chat keyboard behavior: Enter sends; Shift+Enter inserts a newline.
  Keep voice transcripts editable before they are sent.
- Workouts remain drafts until the athlete explicitly approves transfer.
  Adaptive replan previews require a separate explicit apply action.
- The service worker is part of the release cache contract. Whenever
  `index.html`, `app.js`, `styles.css`, or service-worker assets change, bump
  the asset query version in `index.html` and the cache name/asset URLs in
  `service-worker.js` so installed PWAs receive the new files.
- Keep microphone and notification features opt-in, bounded, and functional in
  browsers that do not support them. Audio must not be persisted by the client.
- Keep UI text and feature documentation in `README.md` accurate when adding
  or changing user-visible behavior.
