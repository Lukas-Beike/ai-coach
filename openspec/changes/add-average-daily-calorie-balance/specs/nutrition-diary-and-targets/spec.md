# Spec Delta

## ADDED Requirements

### Requirement: Nutrition history shows average daily calorie balance
The nutrition history SHALL show a signed average daily calorie balance alongside the total balance for both the 14-day and 12-week views, with the count of days used and the period's day count.

#### Scenario: Complete deficit period
- **WHEN** all 14 days have intake and expenditure and their total balance is -4,468 kcal
- **THEN** the total remains visible and the average displays -319 kcal per day with coverage of 14 of 14 days.

#### Scenario: Partial period
- **WHEN** only some days have both intake and expenditure in either period
- **THEN** the average is the sum of those paired daily balances divided by their count, and its coverage identifies the paired days out of 14 or 84.

#### Scenario: Surplus or balanced period
- **WHEN** the paired-day total is positive or zero
- **THEN** the average retains the positive sign for a surplus or displays zero for a balanced period.

#### Scenario: No paired days
- **WHEN** no day has both intake and expenditure
- **THEN** the average is shown as unavailable with zero coverage, rather than as zero.

Evidence at revision `19da41dc`: `backend/nutrition/sync_status.py::NutritionSyncStatusService.get_week_summary` supplies the paired balance sum and count; `public/nutrition.js::renderNutritionWeek` displays the existing total. `tests/test_nutrition_garmin_expenditure.py` covers paired-day summaries and `tests/nutrition-history.test.cjs` covers chart aggregation; the proposed average display is not yet implemented or tested.
