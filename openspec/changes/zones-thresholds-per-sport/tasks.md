## 1. Implementation

- [ ] 1.1 Reorder the profile sections, start them all closed and move Zonen & Schwellen and the first-threshold entry into place
- [ ] 1.2 Render the per-sport page: sport tabs, LT1/LT2 block and the zone kinds with source, range and percent basis
- [ ] 1.3 Open the existing editor under a zone kind, prefilled with the zones in effect (all-sports Garmin zones included) or the current FTP / threshold pace
- [ ] 1.4 Stop the stale-threshold warning from opening the section and show its count in the summary line
- [ ] 1.5 Show the LT1 values in Analyse › Laufen and Radfahren
- [ ] 1.6 Update docs and the PR mapping of old to new places

## 2. Validation

- [ ] 2.1 Regression tests that fail before the change: an all-sports Garmin zone is shown and prefilled; the cycling FTP prefills the power editor
- [ ] 2.2 Run the Node tests and the affected browser specs at mobile, tablet-landscape and desktop where available, and record unavailable checks as gaps
- [ ] 2.3 Review the evidence pointers and run strict OpenSpec validation
