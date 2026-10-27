## MODIFIED Requirements

### Requirement: Intervals wellness and athlete threshold mapping
The system SHALL map dated Intervals wellness body, HRV, sleep, readiness, VO2max, load/form, and sport eFTP observations. It SHALL derive form from valid CTL minus ATL only when no reported form alias is present, label derivation, and preserve athlete versus wellness series. Sport settings SHALL keep threshold/HR/pace/VO2max scope and supported unset-zero semantics; invalid first-present aliases SHALL not silently fall through.

#### Scenario: Derived form versus reported zero
- **WHEN** a wellness row contains valid CTL/ATL without a reported form field
- **THEN** form can be derived and labeled derived; an explicitly reported valid zero form remains the reported value.

#### Scenario: HRV methods and alias precedence
- **WHEN** RMSSD and SDNN are both present or an earlier alias is invalid while a later alias is numeric
- **THEN** HRV methods remain separate observations, and the rejected first-present value is reported rather than replaced by the later alias. Supported wellness kinds include weight/body fat, resting HR, RMSSD/SDNN, sleep duration/score, readiness, VO2max, CTL/ATL/form, and sport-scoped eFTP.

#### Scenario: Rejected reported form stays absent
- **WHEN** a wellness row reports a form value that is not a valid number while CTL and ATL are valid
- **THEN** the value is reported as a mapping issue and no form observation is stored for that day, so readers show no form instead of a consumer-side CTL minus ATL.

#### Scenario: eFTP observations and their classification
- **WHEN** wellness `sportInfo` entries and athlete sport settings carry eFTP
- **THEN** each sport's first `sportInfo` entry yields one wellness-day eFTP observation, and each classified sport setting yields an athlete-record eFTP observation; the sport is classified from the first `types` entry (or `type` for `sportInfo`), `mmp_model` eFTP wins over the entry's own eFTP, and zero means unset.

Detailed contract (known limits of this mapper version, relied on by the performance readers; not requirements): entries identified only by `sport` or `sport_type` and settings whose ride type is not the first `types` entry yield no eFTP observation; two athlete sport settings of the same sport share one observation key, so the store keeps the last written. Mapper version 7 (Epic B) left these limits unchanged; a follow-up with the next mapper version decides whether to align them with the legacy readers. A derived form carries its method (`ctl_minus_atl`, version 1) and input fingerprint since version 7; readers use its value and unchanged DERIVED source kind only.

Evidence: `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`, `backend/providers/intervals_wellness_mapping.py:map_intervals_athlete_thresholds`; `tests/test_intervals_wellness_mapping.py:test_hrv_sdnn_maps_to_sdnn_in_milliseconds`, `tests/test_intervals_wellness_mapping.py:test_without_tsb_form_is_ctl_minus_atl_and_derived`, `tests/test_intervals_wellness_mapping.py:test_invalid_first_alias_is_not_replaced_by_the_later_alias`, `tests/test_intervals_wellness_mapping.py:test_rejected_tsb_is_reported_and_not_derived`, `tests/test_intervals_wellness_mapping.py:test_each_sport_keeps_its_first_entry`, `tests/test_intervals_wellness_mapping.py:test_untyped_entries_are_skipped_and_malformed_lists_reported`, `tests/test_intervals_wellness_mapping.py:test_sport_setting_mmp_model_eftp_wins_and_zero_is_unset`. The known limits are pinned by `tests/test_intervals_wellness_mapping.py:KnownEftpClassificationLimitTests` and `tests/test_canonical_store.py:test_two_athlete_eftp_observations_of_one_sport_keep_the_last_written`.
