import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import cloud_archive
import main
import monitoring


class MonitoringTests(unittest.TestCase):
    def test_alerts_route_confirmed_posts_only(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://example.invalid/hook",
                                     "TELEGRAM_BOT_TOKEN": "example", "TELEGRAM_CHAT_ID": "123"}, clear=True), \
                patch.object(monitoring, "urlopen") as send:
            send.return_value.__enter__.side_effect = lambda: io.BytesIO(b'{"ok":true}')
            for receipt in ("processing:1", "SEND_TO_USER_INBOX:2", "github-artifact:3"):
                self.assertFalse(monitoring.notify_post("tiktok", receipt))
            send.assert_not_called()
            self.assertTrue(monitoring.notify_post("youtube", "abc"))
            self.assertTrue(monitoring.notify_post("tiktok", "PUBLISH_COMPLETE:456"))
            self.assertEqual(send.call_count, 4)
            body = json.loads(send.call_args_list[0].args[0].data)
            self.assertIn("https://www.youtube.com/shorts/abc", body["content"])
            self.assertEqual(body["allowed_mentions"], {"parse": []})

    def test_failure_trace_does_not_include_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RUNNER_TEMP": tmp}):
            try:
                raise ValueError("https://example.invalid/?secret=private")
            except ValueError as exc:
                trace = monitoring.error_trace(exc, "R2")
            stored = (Path(tmp) / "clips-error-trace.txt").read_text()
            self.assertIn("test_cloud.py:", trace)
            self.assertIn("R2: ValueError", stored)
            self.assertNotIn("private", stored)

    def test_dry_run_collects_all_failures_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "twitch_clips", return_value=({main.V:"1"}, {})), \
                patch("kick.clip_page"), patch.dict(os.environ, {}, clear=True), patch.object(main, "store") as db, \
                patch.object(main.subprocess, "run", side_effect=OSError), patch.dict("sys.modules", {"faster_whisper": None}), \
                patch.object(cloud_archive, "check_upload", side_effect=ValueError("Missing R2_BUCKET")) as upload, \
                patch.object(main, "publish") as publish, redirect_stdout(io.StringIO()) as log:
            db.return_value.ping.return_value = True
            with self.assertRaisesRegex(RuntimeError, "Health checks failed"):
                main.dry_run(Path(tmp))
            self.assertEqual(log.getvalue().count("PASS  ") + log.getvalue().count("FAIL  "), 6)
            self.assertIn("FAIL  R2", log.getvalue())
            upload.assert_called_once()
            publish.assert_not_called()


try:
    from moto import mock_aws
except ImportError:
    mock_aws = None


@unittest.skipUnless(mock_aws, "needs the S3 emulator used in Actions verify")
class ArchiveTests(unittest.TestCase):
    def test_boto_upload_manifest_presigned_read_and_probe_cleanup(self):
        import boto3
        import requests
        from botocore.config import Config
        with mock_aws(), tempfile.TemporaryDirectory() as tmp:
            client = boto3.client("s3", region_name="us-east-1", config=Config(signature_version="s3v4"))
            bucket = "clips-test-bucket"
            client.create_bucket(Bucket=bucket)
            root = Path(tmp)
            files = ("youtube.mp4", "tiktok.mp4", "gta5-freeway.mp4")
            for name in files + ("part0.mp4",):
                (root / name).write_bytes(name.encode())
            with patch.object(cloud_archive, "storage", return_value=(client, bucket)):
                cloud_archive.archive(root)
                cloud_archive.archive(root)
                cloud_archive.check_upload(root / files[0])
            keys = [r["Key"] for r in client.list_objects_v2(Bucket=bucket)["Contents"]]
            self.assertEqual(len(keys), 4)
            manifest = next(k for k in keys if k.startswith("manifests/"))
            records = json.load(client.get_object(Bucket=bucket, Key=manifest)["Body"])
            self.assertEqual(set(records), set(files))
            for name, item in records.items():
                self.assertIn("X-Amz-Signature=", item["video_url"])
                self.assertEqual(requests.get(item["video_url"], timeout=5).content, name.encode())

    def test_incomplete_batch_cannot_write_a_success_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "youtube.mp4").write_bytes(b"short")
            (root / "tiktok.mp4").write_bytes(b"compilation")
            client = Mock()
            with patch.object(cloud_archive, "storage", return_value=(client, "bucket")), \
                    patch.object(cloud_archive, "upload_video", side_effect=[{}, RuntimeError("write failed")]):
                with self.assertRaises(RuntimeError):
                    cloud_archive.archive(root)
            client.put_object.assert_not_called()
            self.assertTrue((root / "youtube.mp4").is_file())
