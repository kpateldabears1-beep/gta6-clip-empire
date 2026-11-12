"""Run via .github/workflows/pipeline.yml; media and model live on the runner."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

from render import analyze_audio, join, probe, render_vertical_short, seconds, curiosity_hook, valid_word
import delivery
from kick import fetch_kick_clips, timestamp, kick_media_url

VI, V = "Grand Theft Auto VI", "Grand Theft Auto V"
LEDGER = "gta-clips:v1"
TARGET = 65


def daily_cap():
    cap = int(os.getenv("DAILY_POST_CAP") or 5)
    if not 1 <= cap <= 25:
        raise ValueError("DAILY_POST_CAP must be between 1 and 25")
    return cap


def day_key():
    return "gta-clips:daily:" + datetime.now(timezone.utc).date().isoformat()


def ranked(clips, used, now):
    scored = []
    generic = {"untitled", "clip", "gta", "gta v", "gta vi", "gta 5", "gta 6", "grand theft auto"}
    for c in clips:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not isinstance(c.get("title"), str):
            continue
        title = " ".join(c["title"].strip().casefold().split())
        created = timestamp(c.get("created_at"))
        try:
            duration, views = float(c.get("duration")), int(c.get("view_count"))
        except (TypeError, ValueError, OverflowError):
            continue
        if (not created or not math.isfinite(duration) or duration < 18 or views < 0
                or c["id"] in used or len(title) < 4 or title in generic):
            continue
        minutes = (now - created).total_seconds() / 60
        if minutes < 0:
            continue
        age = (minutes or 1 / 60) if c.get("platform") == "kick" else max(1, minutes)
        scored.append(dict(c, velocity=views / age, duration=duration, view_count=views))
    return sorted(scored, key=lambda c: (-c["velocity"], -c["view_count"], c["id"]))[:50]


def select(games, clips, used, now=None):
    now = now or datetime.now(timezone.utc)
    vi = ranked([c for c in clips if isinstance(c, dict) and c.get("game_id") in (VI, games.get(VI, VI))], used, now)
    if len(vi) >= 5:
        return VI, vi
    v = ranked([c for c in clips if isinstance(c, dict) and c.get("game_id") in (V, games.get(V, V))], used, now)
    return (V, v) if v else (VI, vi)


def twitch_clips(channels, config, end):
    import requests
    r = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": os.environ["TWITCH_CLIENT_ID"], "client_secret": os.environ["TWITCH_CLIENT_SECRET"],
        "grant_type": "client_credentials"}, timeout=25)
    r.raise_for_status()
    headers = {"Client-Id": os.environ["TWITCH_CLIENT_ID"],
               "Authorization": "Bearer " + r.json()["access_token"]}
    def get(endpoint, **params):
        resp = requests.get("https://api.twitch.tv/helix/" + endpoint, params=params,
                            headers=headers, timeout=25)
        resp.raise_for_status()
        return resp.json()
    game_rows = get("games", name=config["target_game_names"]).get("data")
    games = {g["name"]: g["id"] for g in (game_rows if isinstance(game_rows, list) else [])
             if isinstance(g, dict) and isinstance(g.get("name"), str) and isinstance(g.get("id"), str)}
    clips = {}
    for broadcaster in channels:
        # Query the licensed channels, so smaller streams aren't buried in the global top 100.
        params = dict(broadcaster_id=broadcaster, started_at=(end-timedelta(hours=config["lookback_hours"])).isoformat(),
                      ended_at=end.isoformat(), first=100)
        for _ in range(10):  # Helix limits one query to roughly 1,000 results.
            page = get("clips", **params)
            rows = page.get("data")
            for c in rows if isinstance(rows, list) else ():
                if (isinstance(c, dict) and isinstance(c.get("id"), str)
                        and c.get("broadcaster_id") == broadcaster and c.get("game_id") in games.values()):
                    clips[c["id"]] = dict(c, campaign=channels[broadcaster])
            cursor = page.get("pagination", {}).get("cursor")
            if not cursor:
                break
            params["after"] = cursor
    return games, clips


def discover(db, channels, config):
    now = datetime.now(timezone.utc)
    twitch = {k: v for k, v in channels.items() if not k.startswith("kick:")}
    games, clips = twitch_clips(twitch, config, now) if twitch else ({}, {})
    handles = [k.removeprefix("kick:") for k in channels if k.startswith("kick:")]
    if handles:
        try:
            clips.update((c["id"], c) for c in fetch_kick_clips(handles, now=now))
        except RuntimeError:
            if not twitch:
                raise
            print("Kick feeds unavailable this run; continuing with Twitch.", file=sys.stderr)
    keys = list(clips)
    used = set()
    for i in range(0, len(keys), 200):
        group = keys[i:i+200]
        used.update(k for k, value in zip(group, db.hmget(LEDGER, group)) if value)
    return select(games, clips.values(), used, now)


def compilation(clips):
    # Find the highest-ranked feasible group (at most three moments); avoid cubic search.
    suffix = [[] for _ in range(len(clips) + 1)]
    for i in reversed(range(len(clips))):
        suffix[i] = sorted([clips[i]["duration"], *suffix[i+1]], reverse=True)[:2]
    chosen = []
    for i, c in enumerate(clips):
        remaining = 2 - len(chosen)
        later = suffix[i+1][:remaining]
        group = chosen + [c]
        total = sum(x["duration"] for x in group)
        if len(group) >= 2 and total >= 63:
            return group
        if later and total + sum(later) >= 63:
            chosen = group
    return []


def portions(durations):
    # Share the target evenly; reassign seconds that a short source cannot supply.
    result = [0.0] * len(durations)
    left = min(TARGET, sum(durations))
    for n, i in enumerate(sorted(range(len(result)), key=durations.__getitem__)):
        result[i] = min(durations[i], left / (len(result)-n))
        left -= result[i]
    return result


def store():
    import redis
    return redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True,
                                socket_timeout=20, socket_connect_timeout=10)


def sources_config():
    config = json.loads(Path(__file__).with_name("streamers.json").read_text())
    channels = {s.strip(): {} for s in os.environ.get("ALLOWED_BROADCASTER_IDS", "").split(",") if s.strip()}
    for campaign in config["priority_streamers"]:
        if campaign.get("broadcaster_id"):
            channels[str(campaign["broadcaster_id"])] = campaign
    if not all(re.fullmatch(r"[0-9]+", i) for i in channels):
        raise ValueError("Set cleared numeric Twitch broadcaster IDs in streamers.json or ALLOWED_BROADCASTER_IDS.")
    for handle in os.getenv("ALLOWED_KICK_CHANNELS", "").lower().split(","):
        handle = handle.strip()
        if handle:
            if not re.fullmatch(r"[a-z0-9_-]+", handle):
                raise ValueError("Invalid Kick channel in ALLOWED_KICK_CHANNELS")
            channels["kick:" + handle] = {}
    if not channels:
        raise ValueError("Set cleared Twitch broadcaster IDs or ALLOWED_KICK_CHANNELS.")
    return channels, config


QUEUE = "gta-clips:ranked:v1"


def enqueue(root):
    db = store()
    if int(db.get(day_key()) or 0) >= daily_cap():
        print("Daily cap reached before discovery.")
        return
    channels, config = sources_config()
    game, candidates = discover(db, channels, config)
    with db.pipeline(transaction=True) as p:
        p.delete(QUEUE)
        if candidates:
            p.rpush(QUEUE, *(json.dumps([game, c]) for c in candidates))
            p.expire(QUEUE, int(config["lookback_hours"] * 3600))
        p.execute()
    print(f"Queued {len(candidates)} eligible {game} clips.")


def queued(db, channels, config):
    rows = []
    now = datetime.now(timezone.utc)
    for raw in db.lrange(QUEUE, 0, 49):
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        game, c = entry
        if (game not in (VI, V) or not isinstance(c, dict) or not isinstance(c.get("id"), str)
                or not isinstance(c.get("broadcaster_id"), str) or c["broadcaster_id"] not in channels):
            continue
        created = timestamp(c.get("created_at"))
        hours = min(3, config["lookback_hours"]) if c.get("platform") == "kick" else config["lookback_hours"]
        if created and now - timedelta(hours=hours) <= created <= now:
            rows.append((game, c))
    if not rows:
        return VI, []
    used = db.hmget(LEDGER, [c["id"] for _, c in rows])
    return rows[0][0], [c for (_, c), taken in zip(rows, used) if not taken]


def prepare(root):
    channels, config = sources_config()
    db = store()
    if os.getenv("DELIVERY_MODE") == "deliver":
        if int(db.get(day_key()) or 0) >= daily_cap():
            print("Daily delivery cap reached.")
            return
        game, candidates = queued(db, channels, config)
    else:
        game, candidates = discover(db, channels, config)
    if not candidates:
        print("No eligible unused GTA footage in the configured lookback.")
        return
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
    from faster_whisper import WhisperModel
    model, sources, speech = None, {}, {}
    def load(c):
        nonlocal model
        kick = c.get("platform") == "kick"
        slug = c["id"].removeprefix("kick:") if kick else c["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
            raise ValueError("Invalid source clip slug")
        if kick:
            handle = c["broadcaster_id"].removeprefix("kick:")
            url = kick_media_url(c.get("media_url"), slug) or f"https://kick.com/{handle}/clips/{slug}"
        else:
            url = "https://clips.twitch.tv/" + slug
        base = f"src{len(sources)}"
        with YoutubeDL({"quiet": True, "noplaylist": True, "cachedir": False, "socket_timeout": 30,
                        "format": "best[ext=mp4]/best", "outtmpl": str(root / (base+".%(ext)s"))}) as ydl:
            info = ydl.extract_info(url, download=True)
            if not isinstance(info, dict):
                return False
            src = Path(ydl.prepare_filename(info))
        sources[c["id"]] = src
        metadata = probe(src)
        video = next((s for s in metadata["streams"] if s["codec_type"] == "video"), None)
        if video is None:
            return False
        c["duration"] = min(float(video.get("duration") or metadata["format"]["duration"]),
                            c["duration"])
        if not any(s["codec_type"] == "audio" for s in metadata["streams"]):
            c["trim"] = 0
            c["duration"] = min(44.0, c["duration"])
            c["hype_hits"] = []
            speech[c["id"]] = []
            return True
        trim, active = analyze_audio(src, c["duration"])
        if not active:
            return False
        c["trim"] = trim
        c["duration"] = min(44.0, c["duration"] - trim)
        if model is None:
            model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=2,
                                 download_root=str(root / "model"))
        segments, _ = model.transcribe(str(src), word_timestamps=True, beam_size=1, vad_filter=True)
        words = []
        for segment in segments:
            for word in getattr(segment, "words", None) or ():
                start, end, text = (getattr(word, key, None) for key in ("start", "end", "word"))
                if valid_word((start, end, text)) and end > trim:
                    words.append((max(0, start - trim), end - trim, text.strip()))
        speech[c["id"]] = words
        transcript = " ".join(w.casefold() for start, end, w in words if start < c["duration"])
        c["hype_hits"] = [kw for kw in config["hype_keywords"] if kw.casefold() in transcript]
        return True

    eligible, short, group = [], None, []
    for c in candidates[:6]:
        try:
            accepted = load(c)
        except DownloadError:
            print(f"Skipped unavailable clip {c['id']}.")
            continue
        if not accepted:
            continue
        eligible.append(c)
        if short is None and c["duration"] >= 25:
            short = c
        group = compilation(eligible)
        if short and group:
            break
    if short is None:
        print("No eligible clip long enough for a 25-second Short.")
        return
    editorial = json.loads(Path(__file__).with_name("editorial.json").read_text())
    def cut(c, file, length, youtube=False):
        edit = editorial["clips"].get(c["id"], {})
        notes = [{**n, "start": n["start"] - c["trim"], "end": n["end"] - c["trim"]}
                 for n in edit.get("notes", [])]
        credit = c["broadcaster_name"]
        if youtube and c["campaign"].get("campaign_watermark"):
            credit += "  |  " + c["campaign"]["campaign_watermark"]
        render_vertical_short(sources[c["id"]], root/file, length, speech[c["id"]], edit.get("hook") or curiosity_hook(c["title"]),
               credit, notes=notes, start=c["trim"],
               facecam=editorial["facecams"].get(c["broadcaster_id"], [0, .55, .32, .35]))
    cut(short, "youtube.mp4", short["duration"], youtube=True)
    if not 25 <= seconds(root/"youtube.mp4") <= 45:
        raise RuntimeError("Rendered Short outside 25–45 second target")
    if group:
        parts = []
        for i, (c, length) in enumerate(zip(group, portions([c["duration"] for c in group]))):
            file = f"part{i}.mp4"
            cut(c, file, length)
            parts.append(root/file)
        join(parts, root/"tiktok.mp4")
        if not 62 < seconds(root/"tiktok.mp4") < 66:
            raise RuntimeError("Rendered compilation outside target length")
    else:
        print("Insufficient distinct footage for TikTok; keeping the YouTube Short.")
    (root/"batch.json").write_text(json.dumps({"game": game, "short": short, "group": group}))
    print(f"Prepared {game}: YouTube + {len(group)} TikTok segments.")


def reserve(db, ids, batch):
    # Watch for a competing run; a persistent pending record survives a lost upload response.
    with db.pipeline() as p:
        key = day_key()
        p.watch(LEDGER, key)
        if any(p.hmget(LEDGER, ids)):
            raise RuntimeError("Source already reserved or delivered; prepare a new batch.")
        if int(p.get(key) or 0) >= daily_cap():
            return False
        p.multi()
        p.incr(key)
        p.expire(key, 172800)
        p.hset(LEDGER, mapping={i: "pending:" + batch for i in ids})
        p.execute()
        return True


def publish(root):
    batch = json.loads((root/"batch.json").read_text())
    short, group = batch["short"], batch["group"]
    db = store()
    tag = os.environ.get("GITHUB_RUN_ID", root.name)
    ids = {c["id"] for c in [short, *group]}
    for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        if not os.getenv(key):
            raise ValueError("Missing " + key)
    tiktok_enabled = os.getenv("TIKTOK_ACCESS_TOKEN") or os.getenv("TIKTOK_REFRESH_TOKEN")
    if group and not tiktok_enabled and not os.getenv("ARTIFACT_ID"):
        raise ValueError("Archive the compilation before delivery.")
    if not reserve(db, sorted(ids), tag):
        print("Daily delivery cap reached before upload.")
        return
    outcomes = {i: {} for i in ids}
    outcomes[short["id"]]["youtube"] = "pending"
    for c in group:
        outcomes[c["id"]]["tiktok"] = "pending"
    def record(clips, dest, value):
        for c in clips:
            outcomes[c["id"]][dest] = value
        db.hset(LEDGER, mapping={c["id"]: json.dumps({"run": tag, **outcomes[c["id"]]}) for c in clips})
    errors = []
    for dest, clips in [("youtube", [short]), ("tiktok", group)]:
        if not clips:
            continue
        try:
            if dest == "youtube":
                result = delivery.youtube(root/"youtube.mp4", short, batch["game"])
            elif tiktok_enabled:
                result = delivery.tiktok(root/"tiktok.mp4", delivery.tiktok_token(db))
            else:
                result = "github-artifact:" + os.environ["ARTIFACT_ID"]  # workflow saved it before calling publish
            record(clips, dest, result)
            print(f"{dest}: {result}")
        except Exception as e:
            # Never log a signed URL, API response body, or credential. Keep reservations.
            status = getattr(getattr(e, "resp", None), "status", None)
            errors.append(f"{dest}: {type(e).__name__}" + (f" HTTP {status}" if status else ""))
    if errors:
        raise RuntimeError("; ".join(errors) + ". Check the account before clearing any reservations.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["enqueue", "prepare", "publish", "kick-trending"])
    parser.add_argument("work", type=Path, nargs="?")
    args = parser.parse_args()
    if args.action == "kick-trending":
        print(json.dumps(fetch_kick_clips(), indent=2))
        return
    if args.work is None:
        parser.error("this action needs a work directory")
    root = args.work.resolve()
    if not root.is_dir() or Path(tempfile.gettempdir()).resolve() not in root.parents:
        parser.error("use a dedicated existing subdirectory of the system temp directory")
    {"enqueue": enqueue, "prepare": prepare, "publish": publish}[args.action](root)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as e:
        sys.exit(str(e))
    except Exception as e:
        sys.exit(f"Pipeline failed: {type(e).__name__}. Check configuration, source, quota and connectivity.")
