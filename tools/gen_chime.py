"""Synthesize the AC Launcher signature launch chime (no external deps).

Writes assets/sounds/launch_default.wav — a short, bright A-major arpeggio
motif. Players can replace it with their own file via Settings; this is only
the shipped default.
"""
from __future__ import annotations

import math
import os
import struct
import wave

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "sounds", "launch_default.wav")
SR = 44100
AMP = 0.32  # headroom: keep below 1.0 to avoid clip when harmonics sum


def _note(freq: float, start: float, dur: float, gain: float = 1.0) -> list[tuple[float, float]]:
    """Return list of (time, sample) for one note with ADSR envelope."""
    n = int((start + dur) * SR) + 1
    out = [0.0] * n
    a = int(0.008 * SR)          # attack
    d = int(0.06 * SR)           # decay
    r = int(0.12 * SR)           # release
    s_start = start * SR
    s_end = (start + dur) * SR
    for i in range(n):
        t = i / SR
        if t < start:
            continue
        rel_pos = i - s_start
        # envelope
        if rel_pos < a:
            env = rel_pos / a
        elif i < s_end - r:
            env = 1.0 - 0.35 * ((rel_pos - a) / max(1, d)) if rel_pos < a + d else 0.65
        else:
            rem = (i - (s_end - r))
            env = 0.65 * max(0.0, 1.0 - rem / r)
        # fundamental + 2 soft harmonics (bell-ish)
        s = math.sin(2 * math.pi * freq * t)
        s += 0.4 * math.sin(2 * math.pi * freq * 2 * t)
        s += 0.18 * math.sin(2 * math.pi * freq * 3 * t)
        out[i] = s * env * gain
    return [(t, v) for t, v in enumerate(out)]


def _mix(segments):
    total = max((len(s) for s in segments), default=0)
    buf = [0.0] * total
    for seg in segments:
        for i, (_, v) in enumerate(seg):
            buf[i] += v
    return buf


# A-major ascending motif (bright, "controller" confidence)
NOTES = [
    (220.00, 0.00, 0.20, 0.9),   # A3
    (329.63, 0.16, 0.20, 0.9),   # E4
    (440.00, 0.32, 0.22, 1.0),   # A4
    (554.37, 0.50, 0.55, 1.0),   # C#5
    (659.25, 0.66, 0.70, 1.0),   # E5 (final, ringing)
]


def main():
    segs = [_note(f, s, d, g) for (f, s, d, g) in NOTES]
    buf = _mix(segs)
    peak = max((abs(v) for v in buf), default=1.0) or 1.0
    norm = min(1.0, AMP / peak) if peak > 0 else 1.0
    frames = bytearray()
    for v in buf:
        s = int(max(-1.0, min(1.0, v * norm)) * 32767)
        frames += struct.pack("<h", s)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with wave.open(OUT, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))
    dur = len(buf) / SR
    print(f"wrote {os.path.normpath(OUT)}  ({dur:.2f}s, {len(buf)} samples)")


if __name__ == "__main__":
    main()
