from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sys
import tempfile
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import kick
import main
from render import curiosity_hook, subtitles


class DiscoveryTests(unittest.TestCase):
    def test_kick_pagination_time_window_and_velocity(self):
        now = datetime.now(timezone.utc)
        def clip(slug, minutes, views):
            return {"id": slug, "title": "Freeway chase", "created_at": (now - timedelta(minutes=minutes)).isoformat(),
                    "duration": 30, "views": views, "channel": {"slug": "lacy"},
                    "category": {"name": main.V}, "video_url": f"https://clips.kick.com/clips/ef/{slug}/playlist.m3u8"}
        a, b, c = clip("a", .5, 10), clip("b", 180, 90), clip("c", 181, 10000)
        pages = [{"clips": [None, {}, clip("future", -1, 90), a], "nextCursor": "page2"},
                 {"clips": [a, b, c, dict(a, duration=[]), dict(a, privacy="private")], "nextCursor": "page3"}]
        with patch.object(kick, "clip_page", side_effect=pages) as fetch:
            rows = kick.fetch_kick_clips(["lacy", "lacy"], now=now)
        self.assertEqual([c["id"] for c in rows], ["kick:a", "kick:b"])
        self.assertEqual([c["velocity"] for c in rows], [20, .5])
        self.assertEqual(rows[0]["media_url"], a["video_url"])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args.args[1]["cursor"], "page2")
        with patch.object(main, "fetch_kick_clips", return_value=rows), patch.object(main, "twitch_clips") as twitch:
            db = Mock()
            db.hmget.return_value = [None, "used"]
            game, clips = main.discover(db, {"kick:lacy": {}}, {})
            self.assertEqual((game, [c["id"] for c in clips]), (main.V, ["kick:a"]))
            twitch.assert_not_called()

    def test_empty_and_malformed_clip_and_caption_sequences(self):
        db = Mock()
        db.lrange.return_value = ["{}", "null", "[5]", '["game", null]', "broken"]
        self.assertEqual(main.queued(db, {}, {"lookback_hours": 3}), (main.VI, []))
        self.assertEqual(main.select({}, [None, {"game_id": []}, {"game_id": main.V, "id": []}], set()), (main.VI, []))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "captions.ass"
            words = [None, [], (0, None, "bad"), (0, 1, {}), (1, 2, "Exactly"), (2, 3, "here")]
            subtitles(path, words, 3, "What happens next?", "Streamer")
            data = path.read_text()
            self.assertIn("Exactly", data)
            self.assertNotIn("bad", data)
            subtitles(path, None, 3, "What happens next?", "Streamer")

    def test_silent_kick_clip_reaches_the_renderer(self):
        clip = {"id": "kick:clip_abc", "platform": "kick", "broadcaster_id": "kick:lacy",
                "title": "Ramp jump", "broadcaster_name": "Lacy", "campaign": {}, "duration": 30}
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            dl = Mock()
            dl.prepare_filename.return_value = str(root / "src0.mp4")
            dl.extract_info.return_value = {"id": "clip_abc"}
            downloader = unittest.mock.MagicMock()
            downloader.return_value.__enter__.return_value = dl
            whisper = Mock(side_effect=AssertionError("silent clips do not need Whisper"))
            stack.enter_context(patch.dict(sys.modules, {
                "yt_dlp": SimpleNamespace(YoutubeDL=downloader),
                "yt_dlp.utils": SimpleNamespace(DownloadError=OSError),
                "faster_whisper": SimpleNamespace(WhisperModel=whisper)}))
            stack.enter_context(patch.dict(os.environ, {"ALLOWED_KICK_CHANNELS": "lacy", "DELIVERY_MODE": "preview"}))
            stack.enter_context(patch.object(main, "store"))
            stack.enter_context(patch.object(main, "discover", return_value=(main.V, [clip])))
            stack.enter_context(patch.object(main, "probe", return_value={
                "streams": [{"codec_type": "video", "duration": "30"}]}))
            stack.enter_context(patch.object(main, "seconds", return_value=30))
            render = stack.enter_context(patch.object(main, "render_vertical_short"))
            render.side_effect = lambda source, output, *args, **kwargs: output.touch()
            main.prepare(root)
            dl.extract_info.assert_called_once_with("https://kick.com/lacy/clips/clip_abc", download=True)
            whisper.assert_not_called()
            self.assertEqual(render.call_args.kwargs["platform"], "Kick")
            self.assertEqual(render.call_args.args[5], "lacy")
            self.assertEqual(render.call_args.args[2:5], (30, [], "Ramp jump"))
            self.assertEqual(json.loads((root / "batch.json").read_text())["short"]["id"], "kick:clip_abc")

    def test_invalid_delivery_batch_fails_before_reserving(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "store") as store:
            root = Path(tmp)
            for group in (None, {}, "invalid", [None]):
                (root / "batch.json").write_text(json.dumps({"game": main.V, "short": {}, "group": group}))
                with self.assertRaises(ValueError):
                    main.publish(root)
            store.assert_not_called()

    def test_hooks_are_short_and_title_specific(self):
        self.assertNotEqual(curiosity_hook("Police chase"), curiosity_hook("A huge jump"))
        self.assertEqual(curiosity_hook("Who did that?"), "WHO DID THAT?")
        for title in ("GTA | Twitch | a totally random title", "", "chat reacts", "Drift", None):
            self.assertIn(len(curiosity_hook(title).split()), (3, 4, 5))
