# Design

## Context

See proposal. External records use a `per_100` object; local products already hold optional additional nutrients. Online mirror entries can predate the new projection.

## Goals / Non-Goals

**Goals:** Preserve valid values from supported provider formats through review, including older mirror records when feasible, without altering local products.

**Non-Goals:** Change historical meal snapshots, infer missing nutrition, or introduce a database migration.

## Decisions

Reuse the existing product form beside the lookup result for online barcode matches; other editor entry points remain usable. Keep explicit save and cancel. Extend provider projections and client normalization, applying the same unit, modifier and plausibility checks as existing fields. Do not assume undocumented provider field identities. Old mirrored entries lacking these fields must be handled deliberately without overwriting athlete products or repeatedly fetching when an old entry legitimately lacks data.

When refreshing a still-fresh legacy record fails, preserve its original fetch timestamp and return it as a local record. A bounded, in-memory 15-minute retry delay avoids repeatedly calling unavailable providers while allowing later recovery; it does not persist across restarts or extend the record's freshness.

## Risks / Trade-offs

Provider fields may be unavailable or undocumented; leave them unknown until their wire semantics are supported. A cached older projection may lack values; verify its refresh path with a synthetic fixture and report any limit. No schema change is needed because the external mirror stores JSON.
