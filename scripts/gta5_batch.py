"""One manually dispatched, deduplicated set of five narrated GTA V Shorts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud_archive import file_digest, storage, upload_video
from main import daily_cap, day_key, LEDGER, reserve, store
from render import probe, render_vertical_short, seconds

ITEM = "https://archive.org/details/ut-gtav-b-roll"
SOURCE = "https://archive.org/download/ut-gtav-b-roll/"
CREDIT = "Unlisted Thoughts"
# Number, start, original recording SHA-1 (archive metadata), title, hook, voiceover.
EDITS = [
    (2, 16, "5f42a8eae20decd7befee814333f7f53932de731", "Someone Brought a Boat to the GTA V Freeway Ramp", "Who Brought the Boat?",
     "Look at what the pickup is towing. Someone brought a speedboat to a freeway jump. The truck gets to pick its line, but the boat is stuck following that little hitch. Forget watching the front bumper. The interesting part of this stunt is the last thing to reach the ramp."),
    (3, 18, "3991f83900c9a3312439935e3c37a8229bc1feac", "The Strangest Spectators at a GTA V Stunt", "Watch the Sideline Instead",
     "Ignore the ramp for a second. Look along the dirt shoulder. There are people standing in a row, vehicles parked behind them, and watchtowers in the distance. From this angle the freeway looks like a grandstand. Now look back at the traffic. Would you stand that close?"),
    (4, 16, "1015b94849b44faad4a0e5e7f01c31d12c9b5385", "Watch the Trailer, Not the Cab | GTA V", "Watch the Trailer Swing",
     "Here's the part I'd replay: the angle between the cab and its trailer. The cab only takes up one lane, but turn that trailer sideways and it stretches across the road. Watch the white lane markings underneath it. They're a better ruler than the other cars."),
    (5, 17, "4ee1ec68f7ba77d49461a69ec1ea37736f8bc4d7", "Spot the Safe Landing in This GTA V Scrapyard", "Pick Your Landing Spot",
     "Imagine you have to land in this scrapyard. Pick a spot before you look any closer. That empty patch by the roof? There's a row of metal beams beside it. The open dirt in the middle looks better. This is why I like the overhead shot: you can play it like a puzzle."),
    (6, 16, "1083adc5c4d962159563f0fed4b1aa09e1d4bf9c", "Three Levels of Los Santos in One Shot | GTA V", "Count the Three Levels",
     "How many levels can you find in this one shot? Start with the road on the left. Drop down to the freight cars under the yellow crane. Then look past the tracks, toward the water in the concrete channel. A freeway, a rail yard, and a river, all in the same frame."),
]


def run(*args, cwd=None):
    subprocess.run(list(map(str, args)), check=True, cwd=cwd)


def token(i):
    return f"cc0:ut-gtav-b-roll:B_ROLL_{i}"


def render_all(root):
    from faster_whisper import WhisperModel
    from tempfile import TemporaryDirectory
    import requests
    root.mkdir(parents=True, exist_ok=True)
    meta = requests.get("https://archive.org/metadata/ut-gtav-b-roll", timeout=30)
    meta.raise_for_status()
    if meta.json()["metadata"]["licenseurl"].replace("http:", "https:") != "https://creativecommons.org/publicdomain/zero/1.0/":
        raise RuntimeError("Source recording license changed")
    model = WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=2)
    manifest = {}
    for i, start, checksum, title, hook, script in EDITS:
        with TemporaryDirectory(dir=root.parent) as temp:
            d = Path(temp)
            raw = d / "source.mp4"
            run("curl", "-fsSL", "--retry", "3", "--max-time", "240", SOURCE + f"B_ROLL_{i}.mp4", "-o", raw)
            with raw.open("rb") as stream:
                if hashlib.file_digest(stream, "sha1").hexdigest() != checksum:
                    raise ValueError("Source checksum mismatch")
            (d/"words.txt").write_text(script)
            # Only this authored narration is mapped into the Short. No source soundtrack.
            run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "flite=textfile=words.txt:voice=slt", "voice.wav", cwd=d)
            duration = max(18.25, seconds(d/"voice.wav") + 0.45)
            if duration >= 43.8:
                raise ValueError("Narration too long")
            segments, _ = model.transcribe(str(d/"voice.wav"), language="en", word_timestamps=True, beam_size=3)
            words = [(w.start, w.end, w.word.strip()) for s in segments for w in s.words if w.end > w.start]
            if len(words) < max(4, len(script.split()) * .7) or max(b[0]-a[1] for a,b in zip(words,words[1:])) > 4:
                raise ValueError("Incomplete spoken commentary")
            run("ffmpeg", "-v", "error", "-ss", start, "-i", raw, "-i", d/"voice.wav", "-map", "0:v:0", "-map", "1:a:0",
                "-t", f"{duration:.3f}", "-af", "apad", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-c:a", "aac", d/"narrated.mp4")
            dest = d / f"gta5-{i}.mp4"
            render_vertical_short(d/"narrated.mp4", dest, duration, words, title, CREDIT, hook=hook)
            info = probe(dest)
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            a = next(s for s in info["streams"] if s["codec_type"] == "audio")
            if (v["width"], v["height"], a["channels"]) != (1080,1920,2) or not 18 <= seconds(dest) < 44:
                raise ValueError("Invalid rendered Short")
            run("ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", dest, "-f", "null", "-")
            dest.replace(root / dest.name)
            manifest[dest.name] = file_digest(root/dest.name)
            print(f"PASS: {title} | {duration:.1f}s | {len(words)} timed spoken words", flush=True)
    (root/"manifest.json").write_text(json.dumps(manifest, indent=2))


def publish_all(root, backup):
    import delivery
    from monitoring import notify_post
    manifest = json.loads((root/"manifest.json").read_text())
    paths = [root/f"gta5-{e[0]}.mp4" for e in EDITS]
    if set(manifest) != {p.name for p in paths} or any(file_digest(p) != manifest[p.name] for p in paths):
        raise ValueError("Artifact does not contain the five verified renders")
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
        key = token(i)
        existing = db.hget(LEDGER, key)
        if existing:
            if existing.startswith("{") and json.loads(existing).get("youtube"):
                print("Already uploaded:", json.loads(existing)["youtube"], flush=True)
                continue
            raise RuntimeError(f"Existing unresolved upload for {key}; check Studio before retrying.")
        if not reserve(db, [key], run_id):
            raise RuntimeError("Daily cap reached; remaining Shorts are still in the artifact")
        clip = {"title": title, "broadcaster_name": CREDIT + " (CC0 recording). Commentary and edit: Daily Getaway Clips.", "url": ITEM}
        receipt = delivery.youtube(path, clip, "Grand Theft Auto V", with_receipt=True)
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
    parser.add_argument("mode", choices=["prepare", "publish", "capacity"])
    parser.add_argument("root", type=Path)
    parser.add_argument("--backup", choices=["r2", "verified-artifact"], default="r2")
    args = parser.parse_args()
    if args.mode == "prepare":
        render_all(args.root.resolve())
    elif args.mode == "capacity":
        db = store()
        print("Available UTC daily slots:", daily_cap() - int(db.get(day_key()) or 0))
    else:
        publish_all(args.root.resolve(), args.backup)
