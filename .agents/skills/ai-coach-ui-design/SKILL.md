---
name: ai-coach-ui-design
description: Design or improve Intervals Coach screens, visual hierarchy, interaction copy, or mobile usability. Use for deliberate UI/UX work; use ai-coach-debugging for functional failures and ai-coach-pwa-e2e for browser verification.
license: Apache-2.0 adaptation; see ../THIRD_PARTY.md.
---

# Designing Intervals Coach UI

Adapted from Anthropic frontend-design. Modified for the existing mobile PWA,
plain JavaScript, athlete data, and local-action contracts; see
[provenance](../THIRD_PARTY.md).

## Ground the change in the athlete's task

- Read root and `public/AGENTS.md` instructions, then locate the relevant screen,
  state owner, CSS tokens, reusable controls, and neighboring flows. Scan sources
  first. Use synthetic fixture data for every preview or screenshot.
- Describe the athlete's goal, primary action, most important information, and
  states that affect the decision. Resolve routine choices from the existing
  product; request clarification only when an unresolved preference changes scope.
- For a substantial screen change, sketch a compact hierarchy or wireframe before
  editing. Extend existing spacing, color, type, icon, and control conventions.
  Do not rebrand a routine fix or introduce a framework, font service, dependency,
  or build step merely to produce a new look.

## Make the state and actions legible

- Give the primary decision visual priority. Group content by meaning, preserve
  reading order, and use spacing and typography before adding more cards, borders,
  decoration, or animation. Keep dense metrics readable on a narrow screen.
- Distinguish missing, zero, stale, loading, estimated, and failed data. Preserve
  units, dates, athlete-local time, and provider/derived/AI source labels; design
  with both sparse and complete synthetic data, never invented athlete facts.
- Use the existing German product vocabulary and short, concrete action verbs.
  Keep an action's name consistent through buttons, confirmation, and receipts.
  Format numbers, dates, distances, and durations through `public/format.js`.
- Cut eyebrows, taglines, intros, helper text, and secondary labels; name the
  effect in the control or receipt itself. If a screen needs explanation, fix
  the layout. Show source distinctions as a compact badge or suffix, not an
  explanatory line. Omit internal implementation terminology.
- Make local save, preview/apply, and explicit provider synchronization clear.
  Preserve separate approvals and durable-effect receipts; a new layout must not
  silently turn a preview or chat response into a write.
- Cover initial, empty, loading, ready, partial, error/retry, disabled, and success
  states relevant to the flow. Preserve entered values through recoverable errors
  and avoid misleading success feedback while a job is still running.

## Build and inspect

- Preserve semantic controls, visible keyboard focus, labels, WCAG AA contrast,
  touch targets of at least 44 px, screen-reader feedback, and reduced motion.
  Never convey source, severity, selection, or errors only through color. Keep
  DOM and visual order aligned; avoid focus loss when dynamic content updates.
- Add colors only as semantic tokens in both `:root` and `:root[data-theme="light"]`
  of `public/styles.css`; component rules use `var()`. Add new text/background
  pairs to `tests/test_css_design_tokens.py`. Put component rules in `@layer app`
  and precedence rules in `@layer overrides`; do not use `!important`.
- Check small mobile layouts, keyboard-open input, long German labels, 200% text
  without horizontal overflow, scroll containers, and sticky controls in the dark
  and light themes; inspect the affected wider layout too. Keep destructive
  actions distinguishable and microphone/notifications opt-in.
- Preserve safe Markdown, login/CSRF, streaming, and the chat keyboard and asset
  version contracts in `public/AGENTS.md`.
- Use the product-native preview when available and follow
  [the fixture/browser workflow](../ai-coach-pwa-e2e/SKILL.md). Inspect screenshots
  and interactions, then remove visual clutter that does not help the task.
- Run [affected checks](../ai-coach-validation/SKILL.md). Report what changed,
  which viewports/states were actually verified, and any unverified behavior.
