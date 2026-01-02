"""
Ray tracing based room simulation with full furniture support.

This module provides an alternative simulation runner that uses ray tracing
instead of pure ISM, allowing furniture to affect the acoustic simulation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sonalyze_simulation.acoustics.metrics import (
    compute_basic_metrics,
    compute_sti_best_effort,
)
from sonalyze_simulation.acoustics.raytracing import (
    add_furniture_to_room,
    build_room_with_raytracing,
    convert_frontend_furniture_to_boxes,
    create_furniture_walls_with_rotation,
)
from sonalyze_simulation.schemas import (
    AcousticMetrics,
    FurnitureBoxSpec,
    PairResult,
    PolygonRoomSpec,
    RoomSpec,
    ShoeboxRoomSpec,
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


def _pra_material(absorption: float, scattering: float):
    """Create a pyroomacoustics Material object."""
    import pyroomacoustics as pra
    return pra.Material(energy_absorption=float(absorption), scattering=float(scattering))


def run_raytracing_simulation(
    request: SimulationRequest,
    furniture_data: list[dict] | None = None,
) -> SimulationResponse:
    """
    Run acoustic simulation using ray tracing with furniture support.
    
    This is an alternative to run_simulation() that uses ray tracing mode
    to properly model furniture as reflective surfaces.
    
    Args:
        request: Simulation request with room, sources, microphones
        furniture_data: Optional raw furniture data from frontend.
                       If provided, this will be converted and used.
                       If None, request.furniture boxes are used directly.
                       
    Returns:
        SimulationResponse with acoustic metrics for each source-mic pair
    """
    import pyroomacoustics as pra
    
    fs = int(request.sample_rate_hz)
    # Use lower max_order for ray tracing (recommended: 3)
    max_order = min(int(request.max_order), 5)
    
    warnings: list[str] = []
    
    # Get room height for furniture clamping
    if isinstance(request.room, ShoeboxRoomSpec):
        room_height = request.room.dimensions_m[2]
    elif isinstance(request.room, PolygonRoomSpec):
        room_height = request.room.height_m
    else:
        room_height = 3.0
    
    # Build room with ray tracing enabled
    room, build_warnings = build_room_with_raytracing(
        request.room,
        furniture=[],  # We'll add furniture separately for more control
        fs=fs,
        max_order=max_order,
        air_absorption=bool(request.air_absorption),
    )
    warnings.extend(build_warnings)
    
    # Add furniture from either frontend data or request.furniture
    furniture_count = 0
    
    if furniture_data:
        # Convert and add frontend furniture with rotation support
        walls = create_furniture_walls_with_rotation(furniture_data, room_height)
        for wall in walls:
            room.walls.append(wall)
        furniture_count = len(walls) // 5
        
        if furniture_count > 0:
            warnings.append(
                f"Ray tracing: Added {furniture_count} furniture items "
                f"({len(walls)} wall surfaces) with proper rotation."
            )
    elif request.furniture:
        # Use box specs directly from request
        from sonalyze_simulation.acoustics.raytracing import create_box_walls, get_furniture_material
        
        for item in request.furniture:
            if item.type != "box":
                continue
            
            # Determine material
            if item.material:
                absorption = item.material.absorption
                scattering = item.material.scattering
            else:
                mat = get_furniture_material("default")
                absorption = mat.absorption
                scattering = mat.scattering
            
            name = item.id or f"furniture_{furniture_count}"
            box_walls = create_box_walls(
                item.min_m,
                item.max_m,
                absorption,
                scattering,
                name,
                include_bottom=False,
            )
            
            for wall in box_walls:
                room.walls.append(wall)
            furniture_count += 1
        
        if furniture_count > 0:
            warnings.append(
                f"Ray tracing: Added {furniture_count} furniture boxes "
                f"({furniture_count * 5} wall surfaces)."
            )
    
    # Add sources
    sources = [(_s.id, _to_point(_s.position_m)) for _s in request.sources]
    for _, src in sources:
        room.add_source([src.x, src.y, src.z])
    
    # Add microphones
    microphones = [(_m.id, _to_point(_m.position_m)) for _m in request.microphones]
    mic_positions = np.array([[m.x, m.y, m.z] for _, m in microphones], dtype=float).T
    room.add_microphone_array(pra.MicrophoneArray(mic_positions, fs=fs))
    
    # Compute RIR
    room.compute_rir()
    
    # Process results
    max_len = int(round(float(request.rir_duration_s) * fs))
    
    pair_results: list[PairResult] = []
    for mic_index, (mic_id, _) in enumerate(microphones):
        for src_index, (src_id, _) in enumerate(sources):
            rir = np.asarray(room.rir[mic_index][src_index], dtype=float)
            if max_len > 0 and rir.shape[0] > max_len:
                rir = rir[:max_len]
            
            pair_warnings: list[str] = []
            basic = compute_basic_metrics(rir, fs=fs)
            sti_value, sti_method, sti_warning = compute_sti_best_effort(rir, fs=fs)
            if sti_warning:
                pair_warnings.append(sti_warning)
            
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
                    warnings=pair_warnings,
                )
            )
    
    return SimulationResponse(
        sample_rate_hz=fs,
        pairs=pair_results,
        warnings=warnings,
    )
