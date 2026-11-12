import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from render import analyze_audio, join, probe, render, seconds


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg with libass")
class MediaTests(unittest.TestCase):
    def test_encoder_caps_overlong_single_segment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, out = root / "long.mp4", root / "cut.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=160x90:r=5",
                            "-t", "45", "-c:v", "libx264", str(source)], check=True)
            render(source, out, 45, [], "The getaway", "TestChannel", platform="Twitch")
            self.assertTrue(43.8 < seconds(out) < 44)
            self.assertIn("Clip: @TestChannel on Twitch", out.with_suffix(".ass").read_text())
            for moment in ("0.2", "43.7"):
                # The source is plain blue: bright neutral pixels here are burned-in watermark text.
                pixels = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", moment, "-i", str(out),
                    "-vf", "crop=900:150:40:1660,format=gray", "-frames:v", "1", "-f", "rawvideo", "-"])
                self.assertGreater(sum(p > 210 for p in pixels), 1000)

    def test_render_and_join_with_speech_timing_and_a_silent_source(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parts = []
            for i, duration in enumerate([33, 32]):
                source = root / f"source{i}.mp4"
                cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=320x180:r=10,drawbox=x=0:y=0:w=96:h=54:color=red:t=fill"]
                if i == 0:
                    cmd += ["-f", "lavfi", "-i", "sine=frequency=500", "-af", "adelay=2000"]
                subprocess.run(cmd + ["-t", str(duration), "-c:v", "libx264", str(source)], check=True)
                if i == 0:
                    trim, active = analyze_audio(source, duration)
                    self.assertTrue(active)
                    self.assertAlmostEqual(trim, 1.5)
                part = root / f"part{i}.mp4"
                render(source, part, duration, [(0, .6, "Look"), (.6, 1, "here")], "The getaway", "Tester",
                       notes=[{"start": 0, "end": 3, "text": "Watch the gap"}],
                       facecam=[0, 0, .3, .3] if i else None)
                self.assertLess(seconds(part), 58)
                if i:
                    for y, dominant in [(1148, 2), (1152, 0)]:
                        rgb = subprocess.check_output([
                            "ffmpeg", "-v", "error", "-ss", "2", "-i", str(part), "-vf",
                            f"crop=2:2:100:{y},scale=1:1,format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"])
                        self.assertGreater(rgb[dominant], 180, (y, rgb))
                parts.append(part)
            joined = root / "tiktok.mp4"
            join(parts, joined)
            self.assertTrue(62 < seconds(joined) < 66)
            streams = probe(joined)["streams"]
            v = next(s for s in streams if s["codec_type"] == "video")
            self.assertEqual((v["width"], v["height"], v["codec_name"]), (1080, 1920, "h264"))
            self.assertTrue(any(s["codec_name"] == "aac" and s["sample_rate"] == "44100"
                                for s in streams))
            durations = [float(s["duration"]) for s in streams if s["codec_type"] in ("audio", "video")]
            self.assertLess(max(durations) - min(durations), 0.08)
            subprocess.run(["ffmpeg","-v","error","-xerror","-i",str(joined),"-f","null","-"], check=True)
