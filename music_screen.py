"""Look for sustained music with vocals and no spoken commentary in the exported interval."""
from collections import deque
import hashlib
import io
import re
import subprocess
from urllib.request import urlopen
from zipfile import ZipFile

RATE = 16_000
HOP = 7_680  # YAMNet's 0.48 s frame step.
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/audio_classifier/yamnet/float32/1/yamnet.tflite"
MODEL_SHA256 = "4d8b4a53282dc83ef04e3e7dbc4fbc98082e34e44ed798e16c3a0cdd4c584faf"
MUSIC_CUE = re.compile(r"[♪♫]|\[(?:music|singing|lyrics)\]|\((?:music|singing)\)", re.I)


def decode_audio(path, length, start=0):
    import numpy as np
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(path), "-t", str(length),
           "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.check_output(cmd), dtype="<f4")


def audio_activity(samples):
    import numpy as np
    # 100 ms RMS windows, including the final partial window.
    first, count = None, 0
    for offset in range(0, len(samples), RATE // 10):
        chunk = samples[offset:offset + RATE // 10]
        if np.mean(chunk * chunk) >= .01 ** 2:
            if first is None:
                first = offset / RATE
            count += len(chunk)
    return min(1.5, max(0, (first or 0) - .1)), count >= RATE // 2


class MusicScreen:
    def __init__(self):
        from ai_edge_litert.interpreter import Interpreter
        with urlopen(MODEL_URL, timeout=30) as response:
            model = response.read()
        if hashlib.sha256(model).hexdigest() != MODEL_SHA256:
            raise RuntimeError("Unexpected YAMNet model checksum")
        with ZipFile(io.BytesIO(model)) as archive:
            labels = archive.read("yamnet_label_list.txt").decode().splitlines()
        self.spoken = [labels.index(s) for s in ("Speech", "Conversation", "Narration, monologue", "Shout", "Whispering")]
        self.vocals = [labels.index(s) for s in ("Singing", "Choir", "Rapping", "Child singing", "Chant")]
        self.music = labels.index("Music")
        self.model = Interpreter(model_content=model, num_threads=2)
        self.model.allocate_tensors()
        input_tensor, = self.model.get_input_details()
        output_tensor, = self.model.get_output_details()
        self.input, self.output = input_tensor["index"], output_tensor["index"]
        self.shape = tuple(input_tensor["shape"])
        self.size = int(input_tensor["shape"][-1])

    def flagged_span(self, samples, words, cues):
        import numpy as np
        # A window represents one hop of real audio. Never count padded audio as evidence.
        recent = deque(maxlen=17)  # 8.16 seconds.
        for pos in range(0, len(samples) - HOP + 1, HOP):
            t = pos / RATE
            window = samples[pos:pos + self.size]
            if np.mean(window[:HOP] ** 2) < .01 ** 2:
                recent.clear()
                continue
            frame = np.pad(window, (0, self.size - len(window))).reshape(self.shape)
            self.model.set_tensor(self.input, frame)
            self.model.invoke()
            scores = self.model.get_tensor(self.output).reshape(-1)
            speech = max(scores[self.spoken])
            singing = max(scores[self.vocals])
            music = scores[self.music]
            end = t + HOP / RATE
            has_words = any(s < end and e > t for s, e, _ in words)
            has_cue = any(s < end and e > t for s, e in cues)
            if speech >= .5 or (has_words and speech >= .2 and speech > singing and speech > music):
                recent.clear()
                continue
            likely_lyrics = singing >= .25 or (music >= .45 and (has_words or has_cue))
            recent.append(bool(likely_lyrics))
            if len(recent) == recent.maxlen and sum(recent) >= 14:
                return (end - len(recent) * HOP / RATE, end)
        return None
