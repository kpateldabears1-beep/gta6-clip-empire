"""Exercise discovery and real media intake on ephemeral cloud disk."""
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kick import fetch_kick_clips
from main import V, VI, download_clip, ranked, twitch_clips
from render import probe


def playback(url, page):
    with TemporaryDirectory() as work:
        path = download_clip(url, Path(work), "clip")
        if not path:
            raise RuntimeError("No clip file received")
        data = probe(path)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], check=True, timeout=90)
        print(f"PASS playback {page} | {float(data['format']['duration']):.1f}s | "
              f"{video['width']}x{video['height']} {video['codec_name']} + {audio['codec_name']}", flush=True)


def main():
    now = datetime.now(timezone.utc)
    config = json.loads(Path("streamers.json").read_text())
    handles = [row["username"] for row in config["watchlist"] if row.get("username")]
    all_clips = {}
    for handle in handles:
        clips = fetch_kick_clips([handle], now=now)
        print(f"Watchlist {handle}: {len(clips)} recent, {sum(c['game_id'] in (V, VI) for c in clips)} labeled GTA")
        all_clips.update((c["id"], c) for c in clips)
    category = fetch_kick_clips([], now=now, include_gta_categories=True)
    all_clips.update((c["id"], c) for c in category)
    gta = [c for c in all_clips.values() if c["game_id"] in (V, VI)]
    picks = ranked(gta, set(), now)
    print(f"Kick last 3 hours at {now.isoformat()}: {dict(Counter(c['game_id'] for c in gta))}, "
          f"{len(picks)} ranked (list capped at 50).", flush=True)
    failures, tested = [], set()
    for c in picks:
        if len(tested) >= 3:
            break
        if c["broadcaster_id"] in tested:
            continue
        tested.add(c["broadcaster_id"])
        try:
            playback(c["media_url"] or c["url"], c["url"])
        except Exception as exc:
            print(f"FAIL playback {c['url']} ({type(exc).__name__})", flush=True)
            failures.append(c["id"])
    if not tested:
        print("No recent ranked Kick GTA clip available to test.")
        failures.append("Kick sample unavailable")
    twitch_slug = os.getenv("TWITCH_SAMPLE", "")
    if os.getenv("TWITCH_CLIENT_ID") and os.getenv("TWITCH_CLIENT_SECRET"):
        ids = {r["broadcaster_id"]: r for r in config["watchlist"] if r.get("broadcaster_id")}
        _, clips = twitch_clips(ids, config, now)
        print(f"Twitch Helix: {len(clips)} watchlist GTA clips in the last 3 hours")
        if clips:
            twitch_slug = max(clips.values(), key=lambda c: c["view_count"])["id"]
    else:
        print("Twitch Helix: unavailable (app credentials missing)", flush=True)
    if twitch_slug:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", twitch_slug):
            raise ValueError("Invalid Twitch clip ID")
        url = "https://clips.twitch.tv/" + twitch_slug
        playback(url, url)
    if failures:
        raise SystemExit("Failed media checks: " + ", ".join(failures))


if __name__ == "__main__":
    main()
