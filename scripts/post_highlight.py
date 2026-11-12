"""Publish the reviewed GTA V highlight from a verified Actions artifact."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import delivery
from main import LEDGER, reserve, store


KEY = "cc0:ut-gtav-b-roll:wrong-exit:music-v1"


def main(root):
    video = root / "wrong-exit-gta5.mp4"
    if not video.is_file() or not video.stat().st_size:
        raise ValueError("The reviewed GTA highlight is missing")
    db = store()
    existing = db.hget(LEDGER, KEY)
    if existing:
        try:
            record = json.loads(existing)
        except (TypeError, ValueError):
            record = {}
        if record.get("youtube"):
            print("Already published: https://www.youtube.com/shorts/" + record["youtube"])
            return
        raise RuntimeError("This highlight has an unresolved delivery reservation")
    if not reserve(db, [KEY], os.environ["GITHUB_RUN_ID"]):
        raise RuntimeError("Daily delivery cap reached")
    clip = {
        "title": "Wrong Exit in GTA V #GTA5",
        "broadcaster_name": "Unlisted Thoughts (CC0 footage). Edit by Daily Getaway Clips.",
        "url": "https://archive.org/details/ut-gtav-b-roll",
        "description_intro": "A freeway exit turns into a rail-yard launch in GTA V. Which #GTA6 #ViceCity stunt would you try first?",
        "music_credit": (root / "credits.txt").read_text().split("Music: ", 1)[-1].strip(),
        "campaign": {"extra_tags": ["GTA5", "GTAV", "LosSantos", "GTA6", "ViceCity"]},
    }
    receipt = delivery.youtube(video, clip, "Grand Theft Auto V", with_receipt=True)
    if receipt["status"].get("privacyStatus") != "public":
        raise RuntimeError("YouTube did not return public visibility")
    db.hset(LEDGER, KEY, json.dumps({"run": os.environ["GITHUB_RUN_ID"], "youtube": receipt["id"],
                                     "visibility": "public", "channel": receipt["snippet"]["channelId"]}))
    print("YouTube Short: https://www.youtube.com/shorts/" + receipt["id"])


if __name__ == "__main__":
    import sys
    main(Path(sys.argv[1]).resolve())
