"""Cheap editorial signals; these rank candidates, not predict views or earnings."""
import re


def reaction_peaks(samples, rate=16000):
    energies = []
    hop = rate // 2
    for start in range(0, len(samples) - hop + 1, hop):
        frame = samples[start:start+hop]
        energies.append(float(sum(frame * frame) / len(frame)) if hasattr(frame, "dtype")
                        else sum(float(x)**2 for x in frame) / len(frame))
    if not energies:
        return []
    baseline = sorted(energies)[len(energies)//2]
    peaks = []
    for index, energy in enumerate(energies):
        second = index * .5
        if energy > max(.02**2, baseline * 4) and (not peaks or second - peaks[-1] >= 2):
            peaks.append(second)
    return peaks[:6]


def opening_quality(words):
    if not words:
        return -2
    opening = " ".join(w for _,_,w in words[:5]).lower()
    penalty = 2 if re.match(r"^(um|uh|so yeah|anyway|as i was saying)\b", opening) else 0
    return (1 if words[0][0] <= 1 else -1) - penalty
