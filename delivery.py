"""Platform delivery. Never print OAuth credentials or signed upload URLs."""
import base64
import hashlib
import hmac
import json
import os
import time


def youtube(path, clip, game):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YOUTUBE_CLIENT_ID"],
                        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"])
    tags = (["GTA6", "GTAVI"] if game.endswith(" VI") else ["GTA5", "GTAV"]) + ["Gaming", "Shorts"]
    tags += [t.lstrip("#") for t in clip.get("campaign", {}).get("extra_tags", []) if t.lstrip("#")]
    tags = list(dict.fromkeys(tags))
    title = (clip["title"] or game).replace("<", "").replace(">", "").strip()[:80] or game
    body = {"snippet": {"title": title + " #Shorts", "categoryId": "20", "tags": tags,
                        "description": f'{game}\nCredit: {clip["broadcaster_name"]}\n{clip["url"]}\n'
                                       + " ".join("#" + t for t in tags)},
            "status": {"privacyStatus": "public"}}
    request = build("youtube", "v3", credentials=creds, cache_discovery=False).videos().insert(
        part="snippet,status", body=body, notifySubscribers=False,
        media_body=MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8*1024**2, resumable=True))
    result = None
    while result is None:
        _, result = request.next_chunk(num_retries=3)
    print("YouTube reported visibility:", result.get("status", {}).get("privacyStatus", "unknown"))
    return result["id"]


def chunks(size):
    unit = min(size, 16 * 1024**2)
    count = size // unit
    return unit, [unit] * (count - 1) + [size - unit * (count - 1)]


def tiktok_token(db):
    import requests
    from cryptography.fernet import Fernet
    seed = os.getenv("TIKTOK_REFRESH_TOKEN")
    if not seed:
        return os.environ["TIKTOK_ACCESS_TOKEN"]
    # The client secret stays in GitHub. Rotated tokens in Redis are authenticated ciphertext.
    secret = os.environ["TIKTOK_CLIENT_SECRET"]
    key = os.environ["TIKTOK_CLIENT_KEY"]
    digest = hmac.digest(secret.encode(), ("gta-tiktok:" + key + ":" + seed).encode(), "sha256")
    cipher = Fernet(base64.urlsafe_b64encode(digest))
    cache = "gta-clips:oauth:" + hashlib.sha256(digest).hexdigest()[:24]
    with db.lock(cache + ":lock", timeout=60, blocking_timeout=40):
        saved = db.get(cache)
        state = json.loads(cipher.decrypt(saved.encode())) if saved else {}
        if state.get("expires", 0) > time.time() + 120:
            return state["access"]
        resp = requests.post("https://open.tiktokapis.com/v2/oauth/token/",
                             data={"client_key": key, "client_secret": secret, "grant_type": "refresh_token",
                                   "refresh_token": state.get("refresh", seed)}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        state = {"expires": time.time() + int(data["expires_in"]), "access": data["access_token"],
                 "refresh": data["refresh_token"]}
        encrypted = cipher.encrypt(json.dumps(state).encode())
        db.set(cache, encrypted, ex=int(data["refresh_expires_in"]))
        return state["access"]


def tiktok(path, token):
    import requests
    size = path.stat().st_size
    unit, sizes = chunks(size)
    r = requests.post("https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
                      headers={"Authorization": "Bearer " + token},
                      json={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": unit, "total_chunk_count": len(sizes)}}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data["error"]["code"] != "ok":
        raise RuntimeError("TikTok inbox init: " + data["error"]["code"])
    with path.open("rb") as f:
        start = 0
        for n in sizes:
            resp = requests.put(data["data"]["upload_url"], data=f.read(n), timeout=120,
                                headers={"Content-Type": "video/mp4",
                                         "Content-Range": f"bytes {start}-{start+n-1}/{size}"})
            if resp.status_code not in (201, 206):
                raise RuntimeError(f"TikTok media transfer HTTP {resp.status_code}")
            start += n
    publish_id = data["data"]["publish_id"]
    for _ in range(8):
        status = requests.post("https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                               headers={"Authorization": "Bearer " + token},
                               json={"publish_id": publish_id}, timeout=15)
        status.raise_for_status()
        state = status.json()["data"]["status"]
        if state in {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"}:
            return f"{state}:{publish_id}"
        if state == "FAILED":
            raise RuntimeError(f"TikTok processing failed for {publish_id}")
        time.sleep(3)
    return f"processing:{publish_id}"
