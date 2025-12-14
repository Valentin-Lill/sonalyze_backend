from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BasicMetrics:
    rt60_s: float | None
    edt_s: float | None
    d50: float | None
    c50_db: float | None
    c80_db: float | None
    drr_db: float | None


def _safe_db(x: float) -> float:
    return float(10.0 * np.log10(max(x, 1e-20)))


def _schroeder_edc_db(ir: np.ndarray) -> np.ndarray:
    energy = np.square(ir.astype(float))
    edc = np.cumsum(energy[::-1])[::-1]
    if not np.isfinite(edc).all() or edc[0] <= 0:
        return np.full_like(edc, fill_value=np.nan, dtype=float)
    edc /= edc[0]
    return 10.0 * np.log10(np.maximum(edc, 1e-20))


def _linear_rt_from_range(edc_db: np.ndarray, fs: int, db_hi: float, db_lo: float) -> float | None:
    if edc_db.size < 8 or not np.isfinite(edc_db).any():
        return None

    idx = np.where((edc_db <= db_hi) & (edc_db >= db_lo))[0]
    if idx.size < 8:
        return None

    t = idx.astype(float) / float(fs)
    y = edc_db[idx].astype(float)

    slope, intercept = np.polyfit(t, y, deg=1)
    if not np.isfinite(slope) or slope >= 0:
        return None

    return float(-60.0 / slope)


def compute_rt60(ir: np.ndarray, fs: int) -> float | None:
    if ir.size == 0:
        return None

    peak = int(np.argmax(np.abs(ir)))
    tail = ir[peak:]
    edc_db = _schroeder_edc_db(tail)

    # Prefer T30 if possible (-5..-35 dB), else T20 (-5..-25 dB)
    rt60 = _linear_rt_from_range(edc_db, fs=fs, db_hi=-5.0, db_lo=-35.0)
    if rt60 is None:
        rt60 = _linear_rt_from_range(edc_db, fs=fs, db_hi=-5.0, db_lo=-25.0)
    return rt60


def compute_edt(ir: np.ndarray, fs: int) -> float | None:
    if ir.size == 0:
        return None

    peak = int(np.argmax(np.abs(ir)))
    tail = ir[peak:]
    edc_db = _schroeder_edc_db(tail)

    # EDT based on -0..-10 dB region, extrapolated to 60 dB
    rt60 = _linear_rt_from_range(edc_db, fs=fs, db_hi=0.0, db_lo=-10.0)
    return rt60


def compute_dxx(ir: np.ndarray, fs: int, early_ms: float) -> float | None:
    if ir.size == 0:
        return None

    peak = int(np.argmax(np.abs(ir)))
    ir = ir[peak:]

    early_n = int(round((early_ms / 1000.0) * fs))
    early_n = max(1, min(early_n, ir.size))

    e_total = float(np.sum(np.square(ir)))
    if e_total <= 0 or not np.isfinite(e_total):
        return None

    e_early = float(np.sum(np.square(ir[:early_n])))
    return float(e_early / e_total)


def compute_cxx_db(ir: np.ndarray, fs: int, early_ms: float) -> float | None:
    if ir.size == 0:
        return None

    peak = int(np.argmax(np.abs(ir)))
    ir = ir[peak:]

    early_n = int(round((early_ms / 1000.0) * fs))
    early_n = max(1, min(early_n, ir.size))

    e_early = float(np.sum(np.square(ir[:early_n])))
    e_late = float(np.sum(np.square(ir[early_n:])))
    if e_early <= 0 or not np.isfinite(e_early) or not np.isfinite(e_late):
        return None

    return _safe_db(e_early / max(e_late, 1e-20))


def compute_drr_db(ir: np.ndarray, fs: int, direct_ms: float = 2.5) -> float | None:
    if ir.size == 0:
        return None

    peak = int(np.argmax(np.abs(ir)))
    ir = ir[peak:]

    n_direct = int(round((direct_ms / 1000.0) * fs))
    n_direct = max(1, min(n_direct, ir.size))

    e_direct = float(np.sum(np.square(ir[:n_direct])))
    e_reverb = float(np.sum(np.square(ir[n_direct:])))

    if e_direct <= 0 or not np.isfinite(e_direct) or not np.isfinite(e_reverb):
        return None

    return _safe_db(e_direct / max(e_reverb, 1e-20))


def compute_basic_metrics(ir: np.ndarray, fs: int) -> BasicMetrics:
    return BasicMetrics(
        rt60_s=compute_rt60(ir, fs=fs),
        edt_s=compute_edt(ir, fs=fs),
        d50=compute_dxx(ir, fs=fs, early_ms=50.0),
        c50_db=compute_cxx_db(ir, fs=fs, early_ms=50.0),
        c80_db=compute_cxx_db(ir, fs=fs, early_ms=80.0),
        drr_db=compute_drr_db(ir, fs=fs),
    )


def compute_sti_best_effort(ir: np.ndarray, fs: int) -> tuple[float | None, str | None, str | None]:
    """Best-effort STI.

    STI is non-trivial to compute correctly (band filtering, modulation frequencies, noise).
    If pyroomacoustics exposes an STI helper in your installed version, we use it.
    Otherwise we return null with a warning.
    """

    try:
        import pyroomacoustics as pra

        sti_fn = None
        if hasattr(pra, "acoustics") and hasattr(pra.acoustics, "sti"):
            sti_fn = pra.acoustics.sti
        elif hasattr(pra, "sti"):
            sti_fn = pra.sti

        if sti_fn is None:
            return None, None, "STI not available (no STI function found in pyroomacoustics)."

        value = float(sti_fn(ir, fs))
        if not np.isfinite(value):
            return None, "pyroomacoustics", "STI computation returned non-finite value."

        return value, "pyroomacoustics", None

    except Exception as exc:  # noqa: BLE001
        return None, None, f"STI computation failed: {type(exc).__name__}: {exc}"
