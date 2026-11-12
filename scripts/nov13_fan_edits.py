"""One dated YouTube fan-edit batch; no permission for fresh clips is inferred."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import probe, render_vertical_short, valid_word
from music_screen import MusicScreen, decode_audio, MUSIC_CUE
from delivery import youtube
from main import reserve, store, LEDGER, V

POLICY = "https://www.reddit.com/r/DougDoug/comments/1hzagjn/"
SLOTS = (8,11,14,17,20)
# Handpicked from the GTA V rows of DougDoug's all-time TwitchMetrics pages 1–4.
CANDIDATES = [
    ("WimpyPolishedHorseradishDuDudu","Twitch chat lands a plane in GTA V","Can chat land it?"),
    ("SmallBoldDurianTheRinger-_MeygnyoOJFdxmLf","DougDoug bets the GTA tank survives the rockets","Can the tank survive?"),
    ("TardyPolishedFiddleheadsDBstyle-WluufHQSRh7uGOpp","Twitch chat tries counting to five in GTA V","Can chat count together?"),
    ("FamousAgreeableKimchiRalpherZ","DougDoug tries driving by shouting Vroom Vroom","Does voice control work?"),
    ("NiceScrumptiousWolfBatChest","DougDoug leaves GTA with one instruction: don't die","One rule for chat"),
    ("MistyWanderingDragonDoubleRainbow","DougDoug's idea of normal GTA V gameplay","A normal GTA day?"),
    ("MistyFunCheddarHeyGuys-_A22SSNeY66PeIhb","DougDoug's GTA chat says hello to YouTube","Chat meets YouTube"),
    ("CourageousConcernedMinkBCouch-K0fu35KJZEUCKvok","A wholesome DougDoug moment in GTA V","A moment for chat"),
    ("TentativeWittyHorseradishBrainSlug-A1QLCCO8LzCOe2a8","DougDoug's GTA birthday shoutout for Shiro","Chat has a surprise"),
]

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare(out):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
    from faster_whisper import WhisperModel
    out.mkdir(parents=True, exist_ok=True)
    screen = MusicScreen()
    model = WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=2)
    batch = []
    for slug,title,hook in CANDIDATES:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            url = "https://clips.twitch.tv/" + slug
            try:
                with YoutubeDL({"outtmpl":str(root/"source.%(ext)s"),"noplaylist":True,"quiet":True,
                                "format":"best[ext=mp4]/best","socket_timeout":25}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    posted = info.get("timestamp") or 0
                    views = info.get("view_count") or 0
                    if (str(info.get("channel_id")) != "31507411" or
                            V not in (info.get("categories") or [V])):
                        print("Skipped: unverified broadcaster",slug,flush=True)
                        continue
                    if not 0 < posted < datetime(2025,11,13,tzinfo=timezone.utc).timestamp() or views < 100:
                        print("Skipped: age/views",slug,posted,views,flush=True)
                        continue
                    info = ydl.extract_info(url, download=True)
                    src = Path(ydl.prepare_filename(info))
            except DownloadError:
                print("Unavailable",slug,flush=True)
                continue
            duration = float(probe(src)["format"]["duration"])
            length = min(38.,duration-.08)
            replay = slug == "SmallBoldDurianTheRinger-_MeygnyoOJFdxmLf" and 14 <= length < 18
            if length < 18 and not replay:
                print("Too short:", slug,duration,flush=True)
                continue
            # Preserve the payoff at the end of the fan-clipped moment.
            start = max(0.,round(duration-length-.08, 3))
            for start,length in [(start,length)] + ([(0,18.5)] if duration >= 20 else []):
                samples = decode_audio(src,length,start=start)
                segments,_ = model.transcribe(samples, word_timestamps=True, vad_filter=True, beam_size=1)
                words,cues = [],[]
                for seg in segments:
                    if MUSIC_CUE.search(seg.text): cues.append((seg.start,seg.end))
                    else: words.extend((w.start,w.end,w.word.strip()) for w in seg.words or [] if valid_word((w.start,w.end,w.word)))
                if len(words)>=4 and not screen.flagged_span(samples,words,cues):
                    break
            else:
                print("Skipped: speech/music check",slug,flush=True)
                continue
            n = len(batch)+1
            raw = root/"cut.mp4"
            notes = []
            if replay:
                # Replay the last three seconds at 0.75x, with a closer view and no repeated dialogue.
                edited = root/"replay.mp4"
                graph = (f"[0:v]trim=end={length},setpts=PTS-STARTPTS[v];[0:a]atrim=end={length},asetpts=PTS-STARTPTS[a];"
                         f"[0:v]trim=start={length-3}:end={length},setpts=(PTS-STARTPTS)/0.75,"
                         "zoompan=z=1.18:x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1280x720:fps=30[r];"
                         "[v]scale=1280:720,setsar=1[v0];[r]setsar=1[r0];anullsrc=r=44100:cl=stereo,atrim=duration=4[s];"
                         "[v0][a][r0][s]concat=n=2:v=1:a=1[vid][aud]")
                graph = graph.replace(",zoompan=",",fps=30,zoompan=")
                subprocess.run(["ffmpeg","-v","error","-i",str(src),"-filter_complex",graph,"-map","[vid]","-map","[aud]",
                                "-t",str(length+4),"-r","30","-c:v","libx264","-preset","ultrafast",str(edited)],check=True)
                notes=[dict(start=length,end=length+4,text="Replay · 0.75×")]
                src,start,length=edited,0,length+4
            render_vertical_short(src,raw,length,[],title,"DougDoug",notes=notes,start=start,hook=hook,platform="Twitch")
            final = out/f"slot{n}.mp4"
            subprocess.run(["ffmpeg","-v","error","-i",str(raw),"-c:v","copy","-af","loudnorm=I=-16:TP=-2:LRA=9",
                            "-ar","44100","-c:a","aac","-b:a","160k","-movflags","+faststart",str(final)],check=True)
            subprocess.run(["ffmpeg","-v","error","-xerror","-i",str(final),"-f","null","-"],check=True)
            batch.append(dict(id=slug,title=title,url=url,broadcaster_name="DougDoug on Twitch",
                         description_intro="Unofficial DougDoug fan edit by Daily Getaway Clips. Original gameplay and commentary: DougDoug.",
                         views=views,date=datetime.fromtimestamp(posted,timezone.utc).date().isoformat(),
                         policy=POLICY,sha256=digest(final),slot=SLOTS[n-1]))
            print("Verified",slug,views,batch[-1]["date"],title,flush=True)
            if n == 5: break
    if len(batch)!=5: raise RuntimeError(f"Only {len(batch)} eligible videos; batch not released")
    (out/"manifest.json").write_text(json.dumps(batch,indent=2))

def deliver(out):
    now = datetime.now(ZoneInfo("America/Chicago"))
    if str(now.date())!="2026-11-13" or now.hour not in SLOTS or now.minute<15:
        raise RuntimeError("Outside authorized Chicago window")
    rows=json.loads((out/"manifest.json").read_text())
    if len(rows)!=5 or len({r["id"] for r in rows})!=5: raise ValueError("Incomplete batch")
    i=SLOTS.index(now.hour)
    row,video=rows[i],out/f"slot{i+1}.mp4"
    if row["slot"]!=now.hour or row["id"] not in {c[0] for c in CANDIDATES} or digest(video)!=row["sha256"]:
        raise ValueError("Unverified artifact")
    db=store()
    os.environ["POSTING_SLOT"]=f"{now.date()}:{now.hour:02d}"
    if not reserve(db,[row["id"]],os.environ["GITHUB_RUN_ID"]): return
    receipt=youtube(video,row,V,with_receipt=True)
    db.hset(LEDGER,row["id"],json.dumps({"youtube":receipt["id"],"status":receipt["status"]}))
    print("YouTube receipt:",receipt["id"],receipt["status"].get("privacyStatus"))

if __name__=="__main__":
    {"prepare":prepare,"deliver":deliver}[sys.argv[1]](Path(sys.argv[2]).resolve())
