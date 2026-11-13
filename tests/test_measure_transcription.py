import unittest

from scripts.measure_transcription import normalized_words, word_errors


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


if __name__ == "__main__":
    unittest.main()
