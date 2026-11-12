"""Back up finished MP4 files and keep their temporary download URLs in private R2."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from uuid import uuid4


def required(name):
    value = os.getenv(name)
    if not value:
        raise ValueError("Missing " + name)
    return value


def storage():
    from boto3 import client
    from botocore.config import Config
    from urllib.parse import urlsplit

    endpoint = required("R2_ENDPOINT_URL")
    bucket = required("R2_BUCKET")
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not (parts.hostname or "").endswith(".r2.cloudflarestorage.com"):
        raise ValueError("Expected the HTTPS R2 S3 endpoint in R2_ENDPOINT_URL")
    return client("s3", endpoint_url=endpoint, region_name="auto",
                  aws_access_key_id=required("R2_ACCESS_KEY_ID"),
                  aws_secret_access_key=required("R2_SECRET_ACCESS_KEY"),
                  config=Config(signature_version="s3v4", request_checksum_calculation="when_required",
                                retries={"mode": "standard", "max_attempts": 3})), bucket


def upload_video(client, bucket, path, key, digest):
    client.upload_file(str(path), bucket, key,
                       ExtraArgs={"ContentType": "video/mp4", "Metadata": {"sha256": digest}})
    obj = client.head_object(Bucket=bucket, Key=key)
    if (obj["ContentLength"] != path.stat().st_size or obj.get("Metadata", {}).get("sha256") != digest
            or obj.get("ContentType") != "video/mp4"):
        raise RuntimeError("R2 object verification failed")
    lifetime = 6 * 3600
    url = client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=lifetime)
    return {"key": key, "bytes": obj["ContentLength"], "sha256": digest, "video_url": url,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).isoformat()}


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive(root):
    paths = [root / name for name in ("youtube.mp4", "tiktok.mp4", "gta5-freeway.mp4") if (root / name).is_file()]
    if not paths:
        print("No final videos to archive.")
        return
    client, bucket = storage()
    records = {}
    for path in paths:
        if not path.stat().st_size:
            raise ValueError("Empty rendered video: " + path.name)
        digest = file_digest(path)
        key = f"videos/{digest}/{path.name}"
        records[path.name] = upload_video(client, bucket, path, key, digest)
        print("Archived " + key)
    run = os.getenv("GITHUB_RUN_ID") or root.name
    attempt = os.getenv("GITHUB_RUN_ATTEMPT") or "1"
    manifest = f"manifests/{run}/{attempt}.json"
    client.put_object(Bucket=bucket, Key=manifest, Body=json.dumps(records).encode(),
                      ContentType="application/json", CacheControl="private, no-store")
    print("Private R2 download manifest: " + manifest)


def check_upload(path):
    import requests
    client, bucket = storage()
    key = "health/" + uuid4().hex + ".mp4"
    try:
        record = upload_video(client, bucket, path, key, file_digest(path))
        with requests.get(record["video_url"], stream=True, timeout=(5, 30)) as response:
            response.raise_for_status()
            digest = hashlib.sha256()
            for chunk in response.iter_content(1024 * 1024):
                digest.update(chunk)
            if digest.hexdigest() != record["sha256"]:
                raise RuntimeError("Presigned GET returned different bytes")
    finally:
        client.delete_object(Bucket=bucket, Key=key)
