"""Text-to-speech via edge-tts (free Microsoft neural voices, no API key).
Falls back to silence if the network is unavailable, so rendering never dies.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import edge_tts

from . import config


def synth(text: str, out_path: Path, voice: str, rate: str = config.TTS_RATE) -> Path:
    """Render `text` to an mp3 file and return its path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(_speak(text, str(out_path), voice, rate))
    except Exception as exc:  # network down -> silent placeholder
        print(f"[tts] edge-tts failed ({exc}); writing silence for: {text[:60]}")
        _write_silence(out_path, seconds=_estimate_duration(text))
    return out_path


async def _speak(text: str, path: str, voice: str, rate: str) -> None:
    tts = edge_tts.Communicate(text, voice=voice, rate=rate)
    await tts.save(path)


def _estimate_duration(text: str) -> float:
    """~165 spoken words per minute at +10% rate."""
    words = max(len(text.split()), 1)
    return round(words / 165 * 60, 2) + 0.3


def _write_silence(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "anullsrc=r=44100:mono=1",
            "-t", str(max(seconds, 0.5)), "-c:a", "libmp3lame", "-q:a", "5",
            str(path),
        ],
        check=True,
    )


def duration(path: Path) -> float:
    """Duration of an audio file in seconds (ffprobe)."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())
