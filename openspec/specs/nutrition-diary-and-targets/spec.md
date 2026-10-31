# nutrition-diary-and-targets Specification

## Purpose

Describe the athlete's local nutrition diary, nutrient completeness, expenditure comparisons, and body-history presentation. This is a brownfield baseline at application revision `b8c911c9dda83a7920171916ace32681c0c38ba0` (setup revision `6f942515acbb018f3a0b8ffdac148ce888b32a0a`). Evidence below is source/test inspection unless execution is recorded separately. The inspected nutrition flow has no saved calorie/macro target or adaptive-target calculation; its running-day expenditure projection is not a target. Food definitions belong to `food-catalog-and-meal-library`, external writes to `nutrition-provider-sync`, and loading to `view-refresh-and-client-state`.

## Requirements

### Requirement: Protected diary reads and explicit local mutations
The system SHALL expose day, date-range, and history reads only to an authenticated athlete and process nutrition mutations through the authenticated, CSRF-protected API boundary.

#### Scenario: Read a selected day
- **WHEN** an authenticated athlete requests a valid diary date
- **THEN** the response contains that date's local entries, counts, totals, and expenditure metadata; an omitted date uses the athlete-local day.

#### Scenario: Reject unauthenticated reads
- **WHEN** an unauthenticated caller requests nutrition history or saved meals
- **THEN** authentication fails before accessing the nutrition service.

#### Scenario: Reject an unauthorized mutation
- **WHEN** a nutrition POST or PUT lacks the required session or CSRF proof
- **THEN** the shared HTTP boundary rejects it before dispatching a durable nutrition mutation.

Evidence: `backend/http_api/nutrition.py::NutritionGetRoutes.handle`, `backend/http_api/handler.py::RequestHandler.do_POST`; `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_week_route_rejects_unauthenticated_read_before_service_access`, `tests/test_nutrition_api_and_sync.py::NutritionHttpApiTests.test_templates_route_requires_authentication`. Mutation protection also uses the shared HTTP authentication contract; these route-unit tests do not exercise a real browser session.

### Requirement: Validated local entries with trustworthy provenance
The system SHALL validate diary entry data before persistence, retain an entry identity and source provenance, and derive nutrition provenance from the accepted input path rather than trusting a supplied provenance object.

#### Scenario: Record a manual entry
- **WHEN** the athlete submits a description, valid date, finite calories from 0 through 10000, and optional finite macros from 0 through 1000 grams
- **THEN** the entry is persisted locally with normalized calories/macros, source, and an identifier and can be read again.

#### Scenario: Reject invalid entry data
- **WHEN** required calories or description are missing, a date or meal type is invalid, or a nutrient is negative, nonfinite, or out of range
- **THEN** validation fails without saving the invalid entry.

#### Scenario: Distinguish estimates and authoritative food calculations
- **WHEN** an entry uses Coach/photo/voice estimates, packaging values, or database/product components
- **THEN** its basis identifies the accepted estimate, label, or frozen server calculation; a client-supplied basis does not establish database provenance.

Evidence: `backend/nutrition/models.py::normalize_nutrition_entry`, `backend/nutrition/meal_library.py::NutritionMealLibraryService.prepare_values`, `backend/nutrition/diary.py::NutritionDiaryService.log_meal`; `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_log_and_get_meal`, `tests/test_nutrition_composition.py::NutritionCompositionTests.test_composite_rejects_forged_authoritative_values_and_unknown_macros_propagate`. See `food-catalog-and-meal-library` for component validation.

### Requirement: Athlete-local dates and explicit time knowledge
The system SHALL preserve the selected consumption date and distinguish a known meal time from an unknown time. Unknown time SHALL require an explicit meal type and use a neutral ordering anchor without presenting it as an observed time.

#### Scenario: Default at local midnight
- **WHEN** an entry omits the date after midnight in the athlete's configured timezone
- **THEN** the entry uses the athlete-local date, even if UTC is still the previous day.

#### Scenario: Log without a known time
- **WHEN** an entry declares `logged_time_known=false` and an explicit breakfast, lunch, dinner, or snack type
- **THEN** that type is retained, the stored ordering anchor is noon on the meal date, and the UI omits a clock-time claim.

#### Scenario: Correct a previously unknown time
- **WHEN** a correction explicitly supplies a meal time without overriding the time-knowledge flag
- **THEN** the entry becomes known-time and the supplied time is combined with its meal date.

Evidence: `backend/nutrition/models.py::_normalize_logged_time`, `backend/nutrition/diary.py::_names_time_without_flag`, `public/nutrition.js::nutritionCard`; `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_meal_logged_after_athlete_local_midnight_uses_athlete_local_day`, `tests/test_nutrition_meal_times.py::NutritionMealTimeTests.test_unknown_time_keeps_explicit_meal_type_and_noon_anchor`, `tests/test_nutrition_meal_times.py::NutritionMealTimeTests.test_naming_a_time_makes_an_unknown_time_known`.

### Requirement: Targeted corrections and deletion preserve synchronization work
The system SHALL update or delete the identified local meal, preserve omitted correction fields, and mark every affected date pending for later explicit export. Invalid or missing targets SHALL produce an error.

#### Scenario: Move and correct a meal
- **WHEN** the athlete corrects calories and the meal date of an existing entry
- **THEN** its identity, source, and other omitted fields remain, and both old and new dates become pending.

#### Scenario: Remove the last exported meal
- **WHEN** the last meal on an already-synced date is deleted
- **THEN** it disappears from reads while the now-empty date remains pending so a later explicit export can clear prior remote totals.

#### Scenario: Invalid correction
- **WHEN** a correction is empty, contains unsupported fields or invalid nutrient values, or names a nonexistent entry
- **THEN** the service rejects it and retains the valid local state.

Evidence: `backend/nutrition/diary.py::NutritionDiaryService.correct_meal`, `backend/nutrition/diary.py::NutritionDiaryService.delete_meal`; `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_correct_meal_preserves_omitted_fields_and_marks_old_and_new_days_pending`, `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_correct_meal_rejects_empty_invalid_or_missing_target`, `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_deleting_last_synced_entry_keeps_empty_date_pending`. Shared history/undo authorization is owned by the history and Coach contracts.

### Requirement: Daily macro completeness is distinct from known subtotals
The system SHALL sum calories and counts for recorded meals while preserving unknown macronutrients as unknown. It SHALL expose known macro subtotals and the number of entries with incomplete macros rather than treating omitted values as zero.

#### Scenario: Complete day
- **WHEN** every recorded entry supplies a macro
- **THEN** that macro's daily total is the sum of the recorded values.

#### Scenario: Partially known day
- **WHEN** one of two meals lacks macros
- **THEN** affected complete totals are null, the known meal contributes to `known_macro_totals`, and the incomplete-entry count increases.

#### Scenario: Range summary
- **WHEN** the athlete requests an inclusive valid range
- **THEN** returned days with entries preserve the same completeness rules; a reversed range is rejected rather than silently swapped.

Evidence: `backend/db/repositories.py::nutrition_macro_totals`, `backend/nutrition/diary.py::NutritionDiaryService.get_range_summary`; `tests/test_nutrition_meal_times.py::NutritionMealTimeTests.test_partial_macros_keep_daily_totals_unknown_but_expose_known_sums`, `tests/test_nutrition_meal_times.py::NutritionMealTimeTests.test_range_summary_matches_partial_day_totals`, `tests/test_nutrition.py::NutritionRepositoryAndServiceTests.test_day_summary`.

### Requirement: Historical sugar and salt derive from consumption snapshots
The system SHALL compute displayed sugar and salt from the quantity and nutrient data frozen with consumption, including scaled composite portions. Unknown contributions SHALL retain an incomplete total and a separate known subtotal.

#### Scenario: Product changes after consumption
- **WHEN** a product's current nutrient definition changes after a meal was recorded
- **THEN** historical sugar and salt continue to use the consumed product snapshot.

#### Scenario: Composite or database recipe
- **WHEN** a consumed recipe contains multiple frozen ingredients or scaled portions
- **THEN** sugar and salt are calculated from each consumed quantity, including nested provenance snapshots.

#### Scenario: Missing nutrient
- **WHEN** at least one component has no sugar or salt value
- **THEN** that complete total remains null, available values appear only as a known subtotal, and the UI marks incompleteness.

Evidence: `backend/nutrition/intake_totals.py::_snapshot_values`, `backend/nutrition/intake_totals.py::add_intake_totals`, `public/nutrition.js::nutritionTotalTile`; `tests/test_nutrition_composition.py::NutritionCompositionTests.test_sugar_and_salt_follow_consumption_snapshots_and_unknowns`, `tests/test_nutrition_composition.py::NutritionCompositionTests.test_composite_salt_sugar_scale_with_template_portions_and_week_coverage`.

### Requirement: Closed-day history preserves independent coverage
The system SHALL return 7, 14, or 84 closed days ending yesterday, keep absent intake and expenditure unknown, and calculate balances only for dates with both values. Each average SHALL report its own observed-day count.

#### Scenario: Unlogged day with expenditure
- **WHEN** Garmin expenditure exists but the athlete recorded no meal on a historical day
- **THEN** expenditure remains visible, intake and balance remain null, and the day does not count toward intake coverage.

#### Scenario: Independently covered metrics
- **WHEN** intake, macros, and expenditure cover different days
- **THEN** each average uses only its known observations and the balance total counts only paired days.

#### Scenario: Unsupported period or empty history
- **WHEN** the requested period is not the integer 7, 14, or 84, or no measurements exist
- **THEN** invalid periods fail; an empty valid history contains dated gaps, null averages, and zero coverage instead of invented zero intake.

Evidence: `backend/nutrition/sync_status.py::NutritionSyncStatusService.get_week_summary`, `backend/nutrition/sync_status.py::_week_day`, `public/nutrition.js::nutritionChartDays`; `tests/test_nutrition_garmin_expenditure.py::NutritionGarminExpenditureTests.test_week_uses_closed_days_and_only_paired_values_for_balance`, `tests/test_nutrition_garmin_expenditure.py::NutritionGarminExpenditureTests.test_history_rejects_unsupported_periods`, `tests/nutrition-history.test.cjs::weekly chart averages observed days independently and preserves empty weeks`.

### Requirement: Measured expenditure retains date and freshness provenance
The system SHALL keep measured total, active, and resting energy distinct and return source, measurement date, sync time, and freshness for the requested day. It SHALL report a measured total only when supplied, without manufacturing it from components.

#### Scenario: Canonical measurements exist
- **WHEN** daily total, active or resting energy is available through the observation reader
- **THEN** those canonical measurements supply the day values and the running day's resting reference, while refresh status and the complete read windows remain tied to the Garmin snapshot.

#### Scenario: No canonical energy
- **WHEN** the stored Garmin snapshot has daily energy for a day but no canonical observation exists for it
- **THEN** the day's energy is unavailable; the snapshot's values are never read.

#### Scenario: Only components or malformed data exist
- **WHEN** a day has active/resting energy without a measured total, or provider data is malformed or absent
- **THEN** the measured total remains unavailable and the athlete's local diary is still readable.

#### Scenario: Complete empty targeted read
- **WHEN** a successful targeted daily-energy refresh returns no record for its requested day
- **THEN** older canonical energy for that day is not reused as a current measurement; other days retain their own freshness.

Evidence: `backend/performance/daily_health.py::daily_energy_expenditure`, `backend/nutrition/sync_status.py::_filter_targeted_missing_energy`; `tests/test_nutrition_garmin_expenditure.py::NutritionGarminExpenditureTests.test_day_and_week_read_measured_energy_from_observations`, `tests/test_nutrition_garmin_expenditure.py::NutritionGarminExpenditureTests.test_malformed_garmin_snapshot_leaves_local_day_summary_available`, `tests/test_nutrition_garmin_expenditure.py::NutritionGarminExpenditureTests.test_targeted_nutrition_refresh_freshness_is_scoped_to_requested_day`, `tests/test_performance_daily_health.py::CanonicalDailyHealthParityTests.test_expenditure_reads_every_component_from_the_observations`, `tests/test_performance_daily_health.py::CanonicalDailyHealthParityTests.test_snapshot_energy_without_observations_is_unavailable`.

### Requirement: Running-day projection is explicitly derived
The system SHALL expose a separate running-day full-day expenditure projection only when today's active energy and a valid completed resting-energy reference are available. It SHALL retain the reference date and keep this projection distinct from Garmin's measured total.

#### Scenario: Valid reference
- **WHEN** the latest positive resting-energy value within the preceding seven days lies in a fully current completed read window
- **THEN** today's active energy plus that reference produces the separate projection and reference metadata.

#### Scenario: Missing or inconsistent reference
- **WHEN** the reference is absent, outside a trusted current window, or gives a projection below today's already measured resting or total energy
- **THEN** no projected total is returned.

#### Scenario: Historical or future date
- **WHEN** the selected date is not the current athlete-local day
- **THEN** the running-day projection is absent; future dates do not acquire measured expenditure from past data.

Evidence: `backend/performance/daily_health.py::_projection_reference`, `backend/performance/daily_health.py::_projected_expenditure`, `public/nutrition.js::renderNutritionExpenditure`; `tests/test_nutrition_garmin_expenditure.py::NutritionGarminExpenditureTests.test_today_projects_persisted_resting_reference_with_current_active_energy`. Projection edge branches are inspected source evidence; this is not evidence of adaptive nutrition targets.

### Requirement: Nutrition body view preserves observations and gaps
The client SHALL expose body history under nutrition with selectable 14-day and 12-week periods, render server-preferred body measurements, and preserve measurement dates and gaps. Detailed body-series and derived power-to-weight calculation remain governed by the performance domain.

#### Scenario: Open body history
- **WHEN** the athlete navigates to `#nutrition/body`
- **THEN** the body charts appear in nutrition with period controls and the preferred weight/body-fat series; the latest-values table keeps each original measurement date.

#### Scenario: Missing observations
- **WHEN** a date has no body measurement
- **THEN** the chart retains the gap rather than using a current profile value as historical observation.

#### Scenario: Twelve-week aggregation
- **WHEN** the athlete selects twelve weeks
- **THEN** each rolling week's chart point uses the median of available measurements, retains its observation count and latest measurement date, and leaves empty weeks as gaps; W/kg remains in the current cycling-performance table rather than a Body chart.

#### Scenario: Preferred measurements unavailable
- **WHEN** the response has no measured series from the server-preferred body source
- **THEN** the latest-values table shows missing values and empty metric charts are omitted rather than silently substituting another source or profile value.

Evidence: `backend/performance/body.py::body_history`, `public/analysis.js::renderBodyAnalysis`, `public/analysis.js::bodyWeeklyPoints`, `public/navigation.js::NAV_ROUTES`; `e2e/body-analysis.spec.js::@responsive Body keeps old measurements dated and long gaps empty`, `e2e/body-analysis.spec.js::@responsive Body plots measurements and W/kg appears only in the cycling table`, `tests/test_nutrition_garmin_refresh.py::GarminNutritionRefreshTests.test_remote_body_refresh_keeps_body_fat_only_measurements_and_normalizes_date`. Exact body-chart runtime conformance remains unexecuted in this worker; detailed body-series calculation belongs to the performance domain specification.
