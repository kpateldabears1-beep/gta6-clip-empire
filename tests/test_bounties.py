import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import bounties
import delivery
import main
import monitoring


class BountyTests(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.db = MagicMock()
        self.db.get.side_effect = self.values.get
        def put(k, v, nx=False, ex=None):
            if not nx or k not in self.values:
                self.values[k] = v
        self.db.set.side_effect = put
        self.db.delete.side_effect = self.values.pop
        self.c = {"id": "kick:123", "broadcaster_login": "test",
                  "campaign": {"priority": True, "campaign_watermark": "W-4"}}
        self.when = "2026-01-01T12:00:00Z"
        self.yt = "https://www.youtube.com/shorts/abcdefghijk"

    def test_external_publications_retry_discord_only_and_deduplicate(self):
        bounties.register(self.db, "42", "short", [self.c, dict(self.c, campaign={"campaign_watermark": "unused"})])
        urls = {"instagram": "https://www.instagram.com/reel/abcd/", "rumble": "https://rumble.com/v123abc-test.html",
                "tiktok": "https://www.tiktok.com/@account/video/123", "youtube": self.yt}
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://example.invalid/private", "TELEGRAM_BOT_TOKEN": "unused",
                                     "TELEGRAM_CHAT_ID": "unused"}, clear=True), patch.object(monitoring, "urlopen") as send:
            for platform, url in urls.items():
                payload = dict(run_id=42, cut="short", platform=platform, url=url, published_at=self.when)
                send.side_effect = OSError()
                with self.assertRaises(RuntimeError):
                    bounties.published_event(self.db, payload)
                send.side_effect = None
                bounties.published_event(self.db, payload)
                data = json.loads(send.call_args.args[0].data)
                self.assertIn(url.rstrip("/"), data["content"])
                self.assertIn("@test · W-4", data["content"])
                self.assertIn("<t:1767270600:", data["content"])
                self.assertNotIn("unused", data["content"])
                self.assertEqual(send.call_args.args[0].full_url, os.environ["DISCORD_WEBHOOK_URL"])
                bounties.published_event(self.db, payload)
            self.assertEqual(send.call_count, 8)
            self.assertFalse(any(":pending:" in k for k in self.values))

    def test_invalid_receipts_and_non_priority_cuts(self):
        for url in ["https://rumble.com.evil.example/v123-clip.html", "https://rumble.com/account/", "file:///v123-x.html"]:
            with self.assertRaises(ValueError):
                bounties.permalink("rumble", url)
        for campaign in ({"campaign_watermark": "code"}, {"priority": True, "campaign_watermark": " "}):
            self.assertFalse(bounties.register(self.db, "42", "short", [dict(self.c, campaign=campaign)]))
        self.assertFalse(bounties.queue(self.db, "42", "short", "youtube", "receipt"))

    def test_publish_queues_confirmed_receipt_and_reconciles_after_processing(self):
        self.c.update(title="Example title", broadcaster_name="Test", url="https://example.com/credit")
        env = {k: "test" for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")}
        receipt = {"id": "abcdefghijk", "status": {"uploadStatus": "uploaded"},
                   "snippet": {"channelId": "owner", "publishedAt": self.when}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=True), \
                patch.object(main, "store", return_value=self.db), patch.object(main, "reserve", return_value=1), \
                patch.object(delivery, "youtube", return_value=receipt) as upload, patch.object(main, "notify_post"), \
                patch.object(delivery, "public_youtube_post", side_effect=[None, [(self.yt, self.when)]]), \
                patch.object(bounties, "send_alert", return_value=True) as send:
            root = Path(tmp)
            (root / "batch.json").write_text(json.dumps({"game": main.V, "short": self.c, "group": [], "batch_id": "42"}))
            main.publish(root)
            send.assert_not_called()
            self.db.scan_iter.return_value = [k for k in self.values if ":pending:" in k]
            bounties.reconcile(self.db)
            send.assert_called_once()
            upload.assert_called_once()
            self.assertIn(self.yt, send.call_args.args[0])

    def test_youtube_public_feed_must_contain_this_video(self):
        receipt = {"id": "abcdefghijk", "status": {"privacyStatus": "private", "uploadStatus": "processed"},
                   "snippet": {"channelId": "owner", "publishedAt": self.when}}
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
               '<entry><yt:videoId>abcdefghijk</yt:videoId><published>'+self.when+'</published></entry></feed>')
        with patch("urllib.request.urlopen", side_effect=[io.BytesIO(b"<feed/>"), io.BytesIO(xml.encode())]):
            self.assertIsNone(delivery.public_youtube_post(receipt))
            self.assertEqual(delivery.public_youtube_post(receipt), [(self.yt, self.when)])

    def test_tiktok_uses_moderated_video_id_and_its_share_url(self):
        api = MagicMock()
        live = {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [123]}
        video = {"id": "123", "create_time": 1767268800, "share_url": "https://www.tiktok.com/@test/video/123"}
        data = [{"status": "SEND_TO_USER_INBOX"}, {"status": "PUBLISH_COMPLETE"}, live, {"videos": [video]}]
        api.post.return_value.json.side_effect = [{"error": {"code": "ok"}, "data": d} for d in data]
        with patch.dict("sys.modules", {"requests": api}), patch.object(delivery, "tiktok_token", return_value="test"):
            self.assertIsNone(delivery.public_tiktok_posts(self.db, "upload-id"))
            self.assertIsNone(delivery.public_tiktok_posts(self.db, "upload-id"))
            self.assertEqual(delivery.public_tiktok_posts(self.db, "upload-id")[0][0], video["share_url"])
            self.assertEqual(api.post.call_args.kwargs["json"]["filters"]["video_ids"], ["123"])
