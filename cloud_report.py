"""Track public channel performance and discover GTA candidates without fetching media."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.request import urlopen
from xml.etree import ElementTree

from kick import fetch_kick_clips
from main import V, VI, ranked, store
from monitoring import error_trace


def feed_counts(feed, channel):
    root = ElementTree.parse(feed).getroot()
    if root.findtext("{*}channelId") not in (channel, channel.removeprefix("UC")):
        raise ValueError("YouTube feed did not identify the configured channel")
    counts = {}
    for entry in root.findall("{*}entry"):
        video = entry.findtext("{*}videoId", "")
        stats = entry.find("{*}group/{*}community/{*}statistics")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video) or stats is None:
            raise ValueError("YouTube did not supply the public video or its view count")
        counts[video] = int(stats.attrib["views"])
    return counts


def view_report(db, channel, now):
    if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel):
        raise ValueError("Set YOUTUBE_CHANNEL_ID to the destination channel ID")
    with urlopen("https://www.youtube.com/feeds/videos.xml?channel_id=" + channel, timeout=25) as feed:
        counts = feed_counts(feed, channel)
    base = "gta-clips:performance:" + channel
    previous = json.loads(db.get(base + ":latest") or "{}")
    snapshot = json.dumps({"at": now.isoformat(), "views": counts})
    with db.pipeline(transaction=True) as pipe:
        pipe.set(base + ":latest", snapshot, ex=35*86400)
        pipe.set(base + ":" + now.strftime("%Y-%m-%d"), snapshot, ex=35*86400)
        pipe.execute()
    lines = ["### Recent YouTube uploads", f"Recent public uploads: {len(counts)} · {sum(counts.values()):,} displayed views"]
    last = previous.get("views", {})
    if previous:
        lines.append("Previous observation: " + previous["at"])
    # Compare only videos present in both snapshots. A first observation establishes a baseline.
    def gain(video):
        return counts[video] - last[video] if video in last else None
    ordered = sorted(counts, key=lambda vid: (vid in last, gain(vid) or 0, counts[vid]), reverse=True)
    for video in ordered[:5]:
        delta = gain(video)
        change = "first observation" if delta is None else f"{delta:+,} since prior check"
        lines.append(f"- [Watch on YouTube](https://www.youtube.com/watch?v={video}) · {counts[video]:,} views · {change}")
    return lines


def candidate_report(now):
    clips = fetch_kick_clips(now=now, include_gta_categories=True)
    picks = ranked([c for c in clips if c.get("game_id") in (V, VI)], set(), now)
    lines = ["### Public Kick discovery",
             f"{len(clips)} distinct recent clips across the watchlist and GTA category feeds · {len(picks)} ranked GTA candidates (up to 50)"]
    for clip in picks[:5]:
        # Titles are external input. Keep the public summary limited to normalized IDs and numbers.
        lines.append(f"- [{clip['broadcaster_id']}]({clip['url']}) · {clip['velocity']:.1f} views/minute · {clip['duration']:g}s")
    return lines


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    failures = []
    for label, collect in (("YouTube performance", lambda: view_report(store(), os.environ["YOUTUBE_CHANNEL_ID"], now)),
                           ("Kick discovery", lambda: candidate_report(now))):
        try:
            lines = collect()
        except Exception as exc:
            failures.append(label)
            lines = [error_trace(exc, label)]
        report = "\n".join(lines)
        print(report, flush=True)
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
            summary.write(report + "\n\n")
    if failures:
        raise SystemExit("Could not complete: " + ", ".join(failures))
