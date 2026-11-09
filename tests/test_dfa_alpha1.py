"""DFA-a1 first threshold calculation (#1867) on synthetic RR series.

Expected values come from the method's literature, not from the code under test:
white noise has a scaling exponent of 0.5 and an integrated (random walk) series
1.5. The crossing test builds a ramp whose beat-to-beat correlation, and so the
exponent, falls with heart rate by design: an AR(1) noise with coefficient 0.25
has an exponent of about 0.75 over box sizes 4 to 16 (simulated with long series),
and the coefficient is 0.9 * (170 - HR) / 60, so the designed crossing is 153 bpm.
"""

import random
import unittest

from backend.canonical import dfa_alpha1 as dfa
from backend.canonical.vocabulary import DfaQuality


def ramp(seed, *, low=110, high=170, minutes=30, artifacts_every=0):
    """RR intervals (ms) of a heart rate ramp whose noise correlation falls with HR."""
    rng = random.Random(seed)
    series, elapsed, noise = [], 0.0, 0.0
    while elapsed < minutes * 60:
        rate = low + (high - low) * elapsed / (minutes * 60)
        coefficient = 0.9 * (high - rate) / (high - low)
        noise = coefficient * noise + rng.gauss(0, 1)
        interval = 60_000 / rate + 12 * noise * (1 - coefficient**2) ** 0.5
        series.append(interval)
        elapsed += interval / 1000
    if artifacts_every:
        for index in range(7, len(series), artifacts_every):
            series[index] = 3000.0
    return series


def steady(seed, rate=140, minutes=12, coefficient=0.9):
    rng = random.Random(seed)
    series, noise = [], 0.0
    for _ in range(int(minutes * 60 * rate / 60)):
        noise = coefficient * noise + rng.gauss(0, 1)
        series.append(60_000 / rate + 12 * noise)
    return series


class ArtifactTests(unittest.TestCase):
    def test_values_outside_300_to_2000_ms_are_dropped_edges_included(self) -> None:
        for value, dropped in (
            (299.0, True),
            (300.0, False),
            (2000.0, False),
            (2001.0, True),
            (float("nan"), True),
        ):
            with self.subTest(value=value):
                self.assertEqual(dfa.artifact_flags([value]), [dropped])
        self.assertEqual(dfa.artifact_flags([2000.0, 1900.0]), [False, False])

    def test_a_beat_changing_more_than_20_percent_is_dropped_against_the_last_good_beat(
        self,
    ) -> None:
        # 1000 is +25 % of 800 and dropped; 800 after it is compared with the last
        # accepted 800 and kept; 960 is exactly +20 % and kept; 1153 is 193 above 960.
        self.assertEqual(
            dfa.artifact_flags([800.0, 1000.0, 800.0, 960.0, 1153.0]),
            [False, True, False, False, True],
        )

    def test_a_real_level_change_is_accepted_after_five_rejected_beats(self) -> None:
        flags = dfa.artifact_flags([800.0, *[1100.0] * 6])
        self.assertEqual(flags, [False, True, True, True, True, False, False])

    def test_the_artifact_share_is_reported_for_the_recording(self) -> None:
        series = steady(1)
        for index in range(3, len(series), 25):
            series[index] = 250.0
        _, share = dfa.rolling_windows([series])
        self.assertAlmostEqual(share, 1 / 25, delta=0.002)

    def test_windows_above_5_percent_artifacts_are_rejected(self) -> None:
        series = steady(2)
        clean, _ = dfa.rolling_windows([series])
        for index in range(3, len(series), 10):
            series[index] = 250.0  # 10 % of the beats
        windows, share = dfa.rolling_windows([series])
        self.assertGreater(len(clean), 10)
        self.assertEqual(windows, [])
        self.assertAlmostEqual(share, 0.1, delta=0.005)
        self.assertIsNone(dfa.first_threshold([series]))


class ScalingTests(unittest.TestCase):
    def test_white_noise_scales_near_one_half(self) -> None:
        rng = random.Random(3)
        noise = [rng.gauss(0, 1) for _ in range(1500)]
        self.assertAlmostEqual(dfa.alpha1(noise) or 0, 0.5, delta=0.12)

    def test_a_random_walk_scales_near_one_and_a_half(self) -> None:
        rng = random.Random(4)
        walk, level = [], 0.0
        for _ in range(1500):
            level += rng.gauss(0, 1)
            walk.append(level)
        self.assertAlmostEqual(dfa.alpha1(walk) or 0, 1.5, delta=0.12)

    def test_a_series_too_short_or_without_fluctuation_has_no_exponent(self) -> None:
        self.assertIsNone(dfa.alpha1([800.0] * 31))
        self.assertIsNone(dfa.alpha1([800.0] * 200))


class DetrendTests(unittest.TestCase):
    def test_a_linear_trend_is_removed_exactly(self) -> None:
        # A straight line has no second difference, so smoothness priors keep all of it.
        line = [900.0 - 1.5 * index for index in range(300)]
        self.assertLess(max(abs(value) for value in dfa.detrend(line)), 1e-6)

    def test_the_trend_solves_the_smoothness_priors_equation(self) -> None:
        rng = random.Random(9)
        series = [600 + rng.gauss(0, 20) + 2 * index for index in range(60)]
        smoothing = 7.0
        trend = [a - b for a, b in zip(series, dfa.detrend(series, smoothing))]
        # (I + smoothing^2 D'D) trend == series, with D'D built from second differences.
        weight = smoothing**2
        product = list(trend)
        for row in range(len(trend) - 2):
            second = trend[row] - 2 * trend[row + 1] + trend[row + 2]
            product[row] += weight * second
            product[row + 1] -= 2 * weight * second
            product[row + 2] += weight * second
        for got, want in zip(product, series):
            self.assertAlmostEqual(got, want, delta=1e-6)

    def test_a_ramp_no_longer_inflates_alpha1(self) -> None:
        rng = random.Random(10)
        noise = [rng.gauss(0, 1) for _ in range(300)]
        ramped = [value + 0.5 * index for index, value in enumerate(noise)]
        self.assertGreater(dfa.alpha1(ramped) or 0, 1.4)
        self.assertAlmostEqual(dfa.alpha1(dfa.detrend(ramped)) or 0, 0.5, delta=0.12)

    def test_short_series_are_returned_unchanged(self) -> None:
        self.assertEqual(dfa.detrend([1.0, 2.0]), [1.0, 2.0])
        self.assertEqual(dfa.detrend([]), [])


class DropoutTests(unittest.TestCase):
    def test_windows_never_span_a_break(self) -> None:
        whole = steady(11, minutes=12)
        joined, _ = dfa.rolling_windows([whole])
        # 12 minutes cut into two 3-minute pieces and one 6-minute piece: a window
        # of 2 minutes fits in each piece only, never across the cuts.
        third = len(whole) // 4
        pieces = [whole[:third], whole[third : 2 * third], whole[2 * third :]]
        split, _ = dfa.rolling_windows(pieces)
        self.assertGreater(len(joined), len(split))
        per_piece = sum(len(dfa.rolling_windows([piece])[0]) for piece in pieces)
        self.assertEqual(len(split), per_piece)

    def test_a_gap_inside_a_would_be_window_rejects_it(self) -> None:
        # Two 90-second pieces: together 3 minutes would hold windows, apart none.
        rate = 140
        pieces = [
            steady(12, rate=rate, minutes=1.5),
            steady(13, rate=rate, minutes=1.5),
        ]
        self.assertEqual(dfa.rolling_windows(pieces)[0], [])
        self.assertGreater(len(dfa.rolling_windows([pieces[0] + pieces[1]])[0]), 0)


class CrossingTests(unittest.TestCase):
    def test_the_estimate_is_the_heart_rate_where_alpha1_reaches_075(self) -> None:
        for seed in (0, 1, 2):
            with self.subTest(seed=seed):
                result = dfa.first_threshold([ramp(seed)])
                self.assertIsNotNone(result)
                assert result is not None
                self.assertAlmostEqual(result.estimate_bpm, 153.0, delta=6.0)
                self.assertGreaterEqual(result.windows, 40)
                self.assertEqual(result.artifact_share, 0.0)
                self.assertIs(result.quality, DfaQuality.GOOD)
                self.assertEqual(result.method, dfa.METHOD_VERSION)

    def test_artifacts_lower_the_quality_but_keep_the_estimate(self) -> None:
        # One beat in 30 is 3.3 %: below the window limit, above the good limit.
        result = dfa.first_threshold([ramp(0, artifacts_every=30)])
        assert result is not None
        self.assertAlmostEqual(result.estimate_bpm, 153.0, delta=8.0)
        self.assertGreater(result.artifact_share, dfa.GOOD_MAX_ARTIFACT_SHARE)
        self.assertIs(result.quality, DfaQuality.LOW)

    def test_a_steady_run_never_crosses_and_gives_no_estimate(self) -> None:
        self.assertIsNone(dfa.first_threshold([steady(5)]))
        self.assertIsNone(dfa.first_threshold([steady(6, coefficient=0.0)]))

    def test_a_ramp_whose_alpha1_stays_on_one_side_gives_no_estimate(self) -> None:
        def correlated_ramp(coefficient):
            rng = random.Random(7)
            series, elapsed, noise = [], 0.0, 0.0
            while elapsed < 30 * 60:
                rate = 110 + 60 * elapsed / (30 * 60)
                noise = coefficient * noise + rng.gauss(0, 1)
                interval = 60_000 / rate + 12 * noise
                series.append(interval)
                elapsed += interval / 1000
            return series

        self.assertIsNone(dfa.first_threshold([correlated_ramp(0.9)]))  # always high
        self.assertIsNone(dfa.first_threshold([correlated_ramp(0.0)]))  # always low

    def test_too_few_windows_give_no_estimate(self) -> None:
        self.assertIsNone(dfa.first_threshold([ramp(0)[:700]]))
        self.assertIsNone(dfa.first_threshold([]))

    def test_windows_with_a_fast_heart_rate_step_are_left_out(self) -> None:
        # Alternating 2 minutes at 120 and 160 bpm: no steady window exists.
        series = []
        for block in range(8):
            rate = 120 if block % 2 == 0 else 160
            series.extend([60_000 / rate] * int(rate * 2))
        rng = random.Random(8)
        series = [value + rng.gauss(0, 8) for value in series]
        windows, _ = dfa.rolling_windows([series])
        for window in windows:
            self.assertTrue(115 < window.heart_rate_bpm < 165)
        spread = [w.heart_rate_bpm for w in windows]
        # Windows straddling a change are the ones that were removed.
        self.assertTrue(
            all(abs(rate - 120) < 4 or abs(rate - 160) < 4 for rate in spread)
        )


if __name__ == "__main__":
    unittest.main()
