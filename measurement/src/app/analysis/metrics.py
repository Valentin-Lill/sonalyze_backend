from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal


@dataclass(frozen=True)
class DecayFit:
    method: str
    t_low_s: float
    t_high_s: float
    slope_db_per_s: float
    intercept_db: float
    rt60_s: float


def _schroeder_edc_db(ir: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    energy = ir.astype(np.float64, copy=False) ** 2
    edc = np.cumsum(energy[::-1])[::-1]
    edc = edc / max(float(edc[0]), eps)
    edc_db = 10.0 * np.log10(np.maximum(edc, eps))
    return edc_db


def _fit_decay(edc_db: np.ndarray, fs: int, low_db: float, high_db: float, label: str) -> DecayFit | None:
    # Find indices closest to given dB range (edc starts near 0 dB, goes downwards)
    if edc_db.size < 2:
        return None

    i_low = np.where(edc_db <= low_db)[0]
    i_high = np.where(edc_db <= high_db)[0]
    if i_low.size == 0 or i_high.size == 0:
        return None

    start = int(i_low[0])
    end = int(i_high[0])
    if end <= start + 4:
        return None

    t = np.arange(edc_db.size, dtype=np.float64) / float(fs)
    x = t[start:end]
    y = edc_db[start:end]

    # Linear regression y = a*x + b
    a, b = np.polyfit(x, y, deg=1)
    if a >= 0:
        return None

    # RT60 extrapolation: drop of 60 dB => time = -60/a
    rt60 = -60.0 / float(a)
    return DecayFit(method=label, t_low_s=float(x[0]), t_high_s=float(x[-1]), slope_db_per_s=float(a), intercept_db=float(b), rt60_s=float(rt60))


def rt_metrics_from_ir(ir: np.ndarray, fs: int) -> dict:
    ir = ir.astype(np.float64, copy=False)
    edc_db = _schroeder_edc_db(ir)

    edt = _fit_decay(edc_db, fs, low_db=-1.0, high_db=-10.0, label="EDT")
    t20 = _fit_decay(edc_db, fs, low_db=-5.0, high_db=-25.0, label="T20")
    t30 = _fit_decay(edc_db, fs, low_db=-5.0, high_db=-35.0, label="T30")

    out: dict = {
        "edt_s": edt.rt60_s if edt else None,
        "t20_rt60_s": t20.rt60_s if t20 else None,
        "t30_rt60_s": t30.rt60_s if t30 else None,
    }

    if t30 is not None:
        out["rt60_s"] = t30.rt60_s
    elif t20 is not None:
        out["rt60_s"] = t20.rt60_s
    else:
        out["rt60_s"] = None

    out["edc_db"] = {
        "n": int(edc_db.size),
        "min_db": float(edc_db.min(initial=0.0)),
        "max_db": float(edc_db.max(initial=0.0)),
    }

    return out


def early_late_metrics(ir: np.ndarray, fs: int, t_ms: float) -> tuple[float | None, float | None]:
    # returns (clarity_db, definition)
    if ir.size == 0:
        return None, None
    energy = ir.astype(np.float64, copy=False) ** 2
    n_early = int(round((t_ms / 1000.0) * fs))
    n_early = max(1, min(n_early, energy.size))
    e_early = float(np.sum(energy[:n_early]))
    e_total = float(np.sum(energy))
    e_late = max(e_total - e_early, 0.0)

    clarity_db = None
    if e_late > 0 and e_early > 0:
        clarity_db = 10.0 * math.log10(e_early / e_late)

    definition = None
    if e_total > 0:
        definition = e_early / e_total

    return clarity_db, definition


def clarity_definition_metrics(ir: np.ndarray, fs: int) -> dict:
    c50, d50 = early_late_metrics(ir, fs, t_ms=50.0)
    c80, _ = early_late_metrics(ir, fs, t_ms=80.0)
    return {
        "c50_db": c50,
        "c80_db": c80,
        "d50": d50,
    }


def drr_metrics(ir: np.ndarray, fs: int, direct_window_ms: float = 2.5) -> dict:
    if ir.size == 0:
        return {"drr_db": None, "direct_index": None}

    idx = int(np.argmax(np.abs(ir)))
    n_direct = int(round((direct_window_ms / 1000.0) * fs))
    start = idx
    end = min(idx + max(n_direct, 1), ir.size)

    energy = ir.astype(np.float64, copy=False) ** 2
    e_direct = float(np.sum(energy[start:end]))
    e_rest = float(np.sum(energy) - e_direct)

    drr_db = None
    if e_direct > 0 and e_rest > 0:
        drr_db = 10.0 * math.log10(e_direct / e_rest)

    return {"drr_db": drr_db, "direct_index": idx}


def snr_quality(ir: np.ndarray) -> dict:
    if ir.size < 10:
        return {"snr_db": None, "noise_floor_db": None}

    energy = ir.astype(np.float64, copy=False) ** 2
    n_tail = max(1, int(round(0.1 * energy.size)))
    noise = float(np.mean(energy[-n_tail:]))
    signal = float(np.mean(energy[: max(1, energy.size - n_tail)]))

    if noise <= 0 or signal <= 0:
        return {"snr_db": None, "noise_floor_db": None}

    snr_db = 10.0 * math.log10(signal / noise)
    noise_floor_db = 10.0 * math.log10(noise)
    return {"snr_db": snr_db, "noise_floor_db": noise_floor_db}


def freq_response_summary(ir: np.ndarray, fs: int, n_fft: int = 16384) -> dict:
    if ir.size == 0:
        return {"bands_hz": [], "magnitude_db": []}

    n_fft = int(2 ** math.ceil(math.log2(max(256, min(n_fft, max(ir.size, 256))))))
    window = signal.windows.hann(min(ir.size, n_fft), sym=False)
    x = np.zeros(n_fft, dtype=np.float64)
    x[: window.size] = ir[: window.size] * window

    spec = np.fft.rfft(x)
    mag = np.abs(spec)
    mag = mag / max(float(mag.max(initial=1e-12)), 1e-12)
    mag_db = 20.0 * np.log10(np.maximum(mag, 1e-12))

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / float(fs))

    # Return a coarse summary (log-spaced points)
    target_points = 64
    fmin = max(20.0, float(freqs[1]) if freqs.size > 1 else 20.0)
    fmax = min(20000.0, float(freqs[-1]))
    if fmax <= fmin:
        return {"bands_hz": [], "magnitude_db": []}

    bands = np.geomspace(fmin, fmax, num=target_points)
    mags = []
    for f in bands:
        idx = int(np.argmin(np.abs(freqs - f)))
        mags.append(float(mag_db[idx]))

    return {"bands_hz": [float(b) for b in bands], "magnitude_db": mags}


def deconvolve_sweep(recording: np.ndarray, sweep_ref: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    # Generic spectral deconvolution (works for linear-ish sweeps; for exponential sweeps you may want an inverse filter)
    n = int(2 ** math.ceil(math.log2(max(recording.size, sweep_ref.size, 1024))))
    y = np.fft.rfft(recording, n=n)
    x = np.fft.rfft(sweep_ref, n=n)
    h = y * np.conj(x) / (np.abs(x) ** 2 + eps)
    ir = np.fft.irfft(h, n=n)

    # Trim to plausible IR length (recording length)
    return ir[: max(1, recording.size)]


def build_display_metrics(
    rt: dict,
    clarity: dict,
    drr: dict,
    quality: dict,
    sti: dict,
) -> list[dict]:
    """
    Build a universal list of displayable metrics from analysis results.
    
    This format allows the frontend to render metrics dynamically without
    needing to know about specific metric types in advance.
    """
    metrics = []
    sort_order = 0
    
    # Reverberation metrics
    if rt.get("rt60_s") is not None:
        metrics.append({
            "key": "rt60",
            "label": "RT60",
            "value": rt["rt60_s"],
            "formatted_value": f"{rt['rt60_s']:.2f}",
            "unit": "s",
            "description": "Reverberation time (60 dB decay)",
            "icon": "timer",
            "category": "reverberation",
            "sort_order": sort_order,
        })
        sort_order += 1
    
    if rt.get("edt_s") is not None:
        metrics.append({
            "key": "edt",
            "label": "EDT",
            "value": rt["edt_s"],
            "formatted_value": f"{rt['edt_s']:.2f}",
            "unit": "s",
            "description": "Early decay time",
            "icon": "speed",
            "category": "reverberation",
            "sort_order": sort_order,
        })
        sort_order += 1
    
    # STI
    sti_value = sti.get("sti")
    if sti_value is not None:
        metrics.append({
            "key": "sti",
            "label": "STI",
            "value": sti_value,
            "formatted_value": f"{sti_value:.2f}",
            "unit": "",
            "description": "Speech transmission index",
            "icon": "record_voice_over",
            "category": "intelligibility",
            "sort_order": sort_order,
        })
        sort_order += 1
    
    # Clarity metrics
    if clarity.get("c50_db") is not None:
        metrics.append({
            "key": "c50",
            "label": "C50",
            "value": clarity["c50_db"],
            "formatted_value": f"{clarity['c50_db']:.1f}",
            "unit": "dB",
            "description": "Clarity for speech",
            "icon": "hearing",
            "category": "clarity",
            "sort_order": sort_order,
        })
        sort_order += 1
    
    if clarity.get("c80_db") is not None:
        metrics.append({
            "key": "c80",
            "label": "C80",
            "value": clarity["c80_db"],
            "formatted_value": f"{clarity['c80_db']:.1f}",
            "unit": "dB",
            "description": "Clarity for music",
            "icon": "music_note",
            "category": "clarity",
            "sort_order": sort_order,
        })
        sort_order += 1
    
    if clarity.get("d50") is not None:
        d50_pct = clarity["d50"] * 100
        metrics.append({
            "key": "d50",
            "label": "D50",
            "value": clarity["d50"],
            "formatted_value": f"{d50_pct:.0f}",
            "unit": "%",
            "description": "Definition (speech intelligibility)",
            "icon": "graphic_eq",
            "category": "clarity",
            "sort_order": sort_order,
        })
        sort_order += 1
    
    # DRR
    if drr.get("drr_db") is not None:
        metrics.append({
            "key": "drr",
            "label": "DRR",
            "value": drr["drr_db"],
            "formatted_value": f"{drr['drr_db']:.1f}",
            "unit": "dB",
            "description": "Direct-to-reverberant ratio",
            "icon": "surround_sound",
            "category": "spatial",
            "sort_order": sort_order,
        })
        sort_order += 1
    
    # Quality metrics
    if quality.get("snr_db") is not None:
        metrics.append({
            "key": "snr",
            "label": "SNR",
            "value": quality["snr_db"],
            "formatted_value": f"{quality['snr_db']:.1f}",
            "unit": "dB",
            "description": "Signal-to-noise ratio",
            "icon": "signal_cellular_alt",
            "category": "quality",
            "sort_order": sort_order,
        })
        sort_order += 1
    
    return metrics
