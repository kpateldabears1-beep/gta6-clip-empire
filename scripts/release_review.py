"""Verify or release an exact R2 draft. Only a recorded brand approval enables release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cloud_archive
import delivery
from main import LEDGER, reserve, store, V
from monitoring import error_trace


def release_digest(plan):
    # Approval covers the source, exact bytes, destination and complete post metadata.
    payload = {k: plan[k] for k in ("source_id", "clip_id", "sha256", "bytes",
                                   "channel_id", "campaign_url", "youtube")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def validate(plan, publishing=False):
    if not re.fullmatch(r"[a-f0-9]{64}", plan["sha256"]):
        raise ValueError("Invalid reviewed media digest")
    if type(plan["bytes"]) is not int or not 0 < plan["bytes"] <= 256 * 1024**2:
        raise ValueError("Invalid reviewed media size")
    if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", plan["channel_id"]):
        raise ValueError("Invalid destination channel")
    sources = json.loads(Path(__file__).resolve().parents[1].joinpath("review_sources.json").read_text())
    source = sources[plan["source_id"]]
    if (source["url"].rstrip("/").rsplit("/", 1)[-1] != plan["clip_id"]
            or source["permission_url"] != plan["campaign_url"]):
        raise ValueError("Release does not match the reviewed campaign source")
    delivery.youtube_metadata({}, V, plan["youtube"])
    if publishing:
        approval = plan.get("approval", {})
        evidence = urlsplit(approval.get("evidence_url") or "")
        if (approval.get("status") != "approved" or approval.get("full_playback_reviewed") is not True
                or evidence.scheme != "https" or not evidence.netloc
                or approval.get("approved_release_sha256") != release_digest(plan)):
            raise ValueError("Release blocked: exact draft needs full playback review and recorded brand approval")


def download_verified(plan, root, client, bucket):
    key = f"reviews/{plan['sha256']}/preview.mp4"
    head = client.head_object(Bucket=bucket, Key=key)
    if (head["ContentLength"] != plan["bytes"] or head.get("Metadata", {}).get("sha256") != plan["sha256"]
            or head.get("ContentType") != "video/mp4"):
        raise ValueError("Durable R2 backup does not match the release plan")
    media = root / "approved.mp4"
    client.download_file(bucket, key, str(media))
    if media.stat().st_size != plan["bytes"] or cloud_archive.file_digest(media) != plan["sha256"]:
        raise ValueError("Downloaded bytes differ from the exact reviewed video")
    return media


def run(plan, root, publishing=False):
    validate(plan, publishing)
    if os.getenv("GITHUB_ACTIONS") != "true":
        raise ValueError("Media retrieval and release must run on the cloud runner")
    if os.environ["YOUTUBE_CHANNEL_ID"] != plan["channel_id"]:
        raise ValueError("Configured destination differs from the reviewed channel")
    db = store()
    prior = db.hget(LEDGER, plan["clip_id"])
    if prior:
        raise ValueError("Source already reserved or delivered; inspect the receipt before retrying")
    client, bucket = cloud_archive.storage()
    media = download_verified(plan, root, client, bucket)
    print("PASS: exact durable backup retrieved and full SHA-256 verified")
    print("PASS: source has no prior Redis reservation")
    print("Release identity: " + release_digest(plan))
    if not publishing:
        print("VERIFY ONLY: no reservation or upload. Approval status: " + plan["approval"]["status"])
        return
    for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        cloud_archive.required(name)
    run_id = os.environ["GITHUB_RUN_ID"]
    if not reserve(db, [plan["clip_id"]], run_id):
        raise ValueError("Daily cap reached; no upload attempted")
    # A failed/ambiguous upload keeps its reservation. Never blindly retry.
    receipt = delivery.youtube(media, {}, V, with_receipt=True, approved_metadata=plan["youtube"])
    record = {"run": run_id, "youtube": receipt["id"], "receipt": receipt,
              "sha256": plan["sha256"], "release_sha256": release_digest(plan)}
    db.hset(LEDGER, plan["clip_id"], json.dumps(record))
    # Persist the receipt before interpreting visibility or calling another service.
    client.put_object(Bucket=bucket, Key=f"releases/{run_id}/youtube-receipt.json",
                      Body=json.dumps(record).encode(), ContentType="application/json")
    if receipt["snippet"].get("channelId") != plan["channel_id"]:
        raise RuntimeError("Upload receipt has an unexpected destination; inspect it, do not retry")
    if not delivery.public_youtube_post(receipt):
        raise RuntimeError("Upload recorded, but public publication is unconfirmed; do not re-upload")
    url = "https://www.youtube.com/shorts/" + receipt["id"]
    print("CONFIRMED PUBLIC: " + url)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(f"Published exact approved draft: {url}\n\nSubmit this URL to the campaign dashboard.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    plan = json.loads(Path("reviews/releases/lysium-wheel.json").read_text())
    try:
        with tempfile.TemporaryDirectory(prefix="gta-release-") as temp:
            run(plan, Path(temp), args.publish)
    except Exception as exc:
        print(error_trace(exc), file=sys.stderr)
        sys.exit(1)
