# Release and database compatibility

Releases preserve the athlete's existing encrypted database. The only
supported baseline is the schema production runs: version 26, written by
release 2.0.5. Startup and restore accept it in place, retaining existing
records and SQLCipher encryption. Older, unknown or newer schemas are rejected
without deleting or partially changing the data: open a version 21 to 25
database or backup with release 2.0.5 first (and an older one with release
1.13.44 before that), then back it up again. Keep the existing `/data` bind
mount and `APP_PASSWORD` when recreating the container, and do not replace or
reset the data directory to resolve a rejected schema. A fresh database is only
required when the athlete explicitly chooses to start over. Future schema
changes add explicit, versioned and transactional migrations from the baseline
with upgrade regression tests; the baseline moves only when production runs a
newer schema.
The current schema is version 27. Releases wrote version 21 (1.13.41 to
1.13.44), 22 (2.0.0), 23 (2.0.1), 24 (2.0.2), 25 (2.0.3 and 2.0.4) and 26
(2.0.5). Version 10 adds canonical activity detail
(streams, laps and zone times), version 11 the food-database mirror, version 12
stores the Garmin collection as one keyed row per element instead of one large
`garmin_snapshot` value, version 13 adds the maximum speed of each lap, and
version 14 lets Yazio foods into the food-database mirror and saved products,
and version 15 adds canonical sleep periods, zone configurations, provider
statuses, gear with its activity links, the session each activity note was
written for, and the survivor a deleted merged session keeps, version 16
names the start and planned duration of local planning records (planned units,
workout-library entries, competitions, staged Coach plans and adaptive previews)
`starts_at_local` and `planned_duration_s` instead of the Intervals.icu fields
`start_date_local` and `moving_time`, and version 17 stores the Intervals.icu
cycling power curve (best power per duration with its day and activity, plus the
status and window of the latest fetch) as canonical rows, and version 22 stores
executed strength sets (each set's type, exercise category and code,
repetitions, weight, duration and planned workout step) as a detail kind, and
version 23 adds the athlete's own marking of what a session was
(`activity_feedback.purpose`), version 24 records what measured the heart
rate and power of a stream set (chest strap or optical, power meter, trainer
or estimate) and the external sensors its recording named (without serial
numbers), and version 25 stores the first threshold estimate (DFA-a1) of a
chest-strap stream set as a derived result only, never the RR intervals, and version 26 adds
an index that serves the backfill-continuation lookup of sync jobs, and version 27 gives
products one canonical table: own products and foods saved from a database
lookup are rows of `nutrition_products` with an origin (`own` or the
database), the database's fetch time and its further fields; the upgrade moves
every `food_database_entries` row into it and fills only the empty fields of
an own product that holds a food's EAN or id. Release
2.0.5 upgrades a version 21 to 25 database or backup to it in place within one
transaction, and a failed upgrade leaves it unchanged. Change-history entries
written before version 16 still name the former fields and can no longer be
undone.
Version 18 records the session-RPE rating time. Version 19 names local planned
load and intensity `planned_load` and `planned_intensity` and the frozen target
FTP basis `ftp`; the Intervals.icu adapter retains its provider wire names.
Version 20 adds the favorite flag of saved products. Version 21 gives canonical
observations a lifecycle: a value that Garmin or Wahoo clears or deletes is
retired after the next sync or reprojection of its source record, and it stays
stored but is no longer served. A dateless snapshot record such as the athlete
profile only retires values of its fetch day; values of earlier days stay as
history.

Schema version 9 stores sports in the canonical vocabulary (`sport` such as `ride`, `run` or `strength`, plus `environment` and, for text without a canonical sport, a lossless `sport_detail`) for equipment, competitions, the workout library and planned units. The HTTP API and coach tools keep accepting the previous Intervals.icu-style tokens (for example `VirtualRide` becomes `ride` + `virtual`), and Intervals.icu payloads are unchanged because only the Intervals.icu adapter maps canonical values back to its activity types. Likewise only that adapter maps `starts_at_local` and `planned_duration_s` to the Intervals.icu event and workout fields, and Coach tools take `starts_at_local` and `planned_duration_s` as well.
