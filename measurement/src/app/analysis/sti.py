from __future__ import annotations

import numpy as np
from scipy import signal


_OCTAVE_BANDS_HZ: list[tuple[float, float, float]] = [
    # (center, low, high)
    (125.0, 88.4, 176.8),
    (250.0, 176.8, 353.6),
    (500.0, 353.6, 707.1),
    (1000.0, 707.1, 1414.2),
    (2000.0, 1414.2, 2828.4),
    (4000.0, 2828.4, 5656.9),
    (8000.0, 5656.9, 11313.7),
]

# Modulation frequencies (Hz) commonly used for STI/MTF calculations
_MOD_FREQS_HZ = np.array([0.63, 0.8, 1.0, 1.25, 1.6, 2.0, 2.5, 3.15, 4.0, 5.0, 6.3, 8.0, 10.0, 12.5])

# Default octave-band weights for a simple STI aggregation.
# This is a pragmatic default (can be overridden later).
_DEFAULT_BAND_WEIGHTS = np.array([0.13, 0.14, 0.11, 0.12, 0.12, 0.11, 0.10], dtype=np.float64)


def _bandpass_octave(x: np.ndarray, fs: int, f_lo: float, f_hi: float) -> np.ndarray:
    nyq = 0.5 * fs
    lo = max(1.0, f_lo) / nyq
    hi = min(nyq - 1.0, f_hi) / nyq
    if hi <= lo or lo >= 1.0:
        return np.zeros_like(x)

    b, a = signal.butter(4, [lo, hi], btype="band")
    return signal.lfilter(b, a, x)


def sti_from_impulse_response(ir: np.ndarray, fs: int) -> dict:
    """Compute a simplified STI estimate from an impulse response.

    Uses an MTF-like approach on band-passed IR energy (h^2).
    This is not a full IEC 60268-16 implementation, but it provides a useful proxy.
    """

    if ir.size < fs // 20:  # < 50ms
        return {"sti": None, "note": "IR too short for STI"}

    ir = ir.astype(np.float64, copy=False)
    h2 = ir**2
    total_h2 = float(np.sum(h2))
    if total_h2 <= 0:
        return {"sti": None, "note": "Zero-energy IR"}

    band_tis: list[float] = []
    band_mtfs: list[list[float]] = []

    for (center, f_lo, f_hi), w in zip(_OCTAVE_BANDS_HZ, _DEFAULT_BAND_WEIGHTS, strict=False):
        band = _bandpass_octave(ir, fs, f_lo, f_hi)
        e = band.astype(np.float64, copy=False) ** 2
        e_sum = float(np.sum(e))
        if e_sum <= 0:
            band_tis.append(0.0)
            band_mtfs.append([0.0 for _ in _MOD_FREQS_HZ])
            continue

        t = np.arange(e.size, dtype=np.float64) / float(fs)
        # MTF of energy envelope
        mtf_vals = []
        ti_vals = []
        for fm in _MOD_FREQS_HZ:
            c = np.sum(e * np.cos(2.0 * np.pi * fm * t))
            s = np.sum(e * np.sin(2.0 * np.pi * fm * t))
            m = float(np.sqrt(c * c + s * s) / e_sum)
            m = min(max(m, 0.0), 0.999999)

            # Convert to apparent SNR then TI
            snr = 10.0 * np.log10((m * m) / (1.0 - m * m))
            ti = float(np.clip((snr + 15.0) / 30.0, 0.0, 1.0))

            mtf_vals.append(m)
            ti_vals.append(ti)

        band_mtfs.append(mtf_vals)
        band_tis.append(float(np.mean(ti_vals)))

    weights = _DEFAULT_BAND_WEIGHTS[: len(band_tis)]
    weights = weights / float(np.sum(weights)) if float(np.sum(weights)) > 0 else weights

    sti = float(np.sum(weights * np.array(band_tis, dtype=np.float64))) if band_tis else None

    return {
        "sti": sti,
        "bands_hz": [c for (c, _, _) in _OCTAVE_BANDS_HZ[: len(band_tis)]],
        "band_ti": band_tis,
        "mod_freqs_hz": [float(x) for x in _MOD_FREQS_HZ],
    }
