"""Read public metadata from the same channel clip feed used by Kick's website."""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def clip_page(username, params):
    url = f"https://kick.com/api/v2/channels/{username}/clips?{urlencode(params)}"
    response = subprocess.run(["curl", "--silent", "--show-error", "--fail", "--max-time", "15",
                               "--header", "Accept: application/json", url],
                              capture_output=True, check=True)
    page = json.loads(response.stdout)
    if not isinstance(page, dict) or not isinstance(page.get("clips"), list):
        raise ValueError("Unexpected Kick clips response")
    return page


def kick_media_url(value, slug):
    # Keep a creator-facing page URL for credit and use Kick's own HLS/MP4 for download.
    if isinstance(value, str) and re.fullmatch(
            rf"https://clips\.kick\.com/clips/[a-zA-Z0-9_-]+/{re.escape(slug)}/[a-zA-Z0-9_.-]+\.(?:m3u8|mp4)", value):
        return value
    return None


def fetch_kick_clips(usernames=None, *, now=None):
    """Return distinct public clips from the past three hours, fastest-growing first."""
    if usernames is None:
        config = json.loads(Path(__file__).with_name("streamers.json").read_text())
        usernames = ([creator["username"] for creator in config["watchlist"] if creator.get("username")]
                     if "watchlist" in config else config.get("kick_watchlist", []))
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=3)
    found = {}
    failures = []
    if isinstance(usernames, str):
        usernames = [usernames]
    usernames = list(usernames)
    if any(not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_-]+", name) for name in usernames):
        raise ValueError("Invalid Kick channel slug")
    usernames = list(dict.fromkeys(usernames))
    for username in usernames:
        params = {"sort": "date", "time": "day"}
        cursors = set()
        try:
            while True:
                page = clip_page(username, params)
                reached_cutoff = False
                for row in page["clips"]:
                    if not isinstance(row, dict):
                        continue
                    created = timestamp(row.get("created_at"))
                    if created is None or created > now:
                        continue
                    if created < cutoff:
                        reached_cutoff = True
                        continue
                    channel = row.get("channel")
                    category = row.get("category")
                    slug, title = row.get("id"), row.get("title")
                    if (not isinstance(channel, dict) or channel.get("slug") != username
                            or row.get("privacy", "public") != "public"
                            or not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", slug)
                            or not isinstance(title, str) or not title.strip()):
                        continue
                    try:
                        views = int(row.get("views", row.get("view_count")))
                        duration = float(row.get("duration"))
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if views < 0 or not math.isfinite(duration) or duration <= 0:
                        continue
                    minutes = (now - created).total_seconds() / 60
                    game = category.get("name") if isinstance(category, dict) else None
                    clip_id = "kick:" + slug
                    found[clip_id] = {
                        "id": clip_id, "platform": "kick", "title": title.strip(),
                        "url": f"https://kick.com/{username}/clips/{slug}",
                        "media_url": kick_media_url(row.get("video_url") or row.get("clip_url"), slug),
                        "broadcaster_id": "kick:" + username,
                        "broadcaster_name": channel.get("username") or username,
                        "game_id": game if isinstance(game, str) else None,
                        "view_count": views, "created_at": created.isoformat(), "duration": duration,
                        "velocity": views / (minutes or 1 / 60), "campaign": {},
                    }
                cursor = page.get("nextCursor")
                if reached_cutoff or not page["clips"] or not isinstance(cursor, str) or not cursor or cursor in cursors:
                    break
                cursors.add(cursor)
                params["cursor"] = cursor
        except (subprocess.CalledProcessError, ValueError) as error:
            failures.append(username)
            detail = error.stderr.decode(errors="replace").strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
            print(f"Kick feed unavailable for {username}: {detail}", file=sys.stderr)
    if failures and len(failures) == len(usernames) and not found:
        raise RuntimeError("All requested Kick feeds were unavailable")
    return sorted(found.values(), key=lambda c: (-c["velocity"], -c["view_count"], c["id"]))
