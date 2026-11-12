"""Campaign alerts for confirmed public posts; pending receipts survive runner cleanup."""
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit

from monitoring import send_alert

PREFIX = "gta-clips:bounty:"
TTL = 30 * 86400
PATHS = {
    "youtube": ("youtube.com", r"/shorts/[A-Za-z0-9_-]{11}"),
    "tiktok": ("tiktok.com", r"/@[A-Za-z0-9._]+/video/[0-9]+/?"),
    "instagram": ("instagram.com", r"/reel/[A-Za-z0-9_-]+/?"),
    "rumble": ("rumble.com", r"/v[a-zA-Z0-9]+(?:-[A-Za-z0-9._%-]+)?\.html"),
}


def permalink(platform, url):
    parts = urlsplit(url)
    host, path = PATHS[platform]
    if parts.scheme != "https" or parts.netloc not in (host, "www." + host) or not re.fullmatch(path, parts.path):
        raise ValueError("Expected a public platform post permalink")
    canonical_host = host if platform == "rumble" else "www." + host
    return "https://" + canonical_host + parts.path.rstrip("/")


def active(clip):
    campaign = clip.get("campaign") or {}
    code = campaign.get("campaign_watermark")
    return campaign.get("priority") is True and isinstance(code, str) and bool(code.strip())


def register(db, run, cut, clips):
    campaigns = []
    for clip in clips:
        campaign = clip.get("campaign") or {}
        code = campaign.get("campaign_watermark")
        if active(clip):
            entry = {"handle": clip["broadcaster_login"], "code": code.strip(), "source": clip["id"]}
            if entry not in campaigns:
                campaigns.append(entry)
    if campaigns:
        db.set(PREFIX + f"cut:{run}:{cut}", json.dumps(campaigns), ex=TTL)
    return campaigns


def digest(*values):
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def queue(db, run, cut, platform, receipt, *, url=None, published=None):
    campaigns = db.get(PREFIX + f"cut:{run}:{cut}")
    if not campaigns:
        return None
    item = {"platform": platform, "receipt": receipt, "campaigns": json.loads(campaigns)}
    if url is not None:
        item["url"] = permalink(platform, url)
        item["published"] = published
    key = PREFIX + "pending:" + digest(run, cut, platform, receipt)
    db.set(key, json.dumps(item), nx=True, ex=TTL)
    return key


def process(db, key):
    import delivery
    # Immediate delivery, webhook retries and the scheduled reconciler share this lock.
    with db.lock(PREFIX + "lock:" + digest(key), timeout=120, blocking_timeout=30):
        raw = db.get(key)
        if not raw:
            return
        item = json.loads(raw)
        platform = item["platform"]
        if "url" in item:
            posts = [(item["url"], item["published"])]
        elif platform == "youtube":
            posts = delivery.public_youtube_post(item["receipt"])
        else:
            posts = delivery.public_tiktok_posts(db, item["receipt"])
        if posts is None:  # The platform is still processing, moderating or waiting for the creator.
            return
        for url, published in posts:
            url = permalink(platform, url)
            sent = PREFIX + "sent:" + digest(url, item["campaigns"])
            with db.lock(PREFIX + "lock:" + digest(sent), timeout=30, blocking_timeout=20):
                if db.get(sent):
                    continue
                publication = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if publication.tzinfo is None:
                    raise ValueError("Publication time must include a timezone")
                deadline = int(publication.timestamp()) + 1800
                lines = [f"Clipping bounty • {platform}", url, f"30-minute submission target: <t:{deadline}:t> (<t:{deadline}:R>)"]
                lines.extend(f"@{c['handle']} · {c['code']} · {c['source']}" for c in item["campaigns"])
                if not send_alert("\n".join(lines), discord_only=True):
                    raise ValueError("Missing DISCORD_WEBHOOK_URL")
                db.set(sent, json.dumps({"platform": platform, "url": url, "published_at": published,
                                         "deadline": deadline, "campaigns": item["campaigns"]}), ex=TTL)
        db.delete(key)


def reconcile(db):
    errors = []
    for key in db.scan_iter(match=PREFIX + "pending:*"):
        try:
            process(db, key)
        except Exception as exc:
            errors.append(type(exc).__name__)
    if errors:
        raise RuntimeError("Bounty receipt checks failed: " + ", ".join(errors))


def published_event(db, payload):
    # An authenticated repository_dispatch from the external publisher confirms the live URL.
    run, cut, platform = (payload.get(k) for k in ("run_id", "cut", "platform"))
    if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?", str(run)) or cut not in ("short", "compilation") or platform not in PATHS:
        raise ValueError("Invalid bounty publication event")
    url = permalink(platform, payload["url"])
    published = datetime.fromisoformat(payload["published_at"].replace("Z", "+00:00"))
    if published.tzinfo is None or published > datetime.now(timezone.utc):
        raise ValueError("Expected the timestamp of an already published post")
    key = queue(db, run, cut, platform, url, url=url, published=published.isoformat())
    if key:
        process(db, key)
    else:
        print("No active bounty registered for this rendered cut.")
