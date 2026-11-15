"""Archive an exact reviewed preview on the cloud runner, without publishing."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud_archive import storage, upload_video
from scripts.review_preview import verified_media


def archive_review(root, selection, expected_digest):
    if not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise ValueError("Expected a SHA-256 digest from the completed QA run")
    rows = json.loads((root / "previews.json").read_text())
    matches = [row for row in rows if row.get("sha256") == expected_digest]
    if len(matches) != 1:
        raise ValueError("Expected exactly one preview matching the reviewed digest")
    media = verified_media(root, matches[0], selection)
    client, bucket = storage()
    key = f"reviews/{expected_digest}/preview.mp4"
    record = upload_video(client, bucket, media, key, expected_digest)
    # Verify the entire stored body, not just user-supplied object metadata.
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    digest = hashlib.sha256()
    try:
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            digest.update(chunk)
    finally:
        body.close()
    if digest.hexdigest() != expected_digest:
        raise RuntimeError("Archived video differs from the reviewed file")
    import requests
    with requests.get(record["video_url"], stream=True, timeout=(5, 30)) as response:
        response.raise_for_status()
        signed_digest = hashlib.sha256()
        for chunk in response.iter_content(1024 * 1024):
            signed_digest.update(chunk)
        if signed_digest.hexdigest() != expected_digest:
            raise RuntimeError("Presigned video download differs from the reviewed file")
    record.update(source_id=selection["source_id"], render_run=os.environ["RENDER_RUN"],
                  approval_status="awaiting_editorial_and_brand_approval")
    manifest = f"manifests/{os.environ['GITHUB_RUN_ID']}/{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}.json"
    client.put_object(Bucket=bucket, Key=manifest, Body=json.dumps(record).encode(),
                      ContentType="application/json", CacheControl="private, no-store")
    # The signed URL stays private; no social credentials or publishing calls here.
    print("PASS: R2 upload, full SHA-256 readback and presigned GET")
    print(json.dumps({k: record[k] for k in ("key", "bytes", "sha256", "source_id", "render_run")}))
    print("Private download manifest: " + manifest)


if __name__ == "__main__":
    archive_review(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), sys.argv[3])
