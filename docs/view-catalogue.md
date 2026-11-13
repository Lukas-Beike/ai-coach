# View catalogue

Every route of the PWA's hash router, with the panel it shows, the navigation
item it belongs to and its view contract, plus the state texts and the
confirmation texts the views show. Everything between the markers is generated
by `node tests/navigation-state.test.cjs --write`; a test per section fails when
it is out of date. An unknown route opens the default route.

## Views

The router's tables in `public/navigation.js` (`NAV_ROUTES`, `NAV_LINK_ROUTES`,
the segment lists and `ROUTE_ALIASES`) give the routes. `NAV_VIEWS` holds one
descriptor per route, for documentation only: `Loads` are the main API reads of
the view beside the start load (bootstrap with the chat, plan, library,
performance, feedback, profile and weather areas), `Actions` the German labels
of its main controls as rendered, and `States` the states it can show
(`loading`, `empty`, `error`, `notConfigured`, `offline`). A test fails when a
route has no descriptor, a descriptor names no route, or a read path or control
label appears in none of the public sources.

<!-- BEGIN GENERATED VIEWS -->
Default route: `#coach`. Navigation items: `#coach`, `#plan`, `#nutrition`, `#analysis`, `#more`.

| Route | Panel | Navigation item | Loads | Actions | States |
| --- | --- | --- | --- | --- | --- |
| `#analysis` | `dataPanel` | `analysis` | `/api/performance`, `/api/analysis/power-profiles` | Analyse aktualisieren, Jetzt abgleichen, Anbindung einrichten | loading, empty, error, notConfigured, offline |
| `#analysis/cycling` | `dataPanel` | `analysis` | `/api/performance`, `/api/analysis/power-profiles` | Analyse aktualisieren, Jetzt abgleichen, Anbindung einrichten | loading, empty, error, notConfigured, offline |
| `#analysis/load` | `dataPanel` | `analysis` | `/api/performance` | Analyse aktualisieren, Jetzt abgleichen, Anbindung einrichten, Letzte 14 Tage, 12 Wochen, 12 Wochen anzeigen | loading, empty, error, notConfigured, offline |
| `#analysis/recovery` | `dataPanel` | `analysis` | `/api/performance` | Analyse aktualisieren, Jetzt abgleichen, Anbindung einrichten, Letzte 14 Tage, 12 Wochen, 12 Wochen anzeigen | loading, empty, error, notConfigured, offline |
| `#analysis/running` | `dataPanel` | `analysis` | `/api/performance`, `/api/analysis/power-profiles` | Analyse aktualisieren, Jetzt abgleichen, Anbindung einrichten | loading, empty, error, notConfigured, offline |
| `#coach` | `chatPanel` | `coach` | `/api/chat/history?limit=100` | Senden, Morgen-Check-in, Analyse & Plan, Spracheingabe starten, Antwort stoppen, Weitere Nachrichten laden, Coach fragen | loading, empty, error, notConfigured, offline |
| `#more` | `settingsPanel` | `more` | `/api/context-preview`, `/api/logs?limit=250`, `/api/providers/connections`, `/api/nutrition/yazio/status` | Verbindung prüfen, Mit Garmin anmelden, Garmin trennen, Wahoo verbinden, Synchronisieren, Speichern, Entfernen | loading, error, notConfigured, offline |
| `#more/appearance` | `settingsPanel` | `more` | `/api/context-preview`, `/api/logs?limit=250` | System, Hell, Dunkel, Kalenderansicht speichern | loading, offline |
| `#more/coach` | `settingsPanel` | `more` | `/api/context-preview`, `/api/logs?limit=250` | Chat zurücksetzen, Kontext laden | loading, error, offline |
| `#more/connections` | `settingsPanel` | `more` | `/api/context-preview`, `/api/logs?limit=250`, `/api/providers/connections`, `/api/nutrition/yazio/status` | Verbindung prüfen, Mit Garmin anmelden, Garmin trennen, Wahoo verbinden, Synchronisieren, Speichern, Entfernen | loading, error, notConfigured, offline |
| `#more/equipment` | `settingsPanel` | `more` | `/api/context-preview`, `/api/logs?limit=250`, `/api/analysis/training-records` | Fahrrad, Laufschuhe, Wartung erledigt, Rückgängig | loading, empty, error, offline |
| `#more/operations` | `settingsPanel` | `more` | `/api/context-preview`, `/api/logs?limit=250`, `/api/privacy/gps` | Logs herunterladen, Benachrichtigungen aktivieren, Daten exportieren, Lokale Daten löschen, Backup herunterladen, Backup wiederherstellen, Diagnose herunterladen, Diagnose löschen, Abmelden | loading, empty, error, offline |
| `#more/profile` | `profilePanel` | `more` | `/api/context-preview`, `/api/logs?limit=250`, `/api/profile`, `/api/zones` | Athletenkontext speichern, Lokal speichern, Übernehmen | empty, offline |
| `#nutrition` | `nutritionPanel` | `nutrition` | `/api/nutrition/day` | Ernährung aktualisieren, Vorheriger Tag, Nächster Tag, Heute, Löschen, Rückgängig, Erneut laden | loading, empty, error, offline |
| `#nutrition/body` | `nutritionPanel` | `nutrition` | `/api/performance` | Ernährung aktualisieren, Letzte 14 Tage, 12 Wochen | loading, empty, error, offline |
| `#nutrition/diary` | `nutritionPanel` | `nutrition` | `/api/nutrition/day` | Ernährung aktualisieren, Vorheriger Tag, Nächster Tag, Heute, Löschen, Rückgängig, Erneut laden | loading, empty, error, offline |
| `#nutrition/products` | `nutritionPanel` | `nutrition` | `/api/nutrition/products?scope=all` | Barcode scannen, Nährwerttabelle fotografieren, Produkt manuell erfassen, Suchen | loading, empty, error, offline |
| `#nutrition/week` | `nutritionPanel` | `nutrition` | `/api/nutrition/week` | Ernährung aktualisieren, Letzte 14 Tage, 12 Wochen, Tageswerte anzeigen | loading, empty, error, offline |
| `#plan` | `workoutsPanel` | `plan` | `/api/plan`, `/api/library?limit=100`, `/api/activities?limit=100` | Kalender aktualisieren, Woche, Monat, Woche synchronisieren, Verschieben, Feedback, Mit dem Coach analysieren, Mit Coach lösen | loading, empty, error, notConfigured, offline |
| `#plan/library` | `workoutsPanel` | `plan` | `/api/plan`, `/api/library?limit=100` | Kalender aktualisieren, Weitere Bibliothekseinheiten laden, Erneut senden | loading, empty, error, offline |
| `#plan/overview` | `workoutsPanel` | `plan` | `/api/plan`, `/api/library?limit=100`, `/api/activities?limit=100` | Kalender aktualisieren, Woche, Monat, Woche synchronisieren, Verschieben, Feedback, Mit dem Coach analysieren, Mit Coach lösen | loading, empty, error, notConfigured, offline |
| `#plan/season` | `workoutsPanel` | `plan` | `/api/plan`, `/api/library?limit=100`, `/api/profile` | Kalender aktualisieren, Erneut laden | loading, empty, error, offline |

Kalender segments: `overview`, `library`, `season`.
Mehr segments: `profile`, `equipment`, `connections`, `coach`, `operations`, `appearance`.

Former routes that open another view:

- `#analysis/performance` opens `#analysis/running`
- `#analysis/sessions` opens `#plan/overview`
<!-- END GENERATED VIEWS -->

## State texts

Every call of the state helpers of `public/components.js` (`createEmptyState`,
`createLoadingState`, `createErrorState` with its fixed heading and retry
button, `markValueMissing`) and every paragraph drawn with an empty-state class
(`h(.empty)`, `h(.context-empty)`) with its text arguments, per file and
function. A text that is not a literal is listed as `(computed)` with its
expression. Other inline status lines are not listed.

<!-- BEGIN GENERATED STATES -->
### `public/activity-analysis.js`

| Function | Helper | Text | Detail |
| --- | --- | --- | --- |
| `loadPanel` | `createLoadingState` | Details werden geladen … |  |
| `loadPanel` | `createErrorState` | (computed) ` error.message ` |  |

### `public/analysis.js`

| Function | Helper | Text | Detail |
| --- | --- | --- | --- |
| `analysisChart` | `h(.empty)` | Ein einzelner Messwert zeigt noch keinen Verlauf; mindestens zwei datierte Werte sind erforderlich. |  |
| `cyclingPowerProfileTable` | `markValueMissing` | nicht erfasst |  |
| `showProfileCardsState` | `createErrorState` | (computed) ` error.message ` |  |
| `showProfileCardsState` | `createLoadingState` | (computed) `` `${title} wird geladen…` `` |  |
| `renderRunningBestEfforts` | `markValueMissing` | nicht erfasst |  |
| `renderBodyAnalysis` | `h(.empty)` | Noch keine Körper-Historie verfügbar. |  |
| `renderTrainingRecords` | `createLoadingState` | Ausrüstung wird geladen… |  |
| `renderTrainingRecords` | `createErrorState` | (computed) ` error?.message ` |  |
| `analysisEmptyCard` | `createEmptyState` | (computed) ` ANALYSIS_EMPTY_TITLES[segment] ` | (computed) ` cause ` |

### `public/coach.js`

| Function | Helper | Text | Detail |
| --- | --- | --- | --- |
| `renderMessages` | `createEmptyState` | Dein Coach ist bereit | – |

### `public/nutrition.js`

| Function | Helper | Text | Detail |
| --- | --- | --- | --- |
| `kcalValue` | `markValueMissing` | nicht erfasst |  |
| `nutritionTotalTile` | `markValueMissing` | nicht erfasst |  |
| `renderNutritionWeek` | `markValueMissing` | nicht erfasst |  |

### `public/performance-view.js`

| Function | Helper | Text | Detail |
| --- | --- | --- | --- |
| `renderCurrentPerformance` | `h(.empty)` | (computed) ` text ` |  |

### `public/plan-views.js`

| Function | Helper | Text | Detail |
| --- | --- | --- | --- |
| `renderLibrary` | `h(.context-empty)` | Noch keine Einheiten in der Bibliothek. Der Coach legt hier Einheiten ab, wenn du sie planst. |  |
| `renderCompetitions` | `h(.context-empty)` | Noch keine Wettkämpfe gespeichert. |  |
<!-- END GENERATED STATES -->

## Copy deck

Every confirmation the app asks for through `requestConfirmation`, the single
confirmation dialog (also behind `confirmDiscardChanges` and
`confirmDiscardDraft`): title, message and confirm button, with the dialog's
defaults where a call gives none. Computed texts are listed as in the state
texts.

<!-- BEGIN GENERATED COPY -->
| Where | Title | Message | Button |
| --- | --- | --- | --- |
| `public/activity-details.js` `renderBundle` | Aktivität löschen? | Diese Aktivität mit allen Aufzeichnungen lokal löschen? Bei den Anbietern bleibt sie erhalten. | Löschen |
| `public/auth.js` `logout` | Abmelden? | Du wirst auf diesem Gerät abgemeldet. Deine Daten bleiben verschlüsselt gespeichert. | Bestätigen |
| `public/coach.js` `resetCoachChat` | Coach-Chat zurücksetzen? | Coach-Chat wirklich zurücksetzen und eine neue Unterhaltung beginnen? | Bestätigen |
| `public/coach.js` `undoCoachTurn` | Änderungen zurücknehmen? | Alle lokalen Änderungen dieser Coach-Antwort zurücknehmen? Intervals.icu bleibt unverändert. | Zurücknehmen |
| `public/diagnostics.js` `deleteServerLogs` | Server-Logs löschen? | Server-Logs wirklich löschen? | Bestätigen |
| `public/diagnostics.js` `deleteDiagnostics` | Diagnose löschen? | Diagnosedaten wirklich löschen? | Bestätigen |
| `public/nutrition.js` `deleteNutritionEntry` | Mahlzeit löschen? | (computed) `` `Mahlzeit „${item.description}“ wirklich löschen?` `` | Löschen |
| `public/nutrition.js` `deleteNutritionProduct` | Aktion bestätigen | (computed) ` question ` | Bestätigen |
| `public/provider-connections.js` `changeMetricExportField` | Intervals.icu-Abgleich | (computed) ` message ` | Bestätigen |
| `public/provider-connections.js` `configureAutomaticMetricExport` | (computed) ` enabled ? "Automatischen Abgleich aktivieren?" : "Automatischen Abgleich deaktivieren?" ` | (computed) ` message ` | Bestätigen |
| `public/provider-connections.js` `clearProviderCredential` | (computed) `` `${label} entfernen?` `` | (computed) `` `${label} aus der App entfernen? Danach gilt wieder der Wert aus der Serverumgebung, falls dort einer gesetzt ist.` `` | Bestätigen |
| `public/provider-connections.js` `disconnectGarmin` | Garmin trennen? | Garmin trennen? Die in der App gespeicherten Garmin-Tokens werden gelöscht. Bereits geladene Daten bleiben erhalten. | Bestätigen |
| `public/settings.js` `adoptFirstThreshold` | Gemessenen Wert ersetzen? | Der gemessene Wert wird durch die Schätzung ersetzt. | Ersetzen |
| `public/settings.js` `restoreDatabaseBackup` | Datenbank-Backup wiederherstellen? | Das aktuelle Datenbank-Backup wird vorher gesichert und durch die ausgewählte Datei ersetzt. Fortfahren? | Bestätigen |
| `public/settings.js` `deleteGpsTracks` | GPS-Spuren löschen? | (computed) `` `Alle gespeicherten GPS-Spuren (${gpsTracksState.stored_tracks}) werden unwiderruflich lokal gelöscht. Streckenerkennung und Wetter am Ort nutzen sie nicht mehr. Die übrigen Aufzeichnungen bleiben.` `` | Löschen |
| `public/settings.js` `deletePrivacyData` | Lokale Daten endgültig löschen? | (computed) ` scope ` | Endgültig löschen |
| `public/settings.js` `removeZones` | Lokale Zonen entfernen? | Lokale Zonen entfernen? Danach gelten wieder die Zonen des Anbieters. | Entfernen |
| `public/shared.js` `confirmDiscardDraft` | Änderungen verwerfen? | Ungespeicherte Änderungen verwerfen? | Bestätigen |
| `public/sync-actions.js` `fullResync` | (computed) ` confirmation.title ` | (computed) ` confirmation.message ` | Bestätigen |
| `public/wahoo-connection.js` `disconnectWahoo` | (computed) `` `${label} trennen?` `` | (computed) `` `${label} trennen? Der Zugriff wird bei ${label} widerrufen und die lokalen Zugangsdaten werden gelöscht. Bereits geladene Einheiten bleiben erhalten.` `` | Bestätigen |
<!-- END GENERATED COPY -->
