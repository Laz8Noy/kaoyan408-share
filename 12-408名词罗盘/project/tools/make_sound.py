# -*- coding: utf-8 -*-
"""Synthesize a soft click: short filtered noise burst, tiny WAV."""
import math
import random
import struct
import wave
from pathlib import Path

SR = 22050
OUT = Path(__file__).resolve().parent.parent / "public" / "sounds" / "click-soft.wav"
OUT.parent.mkdir(parents=True, exist_ok=True)

frames = []
n = int(SR * 0.055)
prev = 0.0
for i in range(n):
    t = i / SR
    env = math.exp(-t * 120)
    noise = (random.random() * 2 - 1)
    # one-pole low-pass for softness
    prev = prev + 0.22 * (noise - prev)
    body = math.sin(2 * math.pi * 920 * t) * 0.35
    s = (prev * 0.9 + body) * env * 0.55
    frames.append(max(-1, min(1, s)))

with wave.open(str(OUT), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(struct.pack("<h", int(f * 32767)) for f in frames))
print("wrote", OUT, OUT.stat().st_size, "bytes")
