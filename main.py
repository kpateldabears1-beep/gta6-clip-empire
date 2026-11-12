"""Run via .github/workflows/pipeline.yml; media and model live on the runner."""
import argparse
from datetime import datetime, timedelta, timezone
from itertools import combinations
import json
import math
import os
from pathlib import Path
import re
import sys
import subprocess
import shutil
import tempfile
from uuid import uuid4

from music_screen import MUSIC_CUE, RATE, MusicScreen, audio_activity, decode_audio
from render import MAX_SEGMENT_SECONDS, MIN_SEGMENT_SECONDS, join, probe, render_vertical_short, seconds, valid_word
import delivery
import bounties
import cloud_archive
from monitoring import DiagnosticError, error_trace, notify_post
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
        if (not created or not math.isfinite(duration) or duration < MIN_SEGMENT_SECONDS or views < 0
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
        "client_id": cloud_archive.required("TWITCH_CLIENT_ID"), "client_secret": cloud_archive.required("TWITCH_CLIENT_SECRET"),
        "grant_type": "client_credentials"}, timeout=25)
    r.raise_for_status()
    auth = r.json()
    if not isinstance(auth, dict) or not isinstance(auth.get("access_token"), str) or not auth["access_token"]:
        raise ValueError("Twitch token exchange returned no access token")
    headers = {"Client-Id": os.environ["TWITCH_CLIENT_ID"], "Authorization": "Bearer " + auth["access_token"]}
    def get(endpoint, **params):
        resp = requests.get("https://api.twitch.tv/helix/" + endpoint, params=params,
                            headers=headers, timeout=25)
        resp.raise_for_status()
        page = resp.json()
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise ValueError(f"Unexpected Twitch {endpoint} response")
        return page
    game_rows = get("games", name=config["target_game_names"])["data"]
    games = {g["name"]: g["id"] for g in game_rows
             if isinstance(g, dict) and isinstance(g.get("name"), str) and isinstance(g.get("id"), str)}
    handles = {}
    ids = list(channels)
    for i in range(0, len(ids), 100):
        users = get("users", id=ids[i:i+100])["data"]
        handles.update((u["id"], u["login"]) for u in users if isinstance(u, dict)
                       and isinstance(u.get("id"), str) and isinstance(u.get("login"), str) and u["login"])
    clips = {}
    for broadcaster in channels:
        if broadcaster not in handles:
            continue
        # Query the licensed channels, so smaller streams aren't buried in the global top 100.
        params = dict(broadcaster_id=broadcaster, started_at=(end-timedelta(hours=config["lookback_hours"])).isoformat(),
                      ended_at=end.isoformat(), first=100)
        for _ in range(10):  # Helix limits one query to roughly 1,000 results.
            page = get("clips", **params)
            for c in page["data"]:
                if (isinstance(c, dict) and isinstance(c.get("id"), str)
                        and c.get("broadcaster_id") == broadcaster and c.get("game_id") in games.values()):
                    clips[c["id"]] = dict(c, campaign=channels[broadcaster], broadcaster_login=handles[broadcaster])
            pagination = page.get("pagination")
            cursor = pagination.get("cursor") if isinstance(pagination, dict) else None
            if not isinstance(cursor, str) or not cursor:
                break
            params["after"] = cursor
    return games, clips


def discover(db, channels, config):
    now = datetime.now(timezone.utc)
    twitch = {k: v for k, v in channels.items() if not k.startswith("kick:")}
    handles = [k.removeprefix("kick:") for k in channels if k.startswith("kick:")]
    games, clips = {}, {}
    twitch_available = False
    if twitch:
        try:
            games, clips = twitch_clips(twitch, config, now)
            twitch_available = True
        except (OSError, ValueError) as error:
            if not handles:
                raise
            print(f"Twitch discovery failed ({type(error).__name__}); checking Kick.", file=sys.stderr)
    if handles:
        try:
            for c in fetch_kick_clips(handles, now=now):
                clips[c["id"]] = dict(c, campaign=channels[c["broadcaster_id"]])
        except RuntimeError:
            if not twitch_available:
                raise
            print("Kick feeds unavailable this run; continuing with Twitch.", file=sys.stderr)
    keys = list(clips)
    used = set()
    for i in range(0, len(keys), 200):
        group = keys[i:i+200]
        used.update(k for k, value in zip(group, db.hmget(LEDGER, group)) if value)
    return select(games, clips.values(), used, now)


def enough_speech(words, length):
    return sum(end <= length for _, end, _ in words) >= 4


def compilation(clips, speech=None):
    # At most six screened candidates. Check the actual excerpt each source would contribute.
    for size in (2, 3):
        for group in combinations(clips, size):
            lengths = portions([min(c["duration"], MAX_SEGMENT_SECONDS) for c in group])
            if sum(lengths) < 63 or min(lengths) < MIN_SEGMENT_SECONDS:
                continue
            if speech is None or all(enough_speech(speech[c["id"]], n) for c, n in zip(group, lengths)):
                return list(group)
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
    roster = config.get("watchlist", [])
    twitch_metadata = {str(c["broadcaster_id"]): c for c in roster if c.get("broadcaster_id")}
    kick_metadata = {c["username"]: c for c in roster if c.get("username")}
    channels = {}
    for token in os.getenv("ALLOWED_BROADCASTER_IDS", "").split(","):
        broadcaster = token.strip()
        if broadcaster:
            channels[broadcaster] = twitch_metadata.get(broadcaster, {})
    for campaign in config["priority_streamers"]:
        if campaign.get("broadcaster_id"):
            broadcaster = str(campaign["broadcaster_id"])
            channels[broadcaster] = {**twitch_metadata.get(broadcaster, {}), **campaign, "priority": True}
    if not all(re.fullmatch(r"[0-9]+", i) for i in channels):
        raise ValueError("Set cleared numeric Twitch broadcaster IDs in streamers.json or ALLOWED_BROADCASTER_IDS.")
    for handle in os.getenv("ALLOWED_KICK_CHANNELS", "").lower().split(","):
        handle = handle.strip()
        if handle:
            if not re.fullmatch(r"[a-z0-9_-]+", handle):
                raise ValueError("Invalid Kick channel in ALLOWED_KICK_CHANNELS")
            metadata = kick_metadata.get(handle, {})
            for campaign in config["priority_streamers"]:
                kick_name = campaign.get("kick_username") or (campaign.get("username") if not campaign.get("broadcaster_id") else None)
                if kick_name == handle or (metadata.get("broadcaster_id") and
                        str(campaign.get("broadcaster_id")) == metadata["broadcaster_id"]):
                    metadata = {**metadata, **campaign, "priority": True}
            channels["kick:" + handle] = metadata
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
            rows.append((game, dict(c, campaign=channels[c["broadcaster_id"]])))
    if not rows:
        return VI, []
    used = db.hmget(LEDGER, [c["id"] for _, c in rows])
    game = rows[0][0]
    candidates = [c for row_game, c in rows if row_game == game]
    return game, ranked(candidates, {c["id"] for (_, c), taken in zip(rows, used) if taken}, now)


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
    model, screen, sources, speech = None, None, {}, {}
    def load(c):
        nonlocal model, screen
        kick = c.get("platform") == "kick"
        slug = c["id"].removeprefix("kick:") if kick else c["id"]
        # Old queue records may have only the ordinary Twitch display name.
        handle = c["broadcaster_id"].removeprefix("kick:") if kick else c.get("broadcaster_login") or c.get("broadcaster_name")
        if not isinstance(handle, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", handle):
            print(f"Skipped {c['id']}: source handle unavailable.")
            return False
        c["broadcaster_login"] = handle
        if not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
            raise ValueError("Invalid source clip slug")
        if kick:
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
            print(f"Skipped {c['id']}: no audio or spoken words.")
            return False
        samples = decode_audio(src, min(c["duration"], MAX_SEGMENT_SECONDS + 1.5))
        trim, active = audio_activity(samples)
        if not active:
            return False
        c["trim"] = trim
        c["duration"] = min(MAX_SEGMENT_SECONDS, c["duration"] - trim)
        if c["duration"] < MIN_SEGMENT_SECONDS:
            return False
        if model is None:
            model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=2,
                                 download_root=str(root / "model"))
        start_sample = round(trim * RATE)
        samples = samples[start_sample:start_sample + round(c["duration"] * RATE)]
        segments, _ = model.transcribe(samples, word_timestamps=True, beam_size=1, vad_filter=True)
        words, cues = [], []
        for segment in segments:
            if MUSIC_CUE.search(segment.text):
                cues.append((segment.start, segment.end))
            if not re.search(r"[^\W_]", re.sub(r"\[[^\]]*\]|\([^)]*\)", "", segment.text)):
                continue
            annotation = False
            for word in getattr(segment, "words", None) or ():
                start, end, text = (getattr(word, key, None) for key in ("start", "end", "word"))
                if not valid_word((start, end, text)):
                    continue
                if annotation or "[" in text or "(" in text:
                    annotation = "]" not in text and ")" not in text
                    continue
                if re.search(r"[^\W_]", text) and start >= 0 and end <= c["duration"]:
                    words.append((start, end, text.strip()))
        if not enough_speech(words, c["duration"]):
            print(f"Skipped {c['id']}: fewer than four spoken words in the cut.")
            return False
        if screen is None:
            screen = MusicScreen()
        flagged = screen.flagged_span(samples, words, cues)
        if flagged:
            print(f"Skipped {c['id']}: sustained music without commentary at {flagged[0]+trim:.1f}–{flagged[1]+trim:.1f}s.")
            return False
        speech[c["id"]] = words
        transcript = " ".join(w.casefold() for start, end, w in words if start < c["duration"])
        c["words_per_minute"] = round(60 * len(words) / c["duration"], 1)
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
        if short is None:
            short = c
        group = compilation(eligible, speech)
        if short and group:
            break
    if short is None:
        print("No eligible source passed the duration and speech checks.")
        return
    editorial = json.loads(Path(__file__).with_name("editorial.json").read_text())
    def cut(c, file, length):
        edit = editorial["clips"].get(c["id"], {})
        notes = [{**n, "start": n["start"] - c["trim"], "end": n["end"] - c["trim"]}
                 for n in edit.get("notes", [])]
        platform = "Kick" if c.get("platform") == "kick" else "Twitch"
        render_vertical_short(sources[c["id"]], root/file, length, speech[c["id"]], c["title"],
               c["broadcaster_login"], platform=platform, campaign=c["campaign"].get("campaign_watermark"),
               notes=notes, start=c["trim"], hook=edit.get("hook"),
               facecam=editorial["facecams"].get(c["broadcaster_id"], [0, .55, .32, .35]))
    short_file = root / "youtube-rendering.mp4"
    cut(short, short_file.name, short["duration"])
    if not MIN_SEGMENT_SECONDS <= seconds(short_file) < 44:
        raise RuntimeError("Rendered Short must be at least 18 and under 44 seconds")
    short_file.replace(root / "youtube.mp4")
    if group:
        parts = []
        for i, (c, length) in enumerate(zip(group, portions([c["duration"] for c in group]))):
            file = f"part{i}.mp4"
            cut(c, file, length)
            parts.append(root/file)
        compilation_file = root / "tiktok-rendering.mp4"
        join(parts, compilation_file)
        if not 62 < seconds(compilation_file) < 66:
            raise RuntimeError("Rendered compilation outside target length")
        compilation_file.replace(root / "tiktok.mp4")
    else:
        print("Insufficient distinct footage for TikTok; keeping the YouTube Short.")
    batch_id = os.getenv("GITHUB_RUN_ID", root.name)
    attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    if attempt != "1":
        batch_id += "-" + attempt
    for cut_name, clips in (("short", [short]), ("compilation", group)):
        bounties.register(db, batch_id, cut_name, clips)
    (root/"batch.json").write_text(json.dumps({"game": game, "short": short, "group": group, "batch_id": batch_id}))
    print(f"Prepared {game}: YouTube + {len(group)} TikTok segments.")


def reserve(db, ids, batch, *, second_post_ids=()):
    # Redis retries WATCH conflicts before any platform call. An ambiguous upload keeps its slot.
    key, cap = day_key(), daily_cap()
    def transaction(p):
        available = cap - int(p.get(key) or 0)
        slots = 2 if second_post_ids and available >= 2 else 1
        chosen = sorted(set(ids).union(second_post_ids if slots == 2 else ()))
        if any(p.hmget(LEDGER, chosen)):
            raise RuntimeError("Source already reserved or delivered; prepare a new batch.")
        if available <= 0:
            return 0
        p.multi()
        p.incrby(key, slots)
        p.expire(key, 172800)
        p.hset(LEDGER, mapping={i: "pending:" + batch for i in chosen})
        return slots
    return db.transaction(transaction, LEDGER, key, value_from_callable=True)


def publish(root):
    batch = json.loads((root/"batch.json").read_text())
    if not isinstance(batch, dict) or batch.get("game") not in (V, VI):
        raise ValueError("Invalid clip batch or game")
    short, group = batch.get("short"), batch.get("group")
    if not isinstance(group, list) or not all(
            isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"] for c in [short, *group]):
        raise ValueError("Batch needs a rendered Short and a list of compilation clips")
    db = store()
    tag = os.environ.get("GITHUB_RUN_ID", root.name)
    ids = {c["id"] for c in [short, *group]}
    for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        if not os.getenv(key):
            raise ValueError("Missing " + key)
    tiktok_enabled = os.getenv("TIKTOK_ACCESS_TOKEN") or os.getenv("TIKTOK_REFRESH_TOKEN")
    if group and not tiktok_enabled and not os.getenv("ARTIFACT_ID"):
        raise ValueError("Archive the compilation before delivery.")
    second_ids = [c["id"] for c in group] if tiktok_enabled else []
    slots = reserve(db, [short["id"]] if second_ids else sorted(ids), tag, second_post_ids=second_ids)
    if not slots:
        print("Daily delivery cap reached before upload.")
        return
    if second_ids and slots == 1:
        group = []
        print("One daily post slot remained. Reserved it for the Short.")
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
        cut_name = "short" if dest == "youtube" else "compilation"
        tracked = any(bounties.active(c) for c in clips)
        receipt = None
        try:
            if dest == "youtube":
                upload = delivery.youtube(root/"youtube.mp4", short, batch["game"], with_receipt=tracked)
                if tracked:
                    receipt, result = upload, upload["id"]
                else:
                    result = upload
            elif tiktok_enabled:
                result = delivery.tiktok(root/"tiktok.mp4", delivery.tiktok_token(db), wait_for_inbox=not tracked)
                receipt = result.split(":", 1)[1]
            else:
                result = "github-artifact:" + os.environ["ARTIFACT_ID"]  # workflow saved it before calling publish
            pending = None
            if tracked and receipt is not None:
                batch_id = batch.get("batch_id", tag)
                bounties.register(db, batch_id, cut_name, clips)
                pending = bounties.queue(db, batch_id, cut_name, dest, receipt)
            record(clips, dest, result)
            print(f"{dest}: {result}")
        except Exception as e:
            # Never log a signed URL, API response body, or credential. Keep reservations.
            error_trace(e, dest)
            status = getattr(getattr(e, "resp", None), "status", None)
            errors.append(f"{dest}: {type(e).__name__}" + (f" HTTP {status}" if status else ""))
        else:
            try:
                if pending:
                    bounties.process(db, pending)
                notify_post(dest, result)
            except Exception as exc:
                error_trace(exc, f"{dest} notification")
                errors.append(f"{dest} delivered; notification failed ({type(exc).__name__})")
    if errors:
        raise RuntimeError("; ".join(errors) + ". Check the account before clearing any reservations.")


def check_redis_read_write():
    db = store()
    key = "gta-clips:health:" + uuid4().hex
    value = uuid4().hex
    if not db.set(key, value, nx=True, ex=120):
        raise DiagnosticError("Could not create a unique Redis probe key")
    try:
        if db.get(key) != value:
            raise DiagnosticError("Redis returned a different value")
    finally:
        if db.delete(key) != 1:
            raise DiagnosticError("Redis probe key could not be removed")


def dry_run(root):
    """Check real services with one synthetic spoken clip and no delivery credentials."""
    def twitch():
        games, _ = twitch_clips({}, {"target_game_names": [V]}, datetime.now(timezone.utc))
        if V not in games:
            raise DiagnosticError("Twitch did not return the GTA V game ID")

    def kick():
        from kick import clip_page
        # The clip feed itself is public. Validate any configured app key pair as well.
        if os.getenv("KICK_CLIENT_ID") or os.getenv("KICK_CLIENT_SECRET"):
            import requests
            response = requests.post("https://id.kick.com/oauth/token", data={
                "grant_type": "client_credentials", "client_id": cloud_archive.required("KICK_CLIENT_ID"),
                "client_secret": cloud_archive.required("KICK_CLIENT_SECRET")}, timeout=15)
            response.raise_for_status()
            if not response.json().get("access_token"):
                raise DiagnosticError("Kick token exchange returned no token")
        clip_page("adinross", {"sort": "date", "time": "day"})

    source, video = root / "source.mp4", root / "health.mp4"
    test_clip = None

    def split_screen():
        nonlocal test_clip
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if not binary:
            raise DiagnosticError("Install espeak-ng or espeak to generate the spoken clip")
        wave = root / "speech.wav"
        subprocess.run([binary, "-s", "145", "-w", str(wave),
                        "The quick brown fox jumps over the lazy dog."], check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=blue:s=320x180:r=30,drawbox=x=0:y=0:w=96:h=54:color=red:t=fill",
                        "-i", str(wave), "-map", "0:v", "-map", "1:a", "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
        # If the renderer fails, Whisper and R2 can still diagnose their own service using the source.
        test_clip = source
        render_vertical_short(source, video, seconds(source), [], "Health check", "Synthetic fixture",
                              facecam=[0, 0, .3, .3])
        streams = probe(video)["streams"]
        if not any(s.get("width") == 1080 and s.get("height") == 1920 for s in streams):
            raise DiagnosticError("Rendered clip is not 1080 by 1920")
        if not any(s.get("codec_name") == "aac" and s.get("channels") == 2 for s in streams):
            raise DiagnosticError("Rendered clip lacks stereo AAC")
        for y, component in ((1148, 2), (1152, 0)):
            rgb = subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-vf",
                f"crop=2:2:100:{y},scale=1:1,format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"])
            if len(rgb) != 3 or rgb[component] < 180 or any(v > 80 for i, v in enumerate(rgb) if i != component):
                raise DiagnosticError("Incorrect gameplay or facecam pixels at the panel boundary")
        test_clip = video

    def media():
        if test_clip is None:
            raise DiagnosticError("Could not generate the spoken test clip")
        return test_clip

    def transcribe():
        clip = media()
        from faster_whisper import WhisperModel
        model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=2,
                             download_root=str(root / "model"))
        segments, _ = model.transcribe(str(clip), language="en", beam_size=1)
        words = set(re.findall(r"[a-z]+", " ".join(s.text for s in segments).lower()))
        if len(words & {"quick", "brown", "fox", "jumps", "lazy", "dog"}) < 2:
            raise DiagnosticError("Whisper did not recognize the spoken test phrase")

    def upload():
        cloud_archive.check_upload(media())

    kick_label = "Kick public feed" + (" and app keys" if os.getenv("KICK_CLIENT_ID") or os.getenv("KICK_CLIENT_SECRET")
                                      else " (keyless)")
    failed, report = [], []
    for name, check in [("Twitch app keys and Helix", twitch), (kick_label, kick),
                        ("Upstash Redis write, read and delete", check_redis_read_write),
                        ("FFmpeg gameplay top, facecam bottom and AAC", split_screen),
                        ("Whisper speech transcription", transcribe),
                        ("R2 upload, signed download and delete", upload)]:
        try:
            check()
            line = f"PASS  {name}"
            if check in (transcribe, upload):
                line += " (source clip)" if test_clip == source else " (rendered clip)"
        except Exception as exc:
            failed.append(name)
            line = "FAIL  " + error_trace(exc, name)
        report.append(line)
        print(line, flush=True)
    summary = f"{len(report) - len(failed)}/{len(report)} health checks passed"
    print(summary, flush=True)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as handle:
            handle.write("### " + summary + "\n\n```text\n" + "\n".join(report) + "\n```\n")
    if failed:
        raise DiagnosticError("Health checks failed: " + ", ".join(failed))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="run all live dependency checks without posting")
    parser.add_argument("action", nargs="?", choices=["archive", "enqueue", "prepare", "publish", "kick-trending", "bounty-check", "bounty-published"])
    parser.add_argument("work", type=Path, nargs="?")
    args = parser.parse_args()
    if args.dry_run:
        if args.action or args.work:
            parser.error("run --dry-run on its own")
        with tempfile.TemporaryDirectory(prefix="gta-health-") as tmp:
            dry_run(Path(tmp))
        return
    if not args.action:
        parser.error("select an action or use --dry-run")
    if args.action == "bounty-check":
        bounties.reconcile(store())
        return
    if args.action == "bounty-published":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        bounties.published_event(store(), event["client_payload"])
        return
    if args.action == "kick-trending":
        print(json.dumps(fetch_kick_clips(), indent=2))
        return
    if args.work is None:
        parser.error("this action needs a work directory")
    root = args.work.resolve()
    if not root.is_dir() or Path(tempfile.gettempdir()).resolve() not in root.parents:
        parser.error("use a dedicated existing subdirectory of the system temp directory")
    {"enqueue": enqueue, "prepare": prepare, "publish": publish, "archive": cloud_archive.archive}[args.action](root)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as e:
        print(error_trace(e), file=sys.stderr)
        sys.exit(str(e))
    except Exception as e:
        sys.exit("Pipeline failed: " + error_trace(e))
