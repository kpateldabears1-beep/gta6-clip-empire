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

    def test_gta_category_candidates_keep_their_actual_streamer(self):
        now = datetime.now(timezone.utc)
        row = {"id": "new", "title": "Freeway chase", "created_at": now.isoformat(), "duration": 22,
               "views": 10, "channel": {"slug": "newcreator"},
               "category": {"name": "Grand Theft Auto V (GTA)", "slug": "grand-theft-auto-v"}}
        with patch.object(kick, "clip_page", side_effect=[{"clips": [row]}, {"clips": [row]}]):
            clips = kick.fetch_kick_clips([], now=now, include_gta_categories=True)
        self.assertEqual([(c["broadcaster_id"], c["game_id"]) for c in clips], [("kick:newcreator", main.V)])
        with patch.object(kick, "clip_page", return_value={"clips": [row]}):
            self.assertFalse(kick.fetch_kick_clips(["licensed-other-creator"], now=now))

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

    def test_campaign_follows_allowed_channel_through_discovery_and_old_queue(self):
        config = {"lookback_hours": 3, "priority_streamers": [], "watchlist": [
            {"broadcaster_id": "123", "username": "licensed", "campaign_watermark": "EVENT-42"},
            {"broadcaster_id": "456", "username": "other", "campaign_watermark": "OTHER"}]}
        with patch.object(Path, "read_text", return_value=json.dumps(config)), patch.dict(os.environ, {
                "ALLOWED_BROADCASTER_IDS": "123", "ALLOWED_KICK_CHANNELS": "Licensed"}):
            channels, _ = main.sources_config()
        self.assertEqual(set(channels), {"123", "kick:licensed"})
        self.assertEqual(channels["123"]["campaign_watermark"], "EVENT-42")
        clip = {"id": "kick:k1", "broadcaster_id": "kick:licensed", "game_id": main.V, "title": "A close finish",
                "view_count": 10, "duration": 30, "platform": "kick", "created_at": datetime.now(timezone.utc).isoformat()}
        twitch = dict(clip, id="t1", broadcaster_id="123", platform="twitch", campaign=channels["123"])
        db = Mock()
        db.hmget.side_effect = lambda _, keys: [None] * len(keys)
        with patch.object(main, "fetch_kick_clips", return_value=[clip]), patch.object(main, "twitch_clips",
                return_value=({main.V: "42"}, {"t1": twitch})):
            game, clips = main.discover(db, channels, config)
        self.assertEqual({c["id"] for c in clips}, {"t1", "kick:k1"})
        self.assertTrue(all(c["campaign"]["campaign_watermark"] == "EVENT-42" for c in clips))
        db.lrange.return_value = [json.dumps([game, dict(clip, campaign=None)]),
                                  json.dumps([game, dict(clip, duration=[])])]
        _, queued = main.queued(db, channels, config)
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["campaign"]["campaign_watermark"], "EVENT-42")

    def test_roster_reads_kick_handles_once_and_excludes_twitch_only_creators(self):
        with patch.object(kick, "clip_page", return_value={"clips": []}) as page:
            self.assertEqual(kick.fetch_kick_clips(), [])
            self.assertCountEqual([call.args[0] for call in page.call_args_list], ["lacy", "adinross", "n3on"])

    def test_helix_ignores_bad_rows_and_empty_pagination(self):
        http = Mock()
        http.post.return_value.json.return_value = {"access_token": "test-token"}
        http.get.return_value.json.side_effect = [
            {"data": [None, {"id": "42", "name": main.V}]},
            {"data": [{"id": [], "login": "bad"}, {"id": "123", "login": "licensed"}]},
            {"data": [None, {"id": "x", "broadcaster_id": "123", "game_id": "42"}], "pagination": None}]
        with patch.dict(sys.modules, {"requests": http}), patch.dict(os.environ, {
                "TWITCH_CLIENT_ID": "test", "TWITCH_CLIENT_SECRET": "test"}):
            games, clips = main.twitch_clips({"123": {}}, {"target_game_names": [main.V], "lookback_hours": 3},
                                             datetime.now(timezone.utc))
        self.assertEqual(games, {main.V: "42"})
        self.assertEqual(clips["x"]["broadcaster_login"], "licensed")

    def test_kick_still_runs_when_twitch_is_unavailable(self):
        with patch.object(main, "twitch_clips", side_effect=OSError("offline")), patch.object(
                main, "fetch_kick_clips", return_value=[]) as kick_fetch:
            channels = {"123": {}, "kick:lacy": {}}
            self.assertEqual(main.discover(Mock(), channels, {}), (main.VI, []))
            self.assertEqual(kick_fetch.call_args.args, (["lacy"],))
            kick_fetch.side_effect = RuntimeError("Kick unavailable")
            with self.assertRaises(RuntimeError):
                main.discover(Mock(), channels, {})

    def test_only_speech_rich_nonmusical_cuts_are_rendered(self):
        clip = {"id": "kick:clip_abc", "platform": "kick", "broadcaster_id": "kick:lacy",
                "title": "Ramp jump", "broadcaster_name": "Lacy", "campaign": {"campaign_watermark": "CODE1"}, "duration": 30}
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            stack.enter_context(patch.object(main, "music_mix", return_value="test track"))
            dl = Mock()
            dl.prepare_filename.return_value = str(root / "src0.mp4")
            dl.extract_info.return_value = {"id": "clip_abc"}
            downloader = unittest.mock.MagicMock()
            downloader.return_value.__enter__.return_value = dl
            whisper = Mock()
            def transcript(count):
                words = [SimpleNamespace(start=i, end=i+.5, word=w) for i, w in enumerate(["watch", "that", "last", "turn"][:count])]
                return [SimpleNamespace(start=0, end=5, text=" ".join(w.word for w in words), words=words)], None
            whisper.return_value.transcribe.side_effect = [transcript(3), transcript(4), transcript(4), transcript(4)]
            stack.enter_context(patch.dict(sys.modules, {
                "yt_dlp": SimpleNamespace(YoutubeDL=downloader),
                "yt_dlp.utils": SimpleNamespace(DownloadError=OSError),
                "faster_whisper": SimpleNamespace(WhisperModel=whisper)}))
            stack.enter_context(patch.dict(os.environ, {"ALLOWED_KICK_CHANNELS": "lacy", "DELIVERY_MODE": "preview"}))
            stack.enter_context(patch.object(main, "store"))
            flagged = dict(clip, id="kick:clip_music")
            second = dict(clip, id="kick:clip_two", broadcaster_id="kick:n3on", duration=34,
                          campaign={"campaign_watermark": "CODE2"})
            stack.enter_context(patch.object(main, "discover", return_value=(main.V, [dict(clip, id="kick:silent"), dict(clip, id="kick:sparse"), flagged, clip, second])))
            stack.enter_context(patch.object(main, "decode_audio", return_value=[0]))
            stack.enter_context(patch.object(main, "audio_activity", return_value=(0, True)))
            screen = stack.enter_context(patch.object(main, "MusicScreen"))
            screen.return_value.flagged_span.side_effect = [(0, 8.16), None, None]
            video = {"codec_type": "video", "duration": "30"}
            with_audio = {"streams": [video, {"codec_type": "audio"}]}
            stack.enter_context(patch.object(main, "probe", side_effect=[
                {"streams": [video]}, with_audio, with_audio, with_audio,
                {"streams": [dict(video, duration="34"), {"codec_type": "audio"}]}]))
            stack.enter_context(patch.object(main, "seconds", side_effect=[30, 64]))
            render = stack.enter_context(patch.object(main, "render_vertical_short"))
            render.side_effect = lambda source, output, *args, **kwargs: output.touch()
            stack.enter_context(patch.object(main, "join", side_effect=lambda parts, output: output.touch()))
            main.prepare(root)
            self.assertEqual([call.kwargs["campaign"] for call in render.call_args_list], ["CODE1", "CODE1", "CODE2"])
            dl.extract_info.assert_any_call("https://kick.com/lacy/clips/clip_abc", download=True)
            self.assertEqual(whisper.return_value.transcribe.call_count, 4)
            self.assertEqual(screen.return_value.flagged_span.call_count, 3)
            self.assertEqual(render.call_args.kwargs["platform"], "Kick")
            self.assertEqual([call.args[5] for call in render.call_args_list], ["lacy", "lacy", "n3on"])
            self.assertEqual(len(render.call_args_list[0].args[3]), 4)
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
        self.assertEqual(curiosity_hook("Police chase", "DID THEY ESCAPE?"), "DID THEY ESCAPE?")
        self.assertEqual(curiosity_hook("Police chase", "one two three four five six"), curiosity_hook("Police chase"))
        for title in ("GTA | Twitch | a totally random title", "", "chat reacts", "Drift", None):
            self.assertIn(len(curiosity_hook(title).split()), (3, 4, 5))
