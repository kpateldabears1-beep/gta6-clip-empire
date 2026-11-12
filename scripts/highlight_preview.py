"""Cut a GTA V freeway stunt for editorial review. All media lives on the runner."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import probe, stamp
from soundtrack import TRACKS, music_mix


def ff(*args, cwd):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *map(str, args)], cwd=cwd, check=True)


def shot(raw, work, index, start, span, speed, height, center):
    # Center is a pair of positions in the original frame. Pan with the vehicle.
    (x0, y0), (x1, y1) = center
    motion = f"clip(t/{span},0,1)"
    x = f"iw*({x0}+({x1}-{x0})*{motion})-ow/2"
    y = f"ih*({y0}+({y1}-{y0})*{motion})-oh/2"
    crop = f"crop=w=trunc(ih*{height}*9/16/2)*2:h=trunc(ih*{height}/2)*2:x='{x}':y='{y}'"
    vf = f"setpts=PTS-STARTPTS,{crop},scale=1080:1920,setsar=1,setpts=PTS/{speed},fps=30"
    name = f"shot-{index}.mp4"
    ff("-ss", start, "-t", span, "-i", raw, "-map", "0:v:0", "-an", "-vf", vf,
       "-c:v", "libx264", "-threads", 2, "-preset", "veryfast", "-crf", 18, "-pix_fmt", "yuv420p", name, cwd=work)
    return name


def overlay(work, events, length):
    text = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,72,&H00FFFFFF,&H00FFFFFF,&H0023180F,&H5023180F,-1,0,0,0,100,100,0,0,1,5,2,8,50,80,185,1
Style: Credit,DejaVu Sans,36,&H00FFFFFF,&H00FFFFFF,&H0023180F,&H5023180F,0,0,0,0,100,100,0,0,1,3,1,1,40,90,180,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    for begin, end, style, words in [(0, length, "Credit", "Footage: Unlisted Thoughts"), *events]:
        text += f"Dialogue: 0,{stamp(begin)},{stamp(end)},{style},,0,0,0,,{words}\n"
    (work/"titles.ass").write_text(text)


def main(raw, output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        work = Path(temp)
        # Original timestamps and framing were selected from the half-second contact sheets.
        cuts = [
            (100.7, 2.65, 1, .72, ((.157,.60),(.254,.37))),
            (104.3, 2.15, 1, .76, ((.162,.66),(.165,.42))),
            (106.45, 3, .92, .69, ((.167,.40),(.455,.45))),
            (109.45, 2.25, 1, .68, ((.455,.45),(.390,.46))),
            (139.8, 4.20, 1, .63, ((.344,.46),(.344,.46))),
            (140.95, 2.40, .57, .38, ((.342,.46),(.342,.46))),
        ]
        files = [shot(raw, work, i, *cut) for i, cut in enumerate(cuts)]
        lengths = [float(probe(work/f)["streams"][0]["duration"]) for f in files]
        bounds = [0.]
        for duration in lengths:
            bounds.append(bounds[-1] + duration)
        duration = bounds[-1]
        if not 18 <= duration < 44:
            raise ValueError(f"Invalid pilot length: {duration:.2f}s")
        events = [(0, bounds[1], "Hook", "One blocked exit."),
                  (bounds[1], bounds[2]+.15, "Hook", "White car's turn."),
                  (bounds[3]+.35, bounds[4]-.15, "Hook", "Made it down."),
                  (bounds[4], bounds[4]+1.55, "Hook", "30 seconds later..."),
                  (bounds[5], bounds[5]+2.1, "Hook", "REPLAY  /  0.57×")]
        overlay(work, events, duration)
        (work/"order.txt").write_text("".join(f"file '{f}'\n" for f in files))
        hit = round((bounds[4]+1.95)*1000)
        repeat = round((bounds[5]+1.4)*1000)
        # Original low hits and a short noise burst accent the two views of the blast.
        effects = (f"sine=f=63:d=0.34,afade=t=out:d=.34,adelay={hit}[kick];"
                   f"anoisesrc=c=pink:r=44100:d=0.36:a=.35,lowpass=f=2400,afade=t=out:d=.36,adelay={hit}[debris];"
                   f"sine=f=76:d=0.23,afade=t=out:d=.23,adelay={repeat}[replay];"
                   "[kick][debris][replay]amix=inputs=3:normalize=0,apad[a]").replace("d=.", "d=0.")
        final = output/"wrong-exit-gta5.mp4"
        ff("-f", "concat", "-safe", 0, "-i", "order.txt", "-filter_complex", effects, "-map", "0:v:0",
           "-map", "[a]", "-vf", "ass=titles.ass", "-t", f"{duration:.3f}", "-c:v", "libx264", "-threads", 2,
           "-preset", "veryfast", "-crf", 20, "-pix_fmt", "yuv420p", "-ar", 44100, "-ac", 2, "-c:a", "aac",
           final, cwd=work)
        credit = music_mix(final, TRACKS[0], preserve_audio=True)
        info = probe(final)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        if (video["width"], video["height"]) != (1080,1920):
            raise ValueError("Unexpected frame size")
        ff("-xerror", "-i", final, "-f", "null", "-", cwd=work)
        (output/"credits.txt").write_text("Footage: Unlisted Thoughts, CC0. https://archive.org/details/ut-gtav-b-roll\nMusic: " + credit + "\n")
        print(json.dumps({"duration": duration, "edit_points": bounds, "music": credit}))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
