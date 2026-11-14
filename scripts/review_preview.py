"""Inspect existing cloud previews without rendering them again or publishing."""
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def verified_media(root, row, selection):
    name = row.get("file", "")
    if not re.fullmatch(r"preview-[1-5]\.mp4", name):
        raise ValueError("Unexpected preview filename")
    media = root / name
    if media.is_symlink() or not media.is_file():
        raise ValueError("Missing preview")
    if hashlib.sha256(media.read_bytes()).hexdigest() != row.get("sha256"):
        raise ValueError("Preview hash differs from its render manifest")
    if not any(all(row.get(k) == v for k, v in clip.items()) for clip in selection["clips"]):
        raise ValueError("Preview does not match the selected story")
    return media


def inspect(root, selection, out):
    rows = json.loads((root / "previews.json").read_text())
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
        raise ValueError("Expected one to five successfully rendered previews")
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for index, row in enumerate(rows, 1):
        media = verified_media(root, row, selection)
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media)]))
        duration = float(probe["format"]["duration"])
        times = [0, .9, duration*.2, duration*.4, duration*.7, max(0, duration-.4)]
        with TemporaryDirectory(prefix="gta-preview-frames-") as tmp:
            for n, at in enumerate(times):
                subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(media),
                                "-vf", "scale=360:640", "-frames:v", "1", f"{tmp}/frame{n}.png"], check=True)
            sheet = out / f"contact-{index}.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-framerate", "1", "-i", f"{tmp}/frame%d.png",
                            "-vf", "tile=3x2", "-frames:v", "1", "-q:v", "3", str(sheet)], check=True)
        audio = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(media),
                                "-af", "loudnorm=I=-16:TP=-2:LRA=9:print_format=json", "-f", "null", "-"],
                               check=True, capture_output=True, text=True)
        measurement = json.loads(re.search(r'\{\s*"input_i".*?\}', audio.stderr, re.S).group())
        result = dict(file=row["file"], sha256=row["sha256"], duration=duration,
                      sample_seconds=[round(t, 3) for t in times],
                      streams=[{k:s[k] for k in ("codec_type", "codec_name", "width", "height", "sample_rate", "channels") if k in s}
                               for s in probe["streams"]],
                      audio_input_measurements={k:v for k,v in measurement.items() if k.startswith("input_")},
                      review_status="contact_sheet_and_audio_levels_only_not_full_editorial_approval")
        results.append(result)
        print("QA_RESULT " + json.dumps(result), flush=True)
        # Public cleared-preview stills, not credentials or audio. Read directly
        # through cloud job logs so no video needs downloading to the workstation.
        print(f"CONTACT_SHEET_{index}_BEGIN", flush=True)
        encoded = base64.b64encode(sheet.read_bytes()).decode()
        for offset in range(0, len(encoded), 120):
            print(encoded[offset:offset+120], flush=True)
        print(f"CONTACT_SHEET_{index}_END", flush=True)
    (out / "qa.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    inspect(Path(sys.argv[1]).resolve(), json.loads(Path(sys.argv[2]).read_text()), Path(sys.argv[3]).resolve())
