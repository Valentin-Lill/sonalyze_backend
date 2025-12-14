from __future__ import annotations

import numpy as np
import soundfile as sf


def read_audio_mono(path: str) -> tuple[np.ndarray, int]:
    data, samplerate = sf.read(path, always_2d=True)
    # downmix to mono
    mono = data.mean(axis=1).astype(np.float64, copy=False)
    return mono, int(samplerate)


def normalize_peak(signal: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak < eps:
        return signal
    return signal / peak
