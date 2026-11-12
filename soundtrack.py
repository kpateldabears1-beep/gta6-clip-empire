"""Music mixes from a pinned collection of CC0 recordings."""
import json
from pathlib import Path
import random
import subprocess
import tempfile

from cloud_archive import file_digest
from render import probe

# Source pages: https://opengameart.org/content/<slug>. All five list CC0.
# (title, artist, slug, hosted filename, SHA-256)
TRACKS = [
    ("Neon Sign Circuit", "MintoDog", "neon-sign-circuit", "neon_sign_circuit_bpm145_0.ogg", "1cf9a53799cb7d8eb6e53a819233ba96f3afb6bcf73801b1050645d94687cdb4"),
    ("Hot Roadway", "MintoDog", "hot-roadway", "hot_roadway_bpm160_0.ogg", "66d065b2c48d41f7bf86635a81296b99e5963075dccf4906c83c573f53971a7c"),
    ("Pure Raceway", "MintoDog", "pure-raceway", "pure_raceway_bpm160_0.ogg", "e384208fc0bed123b68fd31e28df2d7bc3e8463551e49d681d700b2c21565e5d"),
    ("Cool Highway", "MintoDog", "cool-highway-remake", "cool_highway_remake_bpm140_0.ogg", "33dfa0ed9bdf535469f15a7e12f720d3e5d117a42d1e680bb93a20fd1c57929c"),
    ("Menu Music", "wipics", "menu-music-1", "menu_3.ogg", "bcbf3a7e6d9e05be1d15c7f59500f62236c8cb928027dd03d83f29338fbda58f"),
]


def music_mix(video, track=None, *, preserve_audio=False):
    title, artist, slug, filename, sha = track or random.choice(TRACKS)
    with tempfile.TemporaryDirectory(dir=video.parent) as folder:
        music, output = Path(folder)/"track.ogg", Path(folder)/"mixed.mp4"
        subprocess.run(["curl", "-fsSL", "--retry", "2", "--max-time", "45",
                        "https://opengameart.org/sites/default/files/" + filename, "-o", str(music)], check=True)
        if file_digest(music) != sha:
            raise ValueError("Unexpected audio file for " + title)
        video_stream = next(s for s in probe(video)["streams"] if s["codec_type"] == "video")
        duration = float(video_stream["duration"])
        # Loop short tracks seamlessly. Trim before loudnorm to measure the actual excerpt.
        bed = (f"[1:a]atrim=duration={duration},asetpts=PTS-STARTPTS,"
               f"afade=t=in:d=0.06,afade=t=out:st={max(0,duration-.45):.3f}:d=0.45")
        if preserve_audio:
            # Keep the live reaction in front and turn the instrumental down during speech.
            fx = (bed + ",volume=0.20[bed];[0:a]asplit[voice][key];"
                  "[bed][key]sidechaincompress=threshold=0.025:ratio=6:attack=15:release=240[ducked];"
                  "[voice][ducked]amix=inputs=2:duration=first:normalize=0,")
        else:
            fx = bed + ","
        fx += "loudnorm=I=-16:TP=-2:LRA=9[mix]"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-stream_loop", "-1", "-ss", "4",
                        "-i", str(music), "-filter_complex", fx, "-map", "0:v:0", "-map", "[mix]", "-t", str(duration),
                        "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k",
                        "-movflags", "+faststart", str(output)], check=True, timeout=150)
        audio = next(s for s in probe(output)["streams"] if s["codec_type"] == "audio")
        if audio["channels"] != 2 or abs(float(audio["duration"]) - duration) > .1:
            raise ValueError("Music did not cover the full video")
        meter = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-i", str(output),
                                "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                               capture_output=True, text=True, check=True, timeout=90)
        levels = json.loads(meter.stderr[meter.stderr.rindex("{"):])
        loudness, peak = float(levels["input_i"]), float(levels["input_tp"])
        if not -20 <= loudness <= -12 or not peak < 0:
            raise ValueError(f"Music failed level check: {loudness} LUFS, {peak} dBTP")
        print(f"Mix verified: {title}, {loudness} LUFS, {peak} dBTP", flush=True)
        output.replace(video)
    return f"{title} by {artist} (CC0) https://opengameart.org/content/{slug}"
