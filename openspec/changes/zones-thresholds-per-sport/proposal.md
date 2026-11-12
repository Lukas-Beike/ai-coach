## Why

The "Zonen & Schwellen" editor showed empty fields although the app works with an FTP and Garmin heart-rate zones for all sports (athlete report 2026-11-11, #2262). The athlete chose, with mockups, one page per sport with LT1 and LT2 on top and every zone kind below.

## What Changes

- Profil order: Person, Ziele & Woche, Zonen & Schwellen, Training, Quellen & Coach; every section starts closed. A stale-threshold warning no longer opens the section; its count shows in the summary line and the status strip.
- Zonen & Schwellen: sport tabs (Radfahren, Laufen, Schwimmen). On each tab:
  - LT1 and LT2 with source and date;
  - each zone kind with name, range, percent basis and source;
  - "Bearbeiten" or "Anlegen" opens the existing editor prefilled with what is in effect today: Garmin's zones for all sports, or the FTP / threshold pace from the performance values.
- LT1: heart rate from the stored share of the threshold heart rate; power or pace at the upper limit of zone 2 of the zones in effect, labelled as derived (athlete decision 2026-11-12).
- The first-threshold entry moves from Quellen & Coach behind "Bearbeiten" on LT1.
- Analyse › Laufen and Radfahren show the LT1 values like the zones page (decision on #2265).

## Capabilities

### Modified Capabilities
- `athlete-profile-and-checkins`: zone editing per sport, the profile section order and closed sections.
- `web-pwa-and-accessibility`: LT1 in Analyse Laufen and Radfahren.

## Impact

Frontend: `public/index.html`, `public/settings.js`, `public/performance-view.js`, `public/views.js`, `public/styles.css`.

- No API, schema or provider request change.
- Saving zones and the first threshold keeps its current server behaviour.
