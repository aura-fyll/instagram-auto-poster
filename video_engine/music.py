"""Procedural lo-fi music bed — synthesized with numpy, seeded per episode.

Royalty-free by construction (it is generated math, not sampled audio),
deterministic (same episode id -> identical bed), and costs zero Actions
minutes to download. Warm Fmaj7-Em7-Dm7-Cmaj7 pad, soft kick, tick hats,
vinyl crackle.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from scipy.io import wavfile

SR = 44100

# Fmaj7 / Em7 / Dm7 / Cmaj7 — classic lo-fi descent (Hz)
CHORDS = [
    [174.61, 220.00, 261.63, 329.63],
    [164.81, 196.00, 246.94, 293.66],
    [146.83, 174.61, 220.00, 261.63],
    [130.81, 164.81, 196.00, 246.94],
]
BAR = 3.0          # seconds per chord (80 BPM feel)


def make_bed(seconds: float, out_path: Path, seed: int) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR

    audio = np.zeros(n, dtype=np.float64)

    # --- warm pad -----------------------------------------------------------
    seg = BAR * SR
    for i in range(0, n, int(seg)):
        chord = CHORDS[(i // int(seg)) % len(CHORDS)]
        end = min(i + int(seg), n)
        local = np.arange(end - i) / SR
        env = _adsr(len(local), SR, attack=0.9, release=1.1)
        tone = np.zeros(end - i)
        for f in chord:
            # chorus: two detuned sines + a soft 2nd harmonic
            tone += np.sin(2 * np.pi * f * 1.0000 * local)
            tone += 0.85 * np.sin(2 * np.pi * f * 1.003 * local + 0.7)
            tone += 0.22 * np.sin(2 * np.pi * 2 * f * local)
        trem = 1 + 0.10 * np.sin(2 * np.pi * 0.28 * local + rng.uniform(0, 6))
        audio[i:end] += 0.16 * env * trem * tone / len(chord)

    # --- soft kick (every other beat) ---------------------------------------
    beat = 60 / 80 * 2  # every 1.5 s
    for k in range(int(seconds / beat)):
        start = int(k * beat * SR)
        ln = min(int(0.16 * SR), n - start)
        if ln <= 0:
            break
        local = np.arange(ln) / SR
        thump = np.sin(2 * np.pi * (58 * np.exp(-local * 9) + 40) * local)
        audio[start:start + ln] += 0.16 * np.exp(-local * 16) * thump

    # --- tick hats (8ths, swung, very quiet) --------------------------------
    eighth = beat / 2
    for k in range(int(seconds / eighth) + 1):
        swing = 0.06 if k % 2 == 1 else 0.0
        start = int((k * eighth + swing) * SR)
        ln = min(int(0.035 * SR), n - start)
        if ln <= 0:
            break
        local = np.arange(ln) / SR
        hat = rng.standard_normal(ln) * np.exp(-local * 190)
        audio[start:start + ln] += 0.045 * hat

    # --- vinyl crackle -------------------------------------------------------
    crackle = rng.standard_normal(n) * 0.003
    pops = rng.random(n) < (18 / SR)
    crackle += pops * rng.uniform(0.02, 0.05, n) * np.exp(-rng.random(n) * 22)
    audio += crackle

    # --- normalize + gentle master ------------------------------------------
    audio = np.tanh(audio * 1.6) * 0.72
    audio[: int(0.05 * SR)] *= np.linspace(0, 1, int(0.05 * SR))
    audio[-int(0.05 * SR):] *= np.linspace(1, 0, int(0.05 * SR))

    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    wavfile.write(out_path, SR, pcm)
    return out_path


def _adsr(n: int, sr: int, attack: float, release: float) -> np.ndarray:
    env = np.ones(n)
    a = min(int(attack * sr), n)
    r = min(int(release * sr), n)
    if a:
        env[:a] = np.linspace(0, 1, a)
    if r:
        env[-r:] *= np.linspace(1, 0, r) ** 0.7
    return env


def to_stereo_wav(src_wav: Path, dst_wav: Path) -> Path:
    """Music engine writes mono; ffmpeg upmixes for the final AAC track."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src_wav),
         "-ac", "2", "-ar", "44100", str(dst_wav)],
        check=True,
    )
    return dst_wav
