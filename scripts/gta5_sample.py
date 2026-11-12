"""Render one credited GTA V sample from Unlisted Thoughts' CC0 B-roll set."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import probe, render, seconds


def main(root):
    source = root / "freeway.mp4"
    # Replace the entire source soundtrack with three original, timed impact cues.
    cues = [f"sine=frequency={freq}:duration=0.3,afade=t=out:d=0.3,adelay={delay}[a{i}]"
            for i, (freq, delay) in enumerate([(185, 2400), (225, 11500), (270, 16400)])]
    audio = ";".join(cues + ["[a0][a1][a2]amix=inputs=3:normalize=0,apad[a]"])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "34", "-i", str(root / "original.mp4"),
                    "-filter_complex", audio, "-map", "0:v:0", "-map", "[a]", "-t", "26",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "aac",
                    str(source)], check=True)
    notes = [
        (0, 4.5, "Follow the first trailer. Its nose goes almost vertical."),
        (4.5, 10, "The ramp stays put. The next truck has a clear run."),
        (10, 14.5, "The orange tanker stays much flatter."),
        (14.5, 19.5, "Now watch the red truck clear the ramp in one piece."),
        (19.5, 26, "Back on four wheels. Traffic just keeps going."),
    ]
    out = root / "gta5-freeway.mp4"
    render(source, out, 26, [], "Three trucks. One GTA V ramp.", "Unlisted Thoughts",
           notes=[{"start": s, "end": e, "text": t} for s, e, t in notes])
    video = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
    if (video["width"], video["height"]) != (1080, 1920) or not 25.9 <= seconds(out) <= 26.2:
        raise ValueError("Unexpected sample dimensions or duration")
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(out), "-f", "null", "-"], check=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
