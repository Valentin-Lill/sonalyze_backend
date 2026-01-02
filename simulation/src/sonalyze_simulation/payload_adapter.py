from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class _RoomBounds:
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    height: float

    @property
    def width(self) -> float:
        return max(self.max_x - self.min_x, 0.01)

    @property
    def depth(self) -> float:
        return max(self.max_y - self.min_y, 0.01)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.min_x + self.max_x) / 2.0, (self.min_y + self.max_y) / 2.0)

    def clamp_height(self, preferred: float) -> float:
        capped = min(self.height - 0.05, max(preferred, 0.05))
        if capped <= 0:
            return max(self.height * 0.5, 0.1)
        return capped


@dataclass(frozen=True)
class _RoomConversion:
    room_spec: dict[str, Any]
    bounds: _RoomBounds
    furniture: list[dict[str, Any]]
    polygon: list[list[float]]


def normalize_simulation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize client payloads into the SimulationRequest schema."""
    if not isinstance(payload, dict):
        raise ValueError("Simulation payload must be a JSON object")

    if isinstance(payload.get("room"), dict):
        return payload

    room_model_data = _extract_room_model(payload)
    geometry = _convert_room_model(room_model_data)

    converted: dict[str, Any] = {
        "room": geometry.room_spec,
        "furniture": geometry.furniture,
        "sample_rate_hz": _coerce_int(
            payload.get("sample_rate_hz") or room_model_data.get("sample_rate_hz"),
            default=16000,
            minimum=1,
        ),
        "max_order": _coerce_int(
            payload.get("max_order") or room_model_data.get("max_order"),
            default=12,
            minimum=0,
        ),
        "air_absorption": _coerce_bool(
            payload.get("air_absorption")
            if "air_absorption" in payload
            else room_model_data.get("air_absorption"),
            default=True,
        ),
        "rir_duration_s": _coerce_float(
            payload.get("rir_duration_s") or room_model_data.get("rir_duration_s"),
            default=2.0,
            minimum=0.01,
        ),
        "include_rir": _coerce_bool(
            payload.get("include_rir")
            if "include_rir" in payload
            else room_model_data.get("include_rir"),
            default=False,
        ),
    }

    raw_sources = _extract_emitters_from_payload(
        payload,
        room_model_data,
        keys=("sources", "loudspeakers", "speakers"),
    )
    sources = _convert_emitters(raw_sources, prefix="src")
    if not sources:
        sources = [_default_source(geometry.bounds, geometry.polygon)]
    converted["sources"] = sources

    raw_microphones = _extract_emitters_from_payload(
        payload,
        room_model_data,
        keys=("microphones", "mics", "receivers", "microphone"),
    )
    microphones = _convert_emitters(raw_microphones, prefix="mic")
    if not microphones:
        microphones = [_default_microphone(geometry.bounds, geometry.polygon)]
    converted["microphones"] = microphones

    return converted


def _extract_room_model(payload: dict[str, Any]) -> dict[str, Any]:
    model = payload.get("room_model") or payload.get("roomModel")
    if model is None and isinstance(payload.get("rooms"), list):
        model = payload
    if model is None:
        raise ValueError("Missing 'room' or 'room_model' data in payload")
    return _ensure_object(model, label="room_model")


def _ensure_object(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unable to parse {label} JSON: {exc}") from exc
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"{label} must be a JSON object")


def _convert_room_model(room_model: dict[str, Any]) -> _RoomConversion:
    rooms = room_model.get("rooms")
    if not isinstance(rooms, list) or not rooms:
        raise ValueError("room_model.rooms must contain at least one room")
    room = rooms[0]
    if not isinstance(room, dict):
        raise ValueError("room_model.rooms[0] must be an object")

    dims = room.get("dimensions") if isinstance(room.get("dimensions"), dict) else {}
    width = _positive_float(dims.get("width"), fallback=4.0)
    depth = _positive_float(dims.get("depth"), fallback=4.0)
    height = _positive_float(
        dims.get("height")
        if dims else room.get("height") or room_model.get("height"),
        fallback=2.8,
    )

    segments = _collect_segments(room.get("walls"))
    polygon = _build_polygon_from_segments(segments)
    if not polygon:
        half_w = width / 2.0
        half_d = depth / 2.0
        polygon = [
            [-half_w, -half_d],
            [half_w, -half_d],
            [half_w, half_d],
            [-half_w, half_d],
        ]

    min_x = min(pt[0] for pt in polygon)
    max_x = max(pt[0] for pt in polygon)
    min_y = min(pt[1] for pt in polygon)
    max_y = max(pt[1] for pt in polygon)
    bounds = _RoomBounds(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y, height=height)

    # Extract materials from room_model or use defaults
    materials_data = room_model.get("materials") or room.get("materials") or {}
    wall_material = _extract_material_spec(materials_data.get("wall"))
    floor_material = _extract_material_spec(materials_data.get("floor"))
    ceiling_material = _extract_material_spec(materials_data.get("ceiling"))

    room_spec: dict[str, Any] = {
        "type": "polygon",
        "corners_m": polygon,
        "height_m": height,
        "wall_material": wall_material,
        "floor_material": floor_material,
        "ceiling_material": ceiling_material,
    }

    furniture = _convert_furniture_boxes(room.get("furniture"), room_height=height)
    return _RoomConversion(
        room_spec=room_spec,
        bounds=bounds,
        furniture=furniture,
        polygon=polygon,
    )


def _extract_material_spec(material_data: Any) -> dict[str, float]:
    """Extract material spec from material data (either ID or direct coefficients)."""
    from sonalyze_simulation.materials import get_material_by_id

    default_spec = {"absorption": 0.2, "scattering": 0.05}

    if material_data is None:
        return default_spec

    # If it's a string, treat it as a material ID
    if isinstance(material_data, str):
        material = get_material_by_id(material_data)
        if material:
            return {"absorption": material.absorption, "scattering": material.scattering}
        return default_spec

    # If it's a dict, check for material_id or direct coefficients
    if isinstance(material_data, dict):
        material_id = material_data.get("material_id") or material_data.get("id")
        if material_id:
            material = get_material_by_id(material_id)
            if material:
                return {"absorption": material.absorption, "scattering": material.scattering}

        # Fall back to direct coefficients if provided
        absorption = material_data.get("absorption")
        scattering = material_data.get("scattering", 0.0)
        if absorption is not None:
            return {
                "absorption": float(absorption),
                "scattering": float(scattering),
            }

    return default_spec


def _collect_segments(walls: Any) -> list[tuple[list[float], list[float]]]:
    segments: list[tuple[list[float], list[float]]] = []
    if not isinstance(walls, list):
        return segments
    for wall in walls:
        if not isinstance(wall, dict):
            continue
        start = _three_point2d(wall.get("start"))
        end = _three_point2d(wall.get("end"))
        if start and end:
            segments.append((start, end))
    return segments


def _build_polygon_from_segments(
    segments: Sequence[tuple[list[float], list[float]]]
) -> list[list[float]]:
    if not segments:
        return []

    unused = [([a[0], a[1]], [b[0], b[1]]) for a, b in segments]
    polygon: list[list[float]] = [unused[0][0][:]]
    current = unused[0][1][:]
    polygon.append(current)
    unused.pop(0)

    while unused:
        found = False
        for idx, (start, end) in enumerate(unused):
            if _points_close(start, current):
                current = end[:]
                polygon.append(current)
                unused.pop(idx)
                found = True
                break
            if _points_close(end, current):
                current = start[:]
                polygon.append(current)
                unused.pop(idx)
                found = True
                break
        if not found:
            break

    if len(polygon) >= 3 and _points_close(polygon[0], polygon[-1]):
        polygon.pop()

    cleaned: list[list[float]] = []
    for point in polygon:
        if cleaned and _points_close(cleaned[-1], point):
            continue
        cleaned.append([float(point[0]), float(point[1])])

    if len(cleaned) < 3:
        return []
    return cleaned


def _points_close(a: Sequence[float], b: Sequence[float], tol: float = 1e-3) -> bool:
    return abs(float(a[0]) - float(b[0])) <= tol and abs(float(a[1]) - float(b[1])) <= tol


def _convert_furniture_boxes(items: Any, *, room_height: float) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return boxes
    for entry in items:
        if not isinstance(entry, dict):
            continue
        dims = entry.get("dimensions")
        if not isinstance(dims, dict):
            continue
        position = _three_point3d(entry.get("position"))
        if position is None:
            continue
        width = _positive_float(dims.get("width"), fallback=0.0)
        depth = _positive_float(dims.get("depth"), fallback=0.0)
        height = _positive_float(dims.get("height"), fallback=0.0)
        if width <= 0 or depth <= 0 or height <= 0:
            continue
        min_corner = [
            position[0] - width / 2.0,
            position[1] - depth / 2.0,
            max(0.0, position[2]),
        ]
        max_corner = [
            position[0] + width / 2.0,
            position[1] + depth / 2.0,
            min(room_height, position[2] + height),
        ]
        boxes.append(
            {
                "type": "box",
                "id": entry.get("id"),
                "min_m": min_corner,
                "max_m": max_corner,
            }
        )
    return boxes


def _extract_emitters_from_payload(
    payload: Any,
    room_model: dict[str, Any],
    *,
    keys: tuple[str, ...],
) -> list[Any]:
    for container in (payload, room_model):
        entries = _collect_emitter_entries(container, keys)
        if entries:
            return entries
        entries = _collect_emitter_entries(_nested_devices(container), keys)
        if entries:
            return entries

    rooms = room_model.get("rooms")
    aggregated: list[Any] = []
    if isinstance(rooms, list):
        for room in rooms:
            if not isinstance(room, dict):
                continue
            aggregated.extend(_collect_emitter_entries(room, keys))
            aggregated.extend(_collect_emitter_entries(_nested_devices(room), keys))
    return aggregated


def _nested_devices(container: Any) -> Any:
    if isinstance(container, dict):
        return container.get("devices")
    return None


def _collect_emitter_entries(container: Any, keys: tuple[str, ...]) -> list[Any]:
    if not isinstance(container, dict):
        return []
    collected: list[Any] = []
    for key in keys:
        if key not in container:
            continue
        value = container.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            collected.extend(value)
            continue
        if isinstance(value, tuple):
            collected.extend(list(value))
            continue
        collected.append(value)
    return collected


def _convert_emitters(raw: Any, *, prefix: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    items: Iterable[Any]
    if isinstance(raw, dict):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return []

    converted: list[dict[str, Any]] = []
    for idx, entry in enumerate(items, start=1):
        coords = _coerce_position(entry)
        if coords is None:
            continue
        converted.append(
            {
                "id": str(entry.get("id")) if isinstance(entry, dict) and entry.get("id") else f"{prefix}-{idx}",
                "position_m": coords,
            }
        )
    return converted


def _coerce_position(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        if "position_m" in value:
            return _coerce_position(value["position_m"])
        if "position" in value:
            return _coerce_position(value["position"])
        system = str(value.get("coordinate_system") or value.get("coordinateSystem") or "").lower()
        if system in {"xyz", "pyroom", "cartesian"}:
            maybe = [_float_or_none(value.get("x")), _float_or_none(value.get("y")), _float_or_none(value.get("z"))]
            if None not in maybe:
                return [float(maybe[0]), float(maybe[1]), float(maybe[2])]
        if value.get("x") is not None and (value.get("z") is not None or value.get("y") is not None):
            x = float(value.get("x", 0.0))
            horizontal_y = float(value.get("z", value.get("y", 0.0)))
            vertical = float(value.get("y", value.get("height", 1.0)))
            return [x, horizontal_y, vertical]
        if {"x", "y", "z"}.issubset(value.keys()):
            return [float(value["x"]), float(value["y"]), float(value["z"])]
    elif isinstance(value, (list, tuple)):
        seq = list(value)
        if len(seq) >= 3:
            return [float(seq[0]), float(seq[1]), float(seq[2])]
        if len(seq) == 2:
            return [float(seq[0]), float(seq[1]), 1.2]
    return None


def _default_source(bounds: _RoomBounds, polygon: Sequence[Sequence[float]] | None = None) -> dict[str, Any]:
    span_x = bounds.width
    span_y = bounds.depth
    x = bounds.min_x + 0.25 * span_x
    y = bounds.min_y + 0.25 * span_y
    x, y = _snap_point_inside_polygon((x, y), polygon, bounds)
    z = bounds.clamp_height(1.5)
    return {"id": "src-default", "position_m": [x, y, z]}


def _default_microphone(bounds: _RoomBounds, polygon: Sequence[Sequence[float]] | None = None) -> dict[str, Any]:
    span_x = bounds.width
    span_y = bounds.depth
    x = bounds.max_x - 0.25 * span_x
    y = bounds.max_y - 0.25 * span_y
    x, y = _snap_point_inside_polygon((x, y), polygon, bounds)
    z = bounds.clamp_height(1.2)
    return {"id": "mic-default", "position_m": [x, y, z]}


def _snap_point_inside_polygon(
    candidate: tuple[float, float],
    polygon: Sequence[Sequence[float]] | None,
    bounds: _RoomBounds,
) -> tuple[float, float]:
    if polygon and _point_in_polygon(candidate, polygon):
        return candidate

    centroid = _polygon_centroid(polygon) if polygon else None
    if centroid and polygon and _point_in_polygon(centroid, polygon):
        dx = candidate[0] - centroid[0]
        dy = candidate[1] - centroid[1]
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return centroid
        for fraction in (1.0, 0.75, 0.5, 0.25, 0.1, 0.0):
            test = (centroid[0] + dx * fraction, centroid[1] + dy * fraction)
            if _point_in_polygon(test, polygon):
                return test
        return centroid

    return (
        _clamp_inside_bounds(candidate[0], bounds.min_x, bounds.max_x),
        _clamp_inside_bounds(candidate[1], bounds.min_y, bounds.max_y),
    )


def _clamp_inside_bounds(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return minimum
    span = maximum - minimum
    margin = max(span * 0.01, 0.01)
    lower = minimum + margin
    upper = maximum - margin
    if lower >= upper:
        return (minimum + maximum) / 2.0
    return min(max(value, lower), upper)


def _polygon_centroid(polygon: Sequence[Sequence[float]] | None) -> tuple[float, float] | None:
    if not polygon:
        return None
    area_acc = 0.0
    cx_acc = 0.0
    cy_acc = 0.0
    n = len(polygon)
    for idx in range(n):
        x0, y0 = polygon[idx]
        x1, y1 = polygon[(idx + 1) % n]
        cross = x0 * y1 - x1 * y0
        area_acc += cross
        cx_acc += (x0 + x1) * cross
        cy_acc += (y0 + y1) * cross
    area = area_acc * 0.5
    if abs(area) < 1e-9:
        sum_x = sum(pt[0] for pt in polygon)
        sum_y = sum(pt[1] for pt in polygon)
        return (sum_x / len(polygon), sum_y / len(polygon))
    return (cx_acc / (6.0 * area), cy_acc / (6.0 * area))


def _point_in_polygon(point: tuple[float, float], polygon: Sequence[Sequence[float]]) -> bool:
    x, y = point
    inside = False
    n = len(polygon)
    for idx in range(n):
        x0, y0 = polygon[idx]
        x1, y1 = polygon[(idx + 1) % n]
        if ((y0 > y) != (y1 > y)) and (y1 - y0) != 0:
            intersection_x = (x1 - x0) * (y - y0) / (y1 - y0) + x0
            if x < intersection_x:
                inside = not inside
    return inside


def _three_point2d(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        if value.get("x") is None:
            return None
        x = float(value.get("x", 0.0))
        y = float(value.get("z", value.get("y", 0.0)))
        return [x, y]
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return [float(value[0]), float(value[1])]
    return None


def _three_point3d(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        if "position" in value:
            return _three_point3d(value["position"])
        if value.get("x") is None:
            return None
        x = float(value.get("x", 0.0))
        horizontal_y = float(value.get("z", value.get("y", 0.0)))
        vertical = float(value.get("y", 0.0))
        return [x, horizontal_y, vertical]
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        # Assume already in pyroom axes
        return [float(value[0]), float(value[1]), float(value[2])]
    return None


def _positive_float(value: Any, *, fallback: float) -> float:
    number = _coerce_float(value, default=fallback, minimum=0.0)
    if number <= 0:
        return fallback
    return number


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _coerce_int(value: Any, *, default: int, minimum: int) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return default
    if integer < minimum:
        return minimum
    return integer


def _coerce_float(value: Any, *, default: float, minimum: float) -> float:
    try:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError
    except (TypeError, ValueError):
        return default
    if number < minimum:
        return minimum
    return number


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
