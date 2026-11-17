import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import delivery
from scripts import release_review as release


class ReviewedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(Path("reviews/releases/lysium-wheel.json").read_text())
        self.plan["sha256"] = hashlib.sha256(b"reviewed fixture").hexdigest()
        self.plan["bytes"] = len(b"reviewed fixture")
        self.db, self.client = MagicMock(), MagicMock()
        self.db.hget.return_value = None
        self.client.head_object.return_value = {
            "ContentLength": self.plan["bytes"], "ContentType": "video/mp4",
            "Metadata": {"sha256": self.plan["sha256"]}}
        self.client.download_file.side_effect = lambda bucket, key, path: Path(path).write_bytes(b"reviewed fixture")
        self.env = {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "123",
                    "YOUTUBE_CHANNEL_ID": self.plan["channel_id"],
                    "YOUTUBE_CLIENT_ID": "fixture", "YOUTUBE_CLIENT_SECRET": "fixture",
                    "YOUTUBE_REFRESH_TOKEN": "fixture"}
        self.receipt = {"id": "fixture1234", "status": {"privacyStatus": "public", "uploadStatus": "processed"},
                        "snippet": {"channelId": self.plan["channel_id"], "publishedAt": "2026-11-16T12:00:00Z"}}

    def approve(self):
        self.plan["approval"] = {"status": "approved", "full_playback_reviewed": True,
                                 "evidence_url": "https://example.com/test-only-approval",
                                 "approved_release_sha256": release.release_digest(self.plan)}

    def test_pending_draft_cannot_access_services_or_publish(self):
        with patch.object(release, "store") as store, tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Release blocked"):
                release.run(self.plan, Path(tmp), True)
            store.assert_not_called()

    def test_approval_binds_bytes_source_destination_and_complete_caption(self):
        self.approve()
        release.validate(self.plan, True)
        mutations = [lambda p: p.update(sha256="a"*64), lambda p: p.update(bytes=30),
                     lambda p: p.update(channel_id="UC"+"a"*22),
                     lambda p: p["youtube"].update(title="Changed hook"),
                     lambda p: p["youtube"].update(description="Changed caption"),
                     lambda p: p["youtube"]["tags"].append("GTA6"),
                     lambda p: p.update(clip_id="another-clip"),
                     lambda p: p["approval"].update(full_playback_reviewed=False),
                     lambda p: p["approval"].update(evidence_url=None)]
        for mutate in mutations:
            changed = copy.deepcopy(self.plan)
            mutate(changed)
            with self.assertRaises(ValueError):
                release.validate(changed, True)

    def test_exact_caption_is_not_rewritten_or_extended(self):
        metadata = self.plan["youtube"]
        body = delivery.youtube_metadata({}, "Grand Theft Auto V", metadata)
        for field in ("title", "description", "tags"):
            self.assertEqual(body["snippet"][field], metadata[field])
        fallback = delivery.youtube_metadata({"title": "Getaway", "broadcaster_name": "Creator", "url": "source"}, "Grand Theft Auto V")
        self.assertEqual(fallback["snippet"]["title"], "Getaway #Shorts")

    def exercise(self, publishing=False, failure=None):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, self.env, clear=True), \
                patch.object(release, "store", return_value=self.db), \
                patch.object(release.cloud_archive, "storage", return_value=(self.client, "bucket")), \
                patch.object(release, "reserve", return_value=1) as reserve, \
                patch.object(release.delivery, "youtube", return_value=self.receipt) as youtube:
            if failure:
                with self.assertRaisesRegex(ValueError, failure):
                    release.run(self.plan, Path(tmp), publishing)
            else:
                release.run(self.plan, Path(tmp), publishing)
            return reserve, youtube

    def test_verify_retrieves_exact_r2_bytes_without_reserving_or_uploading(self):
        reserve, youtube = self.exercise()
        self.client.download_file.assert_called_once()
        reserve.assert_not_called()
        youtube.assert_not_called()
        self.db.hset.assert_not_called()

    def test_corrupt_media_stops_before_reservation(self):
        self.approve()
        self.client.download_file.side_effect = lambda bucket, key, path: Path(path).write_bytes(b"different bytes")
        reserve, youtube = self.exercise(True, "Downloaded bytes differ")
        reserve.assert_not_called()
        youtube.assert_not_called()

    def test_existing_source_is_not_downloaded_or_reposted(self):
        self.approve()
        self.db.hget.return_value = "pending:previous-run"
        reserve, youtube = self.exercise(True, "already reserved")
        self.client.download_file.assert_not_called()
        reserve.assert_not_called()
        youtube.assert_not_called()

    def test_daily_cap_stops_upload(self):
        self.approve()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, self.env, clear=True), \
                patch.object(release, "store", return_value=self.db), \
                patch.object(release.cloud_archive, "storage", return_value=(self.client, "bucket")), \
                patch.object(release, "reserve", return_value=0), \
                patch.object(release.delivery, "youtube") as youtube:
            with self.assertRaisesRegex(ValueError, "Daily cap reached"):
                release.run(self.plan, Path(tmp), True)
            youtube.assert_not_called()

    def test_cloud_and_destination_guards(self):
        self.env["GITHUB_ACTIONS"] = "false"
        self.exercise(failure="cloud runner")
        self.env["GITHUB_ACTIONS"] = "true"
        self.env["YOUTUBE_CHANNEL_ID"] = "different"
        self.exercise(failure="destination differs")

    def test_approved_upload_uses_exact_caption_and_records_receipt(self):
        self.approve()
        reserve, youtube = self.exercise(True)
        reserve.assert_called_once_with(self.db, [self.plan["clip_id"]], "123")
        self.assertEqual(youtube.call_args.kwargs["approved_metadata"], self.plan["youtube"])
        record = json.loads(self.db.hset.call_args.args[2])
        self.assertEqual(record["youtube"], self.receipt["id"])
        self.assertEqual(record["release_sha256"], release.release_digest(self.plan))
        self.client.put_object.assert_called_once()

    def test_uncertain_upload_keeps_reservation_and_no_second_attempt(self):
        self.approve()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, self.env, clear=True), \
                patch.object(release, "store", return_value=self.db), \
                patch.object(release.cloud_archive, "storage", return_value=(self.client, "bucket")), \
                patch.object(release, "reserve", return_value=1) as reserve, \
                patch.object(release.delivery, "youtube", side_effect=TimeoutError) as youtube:
            with self.assertRaises(TimeoutError):
                release.run(self.plan, Path(tmp), True)
            reserve.assert_called_once()
            youtube.assert_called_once()
            self.db.hdel.assert_not_called()
            self.db.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
