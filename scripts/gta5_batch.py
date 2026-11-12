"""One manually dispatched, deduplicated set of five music-backed GTA V Shorts."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import random
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud_archive import file_digest, storage, upload_video
from main import daily_cap, day_key, LEDGER, reserve, store
from soundtrack import TRACKS, music_mix
from render import probe, render_vertical_short, seconds

ITEM = "https://archive.org/details/ut-gtav-b-roll"
SOURCE = "https://archive.org/download/ut-gtav-b-roll/"
CREDIT = "Unlisted Thoughts"
# Number, start, original recording SHA-1 (archive metadata), title, hook, on-screen commentary.
EDITS = [
    (2, 16, "5f42a8eae20decd7befee814333f7f53932de731", "Someone Brought a Boat to the GTA V Freeway Ramp", "Who Brought the Boat?",
     ('Start at the hitch', 'The boat follows the pickup', 'Watch the back wheels')),
    (3, 18, "3991f83900c9a3312439935e3c37a8229bc1feac", "The Strangest Spectators at a GTA V Stunt", "Watch the Sideline Instead",
     ('Look past the cars', 'Spot the roadside crowd', 'Would you stand there?')),
    (4, 16, "1015b94849b44faad4a0e5e7f01c31d12c9b5385", "Watch the Trailer, Not the Cab | GTA V", "Watch the Trailer Swing",
     ('Follow the cab', 'Watch the trailer swing', 'Count the lanes it spans')),
    (5, 17, "4ee1ec68f7ba77d49461a69ec1ea37736f8bc4d7", "Spot the Safe Landing in This GTA V Scrapyard", "Pick Your Landing Spot",
     ('Pick a landing spot', 'Look for the metal beams', 'Try the open dirt')),
    (6, 16, "1083adc5c4d962159563f0fed4b1aa09e1d4bf9c", "Three Levels of Los Santos in One Shot | GTA V", "Count the Three Levels",
     ('Start on the freeway', 'Drop to the freight cars', 'Find the concrete channel')),
]


# Each caption identifies the footage as Los Santos and invites a specific GTA VI comparison.
PROMPTS = {
    2: "A speedboat hits a freeway ramp in Los Santos. What would you tow through #ViceCity in #GTA6?",
    3: "Watch the spectators on this GTA V freeway. How would you want crowds in #GTA6 to react to a #ViceCity stunt?",
    4: "Follow the trailer as it swings across the lanes in GTA V. What trailer stunt would you try in #ViceCity in #GTA6?",
    5: "Pick a landing spot in this Los Santos scrapyard. Would your first #GTA6 stunt in #ViceCity be a rooftop jump or a boat launch?",
    6: "One Los Santos shot lines up a freeway, a rail yard and a river. Which part of #ViceCity would you explore first in #GTA6?",
}


def run(*args, cwd=None):
    subprocess.run(list(map(str, args)), check=True, cwd=cwd)


def token(i):
    return f"cc0:ut-gtav-b-roll:B_ROLL_{i}"


def render_all(root):
    from tempfile import TemporaryDirectory
    import requests
    root.mkdir(parents=True, exist_ok=True)
    meta = requests.get("https://archive.org/metadata/ut-gtav-b-roll", timeout=30)
    meta.raise_for_status()
    if meta.json()["metadata"]["licenseurl"].replace("http:", "https:") != "https://creativecommons.org/publicdomain/zero/1.0/":
        raise RuntimeError("Source recording license changed")
    manifest, credits = {}, {}
    tracks = random.sample(TRACKS, len(EDITS))
    for (i, start, checksum, title, hook, captions), track in zip(EDITS, tracks):
        with TemporaryDirectory(dir=root.parent) as temp:
            d = Path(temp)
            raw = d / "source.mp4"
            run("curl", "-fsSL", "--retry", "3", "--max-time", "240", SOURCE + f"B_ROLL_{i}.mp4", "-o", raw)
            with raw.open("rb") as stream:
                if hashlib.file_digest(stream, "sha1").hexdigest() != checksum:
                    raise ValueError("Source checksum mismatch")
            duration = 21
            notes = [{"start": j*7, "end": (j+1)*7, "text": line} for j, line in enumerate(captions)]
            dest = d / f"gta5-{i}.mp4"
            render_vertical_short(raw, dest, duration, [], title, CREDIT, notes=notes, start=start, hook=hook, gap="")
            credits[dest.name] = music_mix(dest, track)
            info = probe(dest)
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            a = next(s for s in info["streams"] if s["codec_type"] == "audio")
            if (v["width"], v["height"], a["channels"]) != (1080,1920,2) or not 18 <= seconds(dest) < 44:
                raise ValueError("Invalid rendered Short")
            run("ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", dest, "-f", "null", "-")
            dest.replace(root / dest.name)
            manifest[dest.name] = file_digest(root/dest.name)
            print(f"PASS: {title} | {duration:.1f}s | {credits[dest.name]}", flush=True)
    (root/"music.json").write_text(json.dumps(credits, indent=2))
    (root/"manifest.json").write_text(json.dumps(manifest, indent=2))


# This API receipt explicitly rejected the 5th upload. Other pending uploads are ambiguous.
REJECTED_RESERVATION = "pending:43275035694"
FINAL_REMIX = token(6) + ":music-v1"
RETRY_START = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
ARCHIVE_EXPIRY = datetime(2026, 11, 19, 17, 55, tzinfo=timezone.utc)


def retry_due(record, now):
    if not record or not RETRY_START <= now < ARCHIVE_EXPIRY:
        return False
    if record == REJECTED_RESERVATION:
        return True
    if record.startswith("upload-limit:"):
        return now.timestamp() >= int(record.split(":")[1])
    return False


def publish_all(root, backup):
    import delivery
    from monitoring import notify_post
    manifest = json.loads((root/"manifest.json").read_text())
    paths = [root/f"gta5-{e[0]}.mp4" for e in EDITS]
    if set(manifest) != {p.name for p in paths} or any(file_digest(p) != manifest[p.name] for p in paths):
        raise ValueError("Artifact does not contain the five verified renders")
    music = json.loads((root/"music.json").read_text()) if (root/"music.json").exists() else {}
    if backup == "r2":
        client, bucket = storage()
        for path in paths:
            sha = manifest[path.name]
            upload_video(client, bucket, path, f"videos/{sha}/{path.name}", sha)
    elif backup != "verified-artifact":
        raise ValueError("Unknown backup choice")
    db = store()
    run_id = os.environ["GITHUB_RUN_ID"]
    for edit, path in zip(EDITS, paths):
        i, _, _, title, _, _ = edit
        key = token(i) + (":music-v1" if path.name in music else "")
        existing = db.hget(LEDGER, key)
        if key == FINAL_REMIX and retry_due(existing, datetime.now(timezone.utc)):
            # Only release an identified rejection, and only if it is still the same record.
            cleared = db.eval("if redis.call('HGET',KEYS[1],ARGV[1]) == ARGV[2] then "
                              "return redis.call('HDEL',KEYS[1],ARGV[1]) end return 0", 1, LEDGER, key, existing)
            if not cleared:
                raise RuntimeError("Upload reservation changed")
            existing = None
        if existing:
            if existing.startswith("{") and json.loads(existing).get("youtube"):
                print("Already uploaded:", json.loads(existing)["youtube"], flush=True)
                continue
            raise RuntimeError(f"Existing unresolved upload for {key}; check Studio before retrying.")
        if not reserve(db, [key], run_id):
            raise RuntimeError("Daily cap reached; remaining Shorts are still in the artifact")
        clip = {"title": title, "broadcaster_name": CREDIT + " (CC0 recording). Commentary and edit: Daily Getaway Clips.", "url": ITEM}
        if path.name in music:
            clip.update(title=title + " #GTA5", music_credit=music[path.name], description_intro=PROMPTS[i],
                        campaign={"extra_tags": ["LosSantos", "GTA6", "ViceCity"]})
        from googleapiclient.errors import HttpError
        try:
            receipt = delivery.youtube(path, clip, "Grand Theft Auto V", with_receipt=True)
        except HttpError as error:
            reasons = [row.get("reason") for row in (error.error_details or []) if isinstance(row, dict)]
            if key == FINAL_REMIX and error.resp.status == 400 and "uploadLimitExceeded" in reasons:
                next_attempt = int(datetime.now(timezone.utc).timestamp()) + 86400
                db.hset(LEDGER, key, f"upload-limit:{next_attempt}")
            raise
        ident = receipt["id"]
        visibility = receipt["status"]["privacyStatus"]
        channel = receipt["snippet"]["channelId"]
        record = {"run": run_id, "youtube": ident, "visibility": visibility, "channel": channel}
        db.hset(LEDGER, key, json.dumps(record))
        print(f"{title} | https://www.youtube.com/shorts/{ident} | {visibility} | {channel}", flush=True)
        if channel != os.environ["YOUTUBE_CHANNEL_ID"] or visibility != "public":
            raise RuntimeError("Unexpected destination or visibility; inspect before further uploads")
        notify_post("youtube", ident)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "publish", "capacity", "check-retry"])
    parser.add_argument("root", type=Path)
    parser.add_argument("--backup", choices=["r2", "verified-artifact"], default="r2")
    args = parser.parse_args()
    if args.mode == "check-retry":
        record = store().hget(LEDGER, FINAL_REMIX)
        due = retry_due(record, datetime.now(timezone.utc))
        print("Final music repost:", "retry due" if due else
              "waiting for the upload window" if record == REJECTED_RESERVATION or (record or "").startswith("upload-limit:") else "no retry due")
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            print("due=" + str(due).lower(), file=out)
    elif args.mode == "prepare":
        render_all(args.root.resolve())
    elif args.mode == "capacity":
        db = store()
        print("Available UTC daily slots:", daily_cap() - int(db.get(day_key()) or 0))
    else:
        publish_all(args.root.resolve(), args.backup)
