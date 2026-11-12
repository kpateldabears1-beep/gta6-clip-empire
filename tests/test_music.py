import hashlib
import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.request import urlopen

from music_screen import MusicScreen, decode_audio, MUSIC_CUE
from render import subtitles


class CaptionTests(unittest.TestCase):
    def test_watermark_hook_and_pairs_cover_the_full_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            ass = Path(tmp) / "cut.ass"
            for platform in ("Kick", "Twitch"):
                subtitles(ass, [(1, 2, "look"), (2, 3, "here"), (4, 5, "now")], 6, "Who did that?",
                          "@Example", platform=platform, campaign="Creator event")
                data = ass.read_text()
                self.assertEqual([line for line in data.splitlines() if ",Credit,," in line],
                                 ["Dialogue: 0,0:00:00.00,0:00:06.00,Credit,,0,0,0,,Clip: @Example Creator event"])
                self.assertIn("0:00:00.00,0:00:06.00,Hook,", data)
                rows = [line.split(",", 9) for line in data.splitlines() if ",Caption,," in line]
                self.assertEqual(rows[0][1], "0:00:00.00")
                self.assertEqual(rows[-1][2], "0:00:06.00")
                self.assertTrue(all(row[2] == nxt[1] for row, nxt in zip(rows, rows[1:])))
                spoken = [row[-1] for row in rows if "Gameplay footage" not in row[-1]]
                self.assertEqual([re.sub(r"\{[^}]*\}", "", line) for line in spoken],
                                 ["look here", "look here", "here now"])
                self.assertTrue(all(r"\t(0,90," in line for line in spoken))


@unittest.skipUnless(os.getenv("CLIPS_TEST_MUSIC_MODEL") == "1", "live classifier fixtures run on GitHub")
class AudioScreenTests(unittest.TestCase):
    def test_long_instrumental_gap_without_whisper_words_is_flagged(self):
        import numpy as np
        from unittest.mock import Mock
        from music_screen import HOP
        screen = MusicScreen.__new__(MusicScreen)
        screen.spoken, screen.vocals, screen.music = [0], [1], 2
        screen.input, screen.output, screen.size, screen.shape = 0, 1, HOP, (HOP,)
        screen.model = Mock()
        screen.model.get_tensor.return_value = np.array([0.01, 0.01, 0.95])
        audible = np.ones(17 * HOP, dtype=np.float32)
        self.assertIsNone(screen.flagged_span(audible[:-HOP], [], []))
        self.assertIsNotNone(screen.flagged_span(audible, [], []))
        self.assertIsNone(screen.flagged_span(audible * 0, [], []))

    def test_song_is_flagged_and_narration_is_kept(self):
        from faster_whisper import WhisperModel

        # Librosa's credited examples: Karissa Hobbs (CC BY 3.0) and Garth Comira (LibriSpeech).
        fixtures = [
            ("Karissa_Hobbs_-_Lets_Go_Fishin", "27b3667c396c1831511aa3c415fcf582b6e8be560cafb844c5b67b76b72c1cb3", True),
            ("5703-47212-0000", "a284612b46af0535f7e1873758c4387bb8369f6dbbe192ffdec1f171108f98dd", False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            screen = MusicScreen()
            whisper = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=2, download_root=tmp)
            for name, digest, expected in fixtures:
                with self.subTest(name=name):
                    src = Path(tmp) / (name + ".ogg")
                    with urlopen("https://librosa.org/data/audio/" + src.name, timeout=30) as response:
                        audio = response.read()
                    self.assertEqual(hashlib.sha256(audio).hexdigest(), digest)
                    src.write_bytes(audio)
                    samples = decode_audio(src, 43.9, start=30 if expected else 0)
                    segments, _ = whisper.transcribe(samples, word_timestamps=True, vad_filter=True, beam_size=1)
                    words, cues = [], []
                    for segment in segments:
                        words.extend((w.start, w.end, w.word) for w in segment.words or [])
                        if MUSIC_CUE.search(segment.text):
                            cues.append((segment.start, segment.end))
                    span = screen.flagged_span(samples, words, cues)
                    print(f"Audio screen fixture {name}: {span or 'kept'}")
                    self.assertEqual(bool(span), expected, f"classifier result for {name}: {span}")
