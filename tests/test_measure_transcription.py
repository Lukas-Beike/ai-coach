import unittest

from scripts.measure_transcription import lan_base_url, normalized_words, word_errors


class MeasureTranscriptionTests(unittest.TestCase):
    def test_word_error_rate_ignores_case_and_punctuation(self):
        reference = normalized_words("Die Wissenschaft weist nun darauf hin, dass ...")
        self.assertEqual(
            reference, ["die", "wissenschaft", "weist", "nun", "darauf", "hin", "dass"]
        )
        self.assertEqual(
            word_errors(
                reference,
                normalized_words("die Wissenschaft weist nun darauf hin dass"),
            ),
            0,
        )
        # Substitutions, deletions and insertions each count one error.
        self.assertEqual(word_errors(["a", "b", "c"], ["a", "x"]), 2)
        self.assertEqual(word_errors(["a", "b"], ["a", "b", "c"]), 1)
        self.assertEqual(word_errors(["a", "b", "c"], ["x", "c", "d"]), 3)

    def test_only_lan_or_loopback_ip_servers_are_measured(self):
        self.assertEqual(
            lan_base_url("http://192.168.1.5:8000/v1"), "http://192.168.1.5:8000/v1"
        )
        self.assertEqual(lan_base_url("https://127.0.0.1"), "https://127.0.0.1:8000/v1")
        for value in ("http://example.com:8000", "http://8.8.8.8:8000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lan_base_url(value)


if __name__ == "__main__":
    unittest.main()
