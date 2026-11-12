from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from itertools import combinations
from pathlib import Path
from unittest.mock import patch

import main
from delivery import chunks


class Ledger:
    def __init__(self):
        self.data = {}
        self.daily = {}
    def pipeline(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def get(self, key):
        return self.daily.get(key)
    def incr(self, key):
        self.daily[key] = self.daily.get(key, 0) + 1
    def expire(self, key, ttl):
        pass
    def watch(self, *keys):
        pass
    def multi(self):
        pass
    def execute(self):
        pass
    def hset(self, key, mapping):
        self.data.update(mapping)
    def hmget(self, key, ids):
        return [self.data.get(i) for i in ids]


def clip(i, game="6", duration=30):
    return {"id": str(i), "duration": duration, "game_id": game, "view_count": i, "title": "The getaway",
            "created_at": "2026-11-11T10:00:00Z"}


class PipelineTests(unittest.TestCase):
    def test_fallback_uses_available_unused_clips(self):
        games = {main.VI: "6", main.V: "5"}
        clips = [clip(i) for i in range(5)] + [clip(6, "5")]
        self.assertEqual(main.select(games, clips, set())[1][0]["id"], "4")
        game, selected = main.select(games, clips, {"0"})
        self.assertEqual((game, [c["id"] for c in selected]), (main.V, ["6"]))
        self.assertEqual(main.select(games, clips, {"0", "6"})[0], main.VI)

    def test_velocity_ignores_generic_titles_and_prioritizes_a_newer_clip(self):
        now = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
        fresh = dict(clip(1), created_at=(now-timedelta(minutes=2)).isoformat(), view_count=20)
        old = dict(clip(2), created_at=(now-timedelta(hours=1)).isoformat(), view_count=120)
        generic = dict(fresh, id="3", title="Untitled")
        self.assertEqual([c["id"] for c in main.ranked([old, generic, fresh], set(), now)], ["1","2"])

    def test_cap_reserves_last_slot_and_rolls_over_at_utc_midnight(self):
        db = Ledger()
        with patch.dict(os.environ, {"DAILY_POST_CAP": "1"}):
            self.assertTrue(main.reserve(db, ["one"], "1"))
            self.assertFalse(main.reserve(db, ["two"], "2"))
            self.assertNotIn("two", db.data)
            with patch.object(main, "day_key", return_value="gta-clips:daily:next-day"):
                self.assertTrue(main.reserve(db, ["two"], "3"))
        self.assertEqual(sum(db.daily.values()), 2)

    def test_ranked_group_satisfies_duration_without_padding(self):
        for durations in ([8, 10, 19, 38], [62], [5, 30, 31], [15, 15, 15], [60, 6], [22]*5):
            group = main.compilation([clip(i, duration=d) for i, d in enumerate(durations)])
            possible = any(sum(combo) >= 63 for n in (2, 3) for combo in combinations(durations, n))
            self.assertEqual(bool(group), possible)
            if group:
                lengths = [c["duration"] for c in group]
                portions = main.portions(lengths)
                self.assertIn(len(group), (2, 3))
                self.assertTrue(all(0 < amount <= cap for amount, cap in zip(portions, lengths)))
                self.assertAlmostEqual(sum(portions), min(sum(lengths), 65))

    def test_preview_reads_ledger_without_reserving_when_no_candidates(self):
        db = Ledger()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ALLOWED_BROADCASTER_IDS":"123"}), \
                patch.object(main, "store", return_value=db), patch.object(main, "discover", return_value=(main.V, [])):
            main.prepare(Path(tmp))
            self.assertFalse(db.data)
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_partial_delivery_is_not_retried_after_lost_response(self):
        db = Ledger()
        env = {k:"example" for k in ["YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN","ARTIFACT_ID"]}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=True), \
                patch.object(main, "store", return_value=db), \
                patch.object(main.delivery, "youtube", side_effect=TimeoutError) as yt:
            root = Path(tmp)
            (root/"batch.json").write_text(json.dumps({"short": clip(1), "group":[clip(1),clip(2)], "game": main.V}))
            with self.assertRaisesRegex(RuntimeError, "TimeoutError"):
                main.publish(root)
            self.assertIn("github-artifact", db.data["2"])
            with self.assertRaisesRegex(RuntimeError, "reserved"):
                main.publish(root)
            self.assertEqual(yt.call_count, 1)

    def test_chunk_boundaries(self):
        for n in (1024, 5*1024**2, 16*1024**2+1, 65*1024**2):
            unit, sizes = chunks(n)
            self.assertEqual(sum(sizes), n)
            self.assertEqual(len(sizes), n//unit)
            self.assertTrue(all(s == unit for s in sizes[:-1]))
