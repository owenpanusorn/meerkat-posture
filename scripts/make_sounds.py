"""Synthesize Meerkat's alert sounds into ``assets/sounds/``.

Generated from scratch with numpy (no samples, no third-party audio), so they are
covered by the project's MIT license. Run after tweaking:

    uv run python scripts/make_sounds.py

- posture.wav: two quick, soft chirps ("hey, posture")
- break.wav:   three rising chirps, a little longer ("time to stand up")
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "sounds"


def chirp(f0: float, f1: float, dur: float, volume: float) -> np.ndarray:
    """A short upward sweep with a soft attack/decay, like a small animal's call."""
    n = int(RATE * dur)
    t = np.arange(n) / RATE
    freq = f0 + (f1 - f0) * (t / dur) ** 0.7
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    tone = np.sin(phase) + 0.25 * np.sin(2 * phase) + 0.08 * np.sin(3 * phase)
    attack = np.minimum(1.0, t / 0.008)
    decay = np.exp(-4.0 * t / dur)
    return volume * tone * attack * decay / 1.33


def silence(dur: float) -> np.ndarray:
    return np.zeros(int(RATE * dur))


def posture() -> np.ndarray:
    return np.concatenate(
        [
            chirp(1700, 2500, 0.07, 0.35),
            silence(0.06),
            chirp(1800, 2700, 0.08, 0.35),
            silence(0.05),
        ]
    )


def stand_up() -> np.ndarray:
    return np.concatenate(
        [
            chirp(1300, 1900, 0.09, 0.4),
            silence(0.07),
            chirp(1600, 2300, 0.09, 0.4),
            silence(0.07),
            chirp(1900, 2900, 0.14, 0.45),
            silence(0.05),
        ]
    )


def write(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, samples in (("posture.wav", posture()), ("break.wav", stand_up())):
        path = OUT_DIR / name
        write(path, samples)
        print(f"wrote {path} ({len(samples) / RATE:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
