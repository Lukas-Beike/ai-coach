# Feature Gap Analysis

This document compares the current Intervals Coach feature set with the
capabilities publicly described by established endurance platforms and newer
AI coaching products.

Research snapshot: 2026-08-29

## Product decisions

Intervals Coach will not rebuild Intervals.icu. Intervals.icu remains the
system of record for training-platform analytics, device delivery, and
execution on Garmin, Wahoo, Zwift, and other connected platforms. Intervals
Coach may persist selected normalized data locally when it improves AI context,
historical comparisons, resilience, or auditability.

The following decisions were made after this review:

| Gap area | Decision | Product boundary |
| --- | --- | --- |
| Adaptive plan and replan engine | **Implement** | Coach-owned future-plan state, constraints, feedback, preview, and approval; no silent remote writes |
| Integration and synchronization foundation | **Defer** | Keep the current Intervals.icu/Garmin integrations; consider broader providers later |
| Structured workout delivery and indoor execution | **Do not implement locally** | Intervals.icu remains responsible for delivery to Garmin, Wahoo, Zwift, and other platforms |
| Deep analytics and long-term history | **Implement selectively** | Persist source data needed by the AI and history; do not recreate Intervals.icu's analytics UI |
| Athlete feedback, availability, and recovery | **Implement** | Store only local signals not already available from Garmin or Intervals.icu |
| Annual planning and race preparation | **Implement** | Add multi-event season planning and optional import from public calendar feeds |
| Notifications, offline behavior, and native device experience | **Implement** | Prioritize PWA notifications; keep native device execution delegated to Intervals.icu |
| Data portability, backup, and recovery | **Implement** | Provide safe local backup/restore without exposing credentials |

## Executive summary

Intervals Coach already has a strong foundation for a private, single-athlete
assistant: local encrypted persistence, Intervals.icu and Garmin data, source
labels, 30-day trends, a conversational coach, workout-library reuse, explicit
approval before remote writes, and transparent context/log views.

The largest remaining product gaps are not another dashboard metric. They are
the systems that turn a chat assistant into a dependable training companion:

1. continuous adaptive planning and safe replanning;
2. first-class athlete availability, subjective feedback, and health signals;
3. season planning and race preparation;
4. reliable PWA notifications and local recovery workflows.

Broader integrations and device delivery remain future options, while
Intervals.icu continues to own the corresponding platform capabilities.

These gaps are based on the current repository and public product information,
not on hands-on testing of paid or device-specific features. Feature
availability can vary by subscription, sport, device, and region.

## Current Intervals Coach baseline

The current repository provides:

- a private mobile-first PWA for one athlete;
- local encrypted SQLite persistence for profile, competitions, snapshots, chat,
  workout drafts, and the workout library;
- Intervals.icu synchronization for strength, running, outdoor cycling, and
  indoor/virtual cycling;
- optional read-only Garmin synchronization, including Garmin VO2 max, running
  predictions, weight, and sport-specific maximum heart rate;
- current performance metrics with source labels and 30-day trends;
- a GPT-5.6 conversational coach with selectable model and thinking level;
- context preview, structured/redacted external-call logs, and OpenAI usage
  information when the API reports it;
- local workout drafts, exact/similar library matching, multi-week draft plans,
  conflict checks, and explicit approval before pushing to Intervals.icu;
- bidirectional competition synchronization with Intervals.icu;
- local JSON export and local cleanup controls;
- Docker/Unraid deployment with environment-variable configuration.

The following gap statements describe capabilities that are absent or only
partially covered by that baseline.

## Comparison matrix

| Capability | Intervals Coach today | Large-platform benchmark | Gap assessment |
| --- | --- | --- | --- |
| Adaptive plan updates | Generates drafts when asked; no continuously maintained plan engine | TrainerRoad adapts plans to performance, schedule, missed workouts, and workout difficulty; Athletica and HumanGO describe continuous adaptive plans | **Critical gap** |
| Annual/season planning | Target competitions and multi-week drafts | Intervals.icu offers annual plans with phases; TrainingPeaks offers Annual Training Plans that model future Fitness, Fatigue, and Form | **High gap** |
| Device and service integrations | Direct Garmin read plus Intervals.icu read/write | TrainingPeaks advertises broad device connectivity; Athletica lists Garmin, Strava, Wahoo, COROS, and Concept2; Strava connects devices and third-party apps | **Deferred** |
| Structured workout delivery | Pushes approved workouts to the Intervals.icu calendar | Intervals.icu supports structured workouts and exports/imports such as ZWO, FIT, MRC, and ERG; Garmin supports sending workouts to compatible devices | **Delegated to Intervals.icu** |
| Indoor execution | No trainer control or in-workout execution surface | TrainerRoad provides adaptive cycling workouts and indoor training; TrainingPeaks offers TrainingPeaks Virtual | **Delegated to Intervals.icu/platforms** |
| Activity analysis | Snapshot summaries, selected metrics, and trends | Intervals.icu exposes extensive interval and fitness analytics; TrainingPeaks provides PMC and detailed workout analysis; Strava provides best efforts, zones, and activity analysis | **Selective persistence only** |
| Workout compliance | Planned and completed data are visible, but no dedicated compliance score or feedback workflow | TrainingPeaks advertises compliance dashboards; TrainerRoad uses post-workout surveys and progression levels | **High gap** |
| Subjective athlete feedback | Profile notes and chat; readiness can be imported | TrainerRoad uses post-workout surveys; Athletica uses RPE/feel/comments; HumanGO advertises personal feedback and fatigue detection | **High gap** |
| Availability and life constraints | No first-class schedule, travel, illness, injury, or time-availability model | Adaptive platforms replan around availability, travel, missed sessions, illness, and fatigue | **High gap** |
| Recovery and health model | Imported readiness, sleep-related context, weight, and trends where available | Garmin combines sleep, HRV, recovery time, acute load, and stress for readiness; AI platforms use recovery and fatigue signals in planning | **Medium/high gap** |
| Performance testing and zones | Imports selected thresholds and VO2 max; derives some estimates | TrainerRoad has AI FTP detection and progression levels; Athletica supports baseline testing and automatic threshold updates; Intervals.icu supports custom zones and eFTP | **Medium/high gap** |
| Race preparation | Stores competitions and syncs them bidirectionally | Garmin provides race-oriented guidance, weather/elevation, pacing, and suggested workouts; HumanGO provides a race planner | **Medium gap** |
| Routes, maps, weather, and outdoor safety | Not a current product area | Strava provides routes, segments, and Beacon; Intervals.icu provides calendar weather; Final Surge lists route builder and weather features | **Medium gap** |
| Notifications and device-native experience | Browser PWA and long-lived login cookie | Garmin, TrainingPeaks, and other platforms provide device/app workout prompts, reminders, and native mobile experiences | **Medium gap** |
| Coach/athlete collaboration | Intentionally one private athlete | TrainingPeaks, Intervals.icu, Final Surge, Athletica, and HumanGO provide coach dashboards, athlete management, groups, or community features | **Out of scope by design** |
| Social/community features | None | Strava, Intervals.icu, Final Surge, and HumanGO offer social, group, or community features | **Out of scope by design** |
| Data portability and recovery | JSON export and local encrypted database | Mature platforms generally support many import/export and synchronization paths | **Selected gap**: add safe backup/restore |

## Priority gaps and recommended direction

### P0 - Adaptive plan and replan engine

Current behavior is request-driven: the coach can create a draft, but the
application does not own a durable plan state that is recalculated after every
completed, missed, or manually changed session.

Recommended scope:

- represent a plan as phases, weeks, sessions, constraints, and intended
  training load;
- calculate planned-versus-completed compliance;
- replan only future sessions after new activity, missed workouts, illness,
  travel, or explicit athlete feedback;
- show a human-readable change set before saving or pushing any change;
- preserve the current explicit-approval boundary for remote writes;
- record why a session changed and which data sources caused the change.

Why it matters: this is the central difference between a chat interface that
can write workouts and an adaptive coach. TrainerRoad, Athletica, and HumanGO
all position adaptation to performance, fatigue, availability, or missed
training as a core capability.

### Deferred - Integration and synchronization foundation

The current direct integrations are useful but narrow. This work is explicitly
deferred. If broader connectors are added later, they should not be added as
isolated one-off clients. Build a provider abstraction with OAuth/token
lifecycle, scopes, incremental cursors, retries, rate-limit handling,
deduplication, conflict policy, and per-provider sync status first.

Recommended order:

1. Strava, because it is a common aggregation point for activities and routes;
2. Wahoo and COROS, because they are important device ecosystems for cycling;
3. Polar, Suunto, Apple Health/Health Connect, and indoor platforms according
   to the athlete's devices;
4. outbound device delivery only after write permissions and approval UX are
   proven.

Every provider should expose provenance, timestamps, permissions, and a clear
canonical-record policy. Read-only sync should remain the default.

### Delegated - Structured workout delivery and execution feedback

Intervals Coach currently produces valid workout text and pushes approved
calendar events. It will not become a second device-delivery platform. The
approved workout remains in Intervals.icu, which is responsible for delivery to
Garmin, Wahoo, Zwift, and other connected platforms.

Possible future scope, only if the Intervals.icu boundary changes:

- normalize workouts into a provider-neutral step model;
- validate sport, duration, target type, zones, and recoveries;
- export/import FIT, ZWO, MRC, and ERG where licensing and provider APIs allow;
- send approved workouts to Garmin, Wahoo, COROS, or indoor platforms;
- match execution to prescription and show completed steps, deviations, and
  athlete feedback;
- retain an explicit approval and revoke/rollback story for every outbound
  action.

This is a high-value bridge from "the coach suggested a session" to "the
athlete can execute and evaluate the session with minimal manual work."

### P1 - Deep analytics and long-term history

The current 30-day trend view is a good summary, but it is not a replacement
for a full performance-analysis workspace.

Recommended scope:

- retain normalized activity and wellness history for multiple seasons;
- add activity detail with map, laps, intervals, power/pace/heart-rate charts,
  zones, and notes;
- add best efforts/peak performances and power/pace curves;
- add configurable date ranges, sport filters, season comparisons, and
  annotations for illness, training blocks, and races;
- expose a transparent PMC-style view for fitness, fatigue, and form;
- distinguish measured, imported, derived, and AI-estimated values everywhere.

Intervals.icu and TrainingPeaks show that deep analysis is a major reason
athletes keep a training platform even when a conversational coach is added.

### P1 - Athlete feedback, availability, and recovery model

Readiness data is currently mostly an imported metric. The coach needs a
structured way to understand what the athlete can actually do today.

Recommended scope:

- daily check-in for sleep quality, soreness, stress, mood, illness, pain,
  motivation, and perceived readiness;
- post-workout RPE, session feel, pain flags, and free-text feedback;
- availability calendar with time windows, preferred days, travel, and
  equipment constraints;
- explicit injury/illness mode that reduces or pauses recommendations;
- source-aware recovery model combining wearable signals and subjective input;
- safety rules that stop automatic progression when data is incomplete or
  warning signals conflict.

Subjective feedback is not just a UI convenience. TrainerRoad, Athletica, and
HumanGO use it as an input to personalization and adaptation.

### P1 - Annual planning and race preparation

Competitions are already modeled and synchronized. The missing layer is a
season view that turns them into priorities, phases, and a controlled taper.

Recommended scope:

- A/B/C race priority and target outcome;
- base, build, peak, taper, and recovery phases;
- backward planning from race date with weekly volume/load targets;
- multiple simultaneous events and sport-specific constraints;
- race-course information, weather snapshot, pacing strategy, and race-week
  checklist;
- explicit preview of projected load and risk before applying the plan.

### P2 - Notifications, offline behavior, and native device experience

The PWA works well for a private server, but it currently depends on opening
the browser and does not provide a device-native reminder or offline execution
layer.

Potential scope:

- web push for sync failures, upcoming workouts, approval requests, and daily
  check-ins;
- offline cache for the current plan and last synced data;
- installable PWA polish, widgets, and calendar feeds;
- optional native companion only if device delivery cannot be handled through
  provider integrations.

### P2 - Data portability, backup, and recovery

JSON export is valuable, but a private self-hosted application also needs a
clear recovery story.

Recommended scope:

- encrypted, versioned backup and restore of database plus Garmin token store;
- export of original provider records and normalized records separately;
- documented schema/version migrations;
- import validation and dry-run before destructive restore;
- configurable backup destination suitable for Unraid.

Do not weaken the current security model by placing secrets into browser
exports, logs, or unencrypted backup archives.

## Deliberately deprioritized gaps

The following capabilities are common on larger platforms but do not represent
the best next investment for the stated product purpose:

- multi-athlete coaching businesses and coach billing;
- public athlete profiles, feeds, clubs, challenges, and social engagement;
- a general route-discovery network;
- a marketplace for paid training plans;
- a large native app team for every watch ecosystem.

They may become relevant if the product changes from a private single-athlete
coach into a hosted platform. For the current architecture, adaptive planning,
data quality, execution, and analysis provide more value.

## Suggested implementation sequence

| Phase | Deliverable | Success criterion |
| --- | --- | --- |
| 1 | Canonical data model, provider abstraction, sync cursors, provenance, and backup/restore | A sync can be retried safely and every value has a source and timestamp |
| 2 | Availability/check-in model and planned-versus-completed compliance | The coach can explain whether a session was completed and how it felt |
| 3 | Replan engine with preview and approval | A missed or completed session produces a reviewable future-plan change set |
| 4 | Structured workout model and first outbound device integration | An approved workout reaches the athlete's primary device and execution is matched back |
| 5 | Deep analytics, season planning, race preparation, and notifications | The app supports a complete plan-analyze-adjust loop |

## Sources

The comparison uses public product and support pages from the following
platforms. These links document the capabilities referenced above; they are not
endorsements.

- [TrainingPeaks product overview](https://www.trainingpeaks.com/) - plans,
  device connectivity, structured training, and strength features.
- [TrainingPeaks Coach Edition guide](https://www.trainingpeaks.com/get-started-coach/)
  - dashboards, Performance Management Chart, calendar, workout libraries,
  and athlete management.
- [TrainingPeaks Performance Management Chart](https://www.trainingpeaks.com/learn/articles/what-is-the-performance-management-chart/)
  - Fitness, Fatigue, Form, and training-load analysis.
- [TrainingPeaks Annual Training Plan guide](https://www.trainingpeaks.com/learn/articles/the-comprehensive-guide-to-creating-an-annual-training-plan/)
  - periodization and projected load/form planning.
- [Garmin Daily Suggested Workout documentation](https://www8.garmin.com/manuals/webhelp/GUID-25E3235D-44D2-4384-A591-DD1D71BEBCB1/EN-US/GUID-542FB2A1-D6D2-4C77-8573-65E87182BFAD.html)
  - suggestions based on training habits, recovery time, and VO2 max.
- [Garmin training-plan support](https://support.garmin.com/en-US/?faq=o21H5a4cSU52FwFAy0R6Z5)
  - event-oriented training plans and device delivery.
- [Garmin workout delivery support](https://support.garmin.com/en-GB/?faq=Oyqt6jUjOF8L1Rnuc9Sms8&productID=73207&tab=topics&topicTag=region_workoutstrainingplan)
  - structured workout creation and sending workouts to compatible devices.
- [Intervals.icu planning features](https://www.intervals.icu/features/plan/)
  - calendar, workout builder, plans, zones, formats, and weather.
- [Intervals.icu analytics overview](https://intervals.icu/about.html)
  - fitness/fatigue/form, activity history, interval metrics, and multisport
  analysis.
- [Strava Help Center](https://support.strava.com/en-us/)
  - activity analysis, goals, training plans, device connections, routes,
  segments, safety, and community areas.
- [Final Surge athlete features](https://site.finalsurge.com/Athletes)
  - calendar planning, reports, workout library, and training-log views.
- [Final Surge app features](https://www.finalsurge.com/app)
  - readiness, weather, route builder, and mobile calendar features.
- [TrainerRoad Adaptive Training](https://www.trainerroad.com/blog/introducing-adaptive-training-the-right-workout-every-time/)
  - machine-learning adaptation, progression levels, missed-workout handling,
  and workout recommendations.
- [TrainerRoad Adaptive Training guide](https://www.trainerroad.com/blog/how-to-use-adaptive-training/)
  - post-workout surveys, workout alternates, and adaptation inputs.
- [Athletica.ai](https://www.athletica.ai/)
  - adaptive plans, conversational coaching, device connections, and athlete
  autonomy claims.
- [Athletica plan-adjustment support](https://support.athletica.ai/hc/en-us/articles/24843044366235-How-does-Athletica-adjust-training-plans)
  - changes based on completed workouts and manual interventions.
- [Athletica settings guide](https://support.athletica.ai/hc/en-us/articles/34950137808923-Updated-Guide-to-Adjusting-Settings-in-Athletica)
  - availability, plan warnings, threshold updates, training modality, and
  connected apps.
- [HumanGO athlete platform](https://humango.ai/gethumango)
  - adaptive plans, wearable connections, feedback, progress tracking, and race
  planning.
- [HumanGO coach platform](https://humango.ai/how-it-works/coaches)
  - replanning, fatigue detection, testing protocols, athlete dashboards, and
  group features.

## Caveats

Product pages are marketing and support material, not independent benchmarks.
Some capabilities require premium subscriptions, compatible hardware, or a
specific sport. Before implementing a gap, verify the relevant API terms,
write permissions, rate limits, data-retention implications, and licensing
requirements.
