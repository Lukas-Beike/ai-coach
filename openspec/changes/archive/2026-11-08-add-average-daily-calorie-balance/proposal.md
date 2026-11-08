# Proposal

## Why

The nutrition history shows the total calorie balance but does not show its average daily magnitude, making 14-day and 12-week periods harder to interpret.

## What Changes

- Show the signed average daily calorie balance beside the existing total for both history periods.
- Calculate it over days with both intake and expenditure, display coverage, and retain an unavailable state when none qualify.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `nutrition-diary-and-targets`: Add an average daily balance to the nutrition history presentation.

## Impact

The nutrition history client and its focused tests are affected. Existing summary data supplies the total and paired-day count; no API, persistence, or provider change is anticipated.
