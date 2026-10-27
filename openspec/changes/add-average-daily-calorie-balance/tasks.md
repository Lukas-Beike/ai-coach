# Tasks

## 1. Nutrition history presentation

- [x] 1.1 Review the current paired-day summary and history rendering against the delta spec; confirm the existing total and coverage fields support the calculation.
- [x] 1.2 Add a signed average daily balance tile beside the total in both history periods, using paired-day coverage and preserving unavailable values; verify complete, partial, surplus, zero, and empty cases with focused client tests.
- [ ] 1.3 Update frontend asset query versions and service-worker cache together; verify the affected mobile layout and history flow with the repository's browser validation guidance, and update user-facing documentation if needed.

## 2. Integration validation

- [ ] 2.1 Run the affected tests and required repository checks on the final tree, review the complete diff, and run `npm run openspec -- validate add-average-daily-calorie-balance --strict`.
