from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from sonalyze_simulation.acoustics.metrics import (
    compute_basic_metrics,
    compute_sti_best_effort,
)
from sonalyze_simulation.acoustics.pyroom import build_room
from sonalyze_simulation.schemas import (
    AcousticMetrics,
    PairResult,
    SimulationRequest,
    SimulationResponse,
)


@dataclass(frozen=True)
class _Point:
    x: float
    y: float
    z: float


def _to_point(v: list[float]) -> _Point:
    return _Point(float(v[0]), float(v[1]), float(v[2]))


def run_simulation(
    request: SimulationRequest,
    raw_furniture: list[dict[str, Any]] | None = None,
    use_raytracing: bool = False,
) -> SimulationResponse:
    """
    Run acoustic simulation.
    
    If use_raytracing is True, or if furniture is present (either in 
    request.furniture or raw_furniture), uses ray tracing mode for 
    accurate furniture modeling. Otherwise uses the faster Image Source 
    Method (ISM).
    
    Args:
        request: Simulation request with room, sources, microphones
        raw_furniture: Optional raw furniture data from frontend with rotation info
        use_raytracing: Force ray tracing mode even without furniture (experimental)
        
    Returns:
        SimulationResponse with acoustic metrics
    """
    # Check if we have furniture to model or raytracing is explicitly requested
    has_furniture = bool(request.furniture) or bool(raw_furniture)
    
    if use_raytracing or has_furniture:
        # Use ray tracing simulation for furniture support
        from sonalyze_simulation.simulate_raytracing import run_raytracing_simulation
        return run_raytracing_simulation(request, furniture_data=raw_furniture)
    
    # No furniture - use standard ISM simulation
    return _run_ism_simulation(request)


def _run_ism_simulation(request: SimulationRequest) -> SimulationResponse:
    """Run standard Image Source Method simulation (no furniture)."""
    fs = int(request.sample_rate_hz)
    room, build_warnings = build_room(
        request.room,
        fs=fs,
        max_order=int(request.max_order),
        air_absorption=bool(request.air_absorption),
    )

    # No furniture in ISM mode
    warnings: list[str] = list(build_warnings)

    sources = [(_s.id, _to_point(_s.position_m)) for _s in request.sources]
    microphones = [(_m.id, _to_point(_m.position_m)) for _m in request.microphones]

    for _, src in sources:
        room.add_source([src.x, src.y, src.z])

    mic_positions = np.array([[m.x, m.y, m.z] for _, m in microphones], dtype=float).T
    import pyroomacoustics as pra

    room.add_microphone_array(pra.MicrophoneArray(mic_positions, fs=fs))

    room.compute_rir()

    max_len = int(round(float(request.rir_duration_s) * fs))

    pair_results: list[PairResult] = []
    for mic_index, (mic_id, _) in enumerate(microphones):
        for src_index, (src_id, _) in enumerate(sources):
            rir = np.asarray(room.rir[mic_index][src_index], dtype=float)
            if max_len > 0 and rir.shape[0] > max_len:
                rir = rir[:max_len]

            warnings: list[str] = []
            basic = compute_basic_metrics(rir, fs=fs)
            sti_value, sti_method, sti_warning = compute_sti_best_effort(rir, fs=fs)
            if sti_warning:
                warnings.append(sti_warning)

            metrics = AcousticMetrics(
                rt60_s=basic.rt60_s,
                edt_s=basic.edt_s,
                d50=basic.d50,
                c50_db=basic.c50_db,
                c80_db=basic.c80_db,
                drr_db=basic.drr_db,
                sti=sti_value,
                sti_method=sti_method,
            )

            pair_results.append(
                PairResult(
                    source_id=src_id,
                    microphone_id=mic_id,
                    metrics=metrics,
                    rir=rir.tolist() if request.include_rir else None,
                    warnings=warnings,
                )
            )

    return SimulationResponse(
        sample_rate_hz=fs,
        pairs=pair_results,
        warnings=warnings,
    )
