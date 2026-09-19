import unittest

from backend.providers.audio import (
    VOICE_AUDIO_TYPES,
    audio_suffix,
    normalized_audio_type,
)


class AudioProviderTests(unittest.TestCase):
    def test_normalized_audio_type_removes_parameters_and_casefolds(self):
        self.assertEqual(normalized_audio_type(" Audio/WebM; codecs=opus "), "audio/webm")
        self.assertEqual(normalized_audio_type("audio/MP4;foo=bar"), "audio/mp4")
        self.assertEqual(normalized_audio_type(""), "")

    def test_audio_suffix_projects_supported_types_and_unknown_types_to_none(self):
        self.assertEqual(audio_suffix("audio/WAV; charset=binary"), ".wav")
        self.assertEqual(audio_suffix("audio/x-wav"), ".wav")
        self.assertEqual(audio_suffix("audio/unknown"), None)
        self.assertEqual(audio_suffix("text/plain"), None)
        self.assertEqual(set(VOICE_AUDIO_TYPES.values()), {".webm", ".mp4", ".ogg", ".mp3", ".wav", ".mpga", ".m4a"})


if __name__ == "__main__":
    unittest.main()
