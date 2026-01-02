"""
Ray tracing room simulation with furniture support.

This module provides ray tracing-based acoustic simulation that includes
furniture as reflective surfaces. Unlike the ISM (Image Source Method),
ray tracing can model arbitrary wall surfaces including furniture items.

Furniture is modeled as 5-sided boxes (no bottom face since they sit on floor):
- 4 vertical side walls
- 1 top horizontal surface

Each furniture type has specific acoustic properties (absorption, scattering)
based on typical materials.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from sonalyze_simulation.schemas import (
    FurnitureBoxSpec,
    MaterialSpec,
    PolygonRoomSpec,
    RoomSpec,
    ShoeboxRoomSpec,
)


@dataclass(frozen=True)
class FurnitureMaterial:
    """Acoustic properties for a furniture type."""
    absorption: float  # 0.0 - 1.0
    scattering: float  # 0.0 - 1.0
    description: str


# Acoustic material properties for each furniture type
# Based on typical materials: wood, fabric, metal, ceramic, glass
FURNITURE_MATERIALS: dict[str, FurnitureMaterial] = {
    # Wooden furniture - moderate absorption, low scattering
    "table": FurnitureMaterial(0.10, 0.10, "Wood surface"),
    "desk": FurnitureMaterial(0.10, 0.10, "Wood surface"),
    "chair": FurnitureMaterial(0.15, 0.15, "Wood/plastic with some fabric"),
    "shelf": FurnitureMaterial(0.12, 0.20, "Wood with items causing scattering"),
    "wardrobe": FurnitureMaterial(0.10, 0.08, "Large flat wood surface"),
    
    # Upholstered furniture - high absorption, moderate scattering
    "sofa": FurnitureMaterial(0.40, 0.25, "Fabric upholstery"),
    "bed": FurnitureMaterial(0.50, 0.30, "Mattress and bedding"),
    
    # Bathroom fixtures - low absorption (ceramic/metal), low scattering
    "bathtub": FurnitureMaterial(0.03, 0.05, "Ceramic/acrylic"),
    "toilet": FurnitureMaterial(0.03, 0.05, "Ceramic"),
    "sink": FurnitureMaterial(0.03, 0.05, "Ceramic/metal"),
    "shower": FurnitureMaterial(0.05, 0.10, "Glass/tile enclosure"),
    
    # Kitchen appliances - very low absorption (metal), low scattering
    "stove": FurnitureMaterial(0.02, 0.05, "Metal surface"),
    "fridge": FurnitureMaterial(0.02, 0.03, "Large metal surface"),
    
    # Default for unknown types
    "default": FurnitureMaterial(0.15, 0.10, "Generic furniture"),
}


def get_furniture_material(furniture_type: str) -> FurnitureMaterial:
    """Get acoustic material properties for a furniture type."""
    return FURNITURE_MATERIALS.get(
        furniture_type.lower(),
        FURNITURE_MATERIALS["default"]
    )


def _create_wall(
    corners: np.ndarray,
    absorption: float,
    scattering: float,
    name: str,
):
    """
    Create a pyroomacoustics Wall object.
    
    Args:
        corners: 3xN array of corner coordinates (float32)
        absorption: Absorption coefficient (0-1)
        scattering: Scattering coefficient (0-1)
        name: Wall identifier
        
    Returns:
        pra.Wall object
    """
    import pyroomacoustics as pra
    
    corners_f32 = np.asarray(corners, dtype=np.float32)
    abs_coef = np.array([[absorption]], dtype=np.float32)
    scat_coef = np.array([[scattering]], dtype=np.float32)
    
    return pra.Wall(corners_f32, abs_coef, scat_coef, name)


def create_box_walls(
    min_corner: list[float],
    max_corner: list[float],
    absorption: float,
    scattering: float,
    name_prefix: str,
    include_bottom: bool = False,
) -> list[Any]:
    """
    Create wall surfaces for a 3D box (furniture item).
    
    The box is defined by min and max corners in [x, y, z] format.
    Creates 5 walls by default (4 sides + top), optionally 6 with bottom.
    
    Coordinate system (pyroomacoustics):
    - X: left-right
    - Y: front-back  
    - Z: floor-ceiling (vertical)
    
    Args:
        min_corner: [x_min, y_min, z_min] in meters
        max_corner: [x_max, y_max, z_max] in meters
        absorption: Absorption coefficient
        scattering: Scattering coefficient
        name_prefix: Prefix for wall names
        include_bottom: Whether to include bottom face
        
    Returns:
        List of pra.Wall objects
    """
    x0, y0, z0 = min_corner
    x1, y1, z1 = max_corner
    
    walls = []
    
    # Front face (x = x0, facing -x direction)
    # Corners go counterclockwise when viewed from outside
    walls.append(_create_wall(
        np.array([
            [x0, x0, x0, x0],  # x
            [y0, y1, y1, y0],  # y
            [z0, z0, z1, z1],  # z
        ]),
        absorption, scattering, f"{name_prefix}_front"
    ))
    
    # Back face (x = x1, facing +x direction)
    walls.append(_create_wall(
        np.array([
            [x1, x1, x1, x1],  # x
            [y0, y1, y1, y0],  # y
            [z0, z0, z1, z1],  # z
        ]),
        absorption, scattering, f"{name_prefix}_back"
    ))
    
    # Left face (y = y0, facing -y direction)
    walls.append(_create_wall(
        np.array([
            [x0, x1, x1, x0],  # x
            [y0, y0, y0, y0],  # y
            [z0, z0, z1, z1],  # z
        ]),
        absorption, scattering, f"{name_prefix}_left"
    ))
    
    # Right face (y = y1, facing +y direction)
    walls.append(_create_wall(
        np.array([
            [x0, x1, x1, x0],  # x
            [y1, y1, y1, y1],  # y
            [z0, z0, z1, z1],  # z
        ]),
        absorption, scattering, f"{name_prefix}_right"
    ))
    
    # Top face (z = z1, facing +z direction)
    walls.append(_create_wall(
        np.array([
            [x0, x1, x1, x0],  # x
            [y0, y0, y1, y1],  # y
            [z1, z1, z1, z1],  # z
        ]),
        absorption, scattering, f"{name_prefix}_top"
    ))
    
    # Bottom face (optional, z = z0, facing -z direction)
    if include_bottom:
        walls.append(_create_wall(
            np.array([
                [x0, x1, x1, x0],  # x
                [y0, y0, y1, y1],  # y
                [z0, z0, z0, z0],  # z
            ]),
            absorption, scattering, f"{name_prefix}_bottom"
        ))
    
    return walls


def create_rotated_box_walls(
    center: list[float],
    dimensions: list[float],
    rotation_y: float,
    absorption: float,
    scattering: float,
    name_prefix: str,
    z_offset: float = 0.0,
) -> list[Any]:
    """
    Create wall surfaces for a rotated 3D box.
    
    This handles furniture that has been rotated in the room editor.
    Rotation is around the vertical (Z) axis.
    
    Args:
        center: [x, y] center position in meters (z is calculated from z_offset)
        dimensions: [width, depth, height] in meters
        rotation_y: Rotation angle in radians around vertical axis
        absorption: Absorption coefficient
        scattering: Scattering coefficient
        name_prefix: Prefix for wall names
        z_offset: Bottom Z coordinate (usually 0 for floor-standing)
        
    Returns:
        List of pra.Wall objects
    """
    cx, cy = center[0], center[1]
    w, d, h = dimensions
    hw, hd = w / 2, d / 2
    
    # Define corners in local space (centered at origin)
    # Before rotation: front-left, front-right, back-right, back-left
    local_corners = np.array([
        [-hw, -hd],
        [hw, -hd],
        [hw, hd],
        [-hw, hd],
    ])
    
    # Rotation matrix for Y-axis rotation (in XY plane since Z is up)
    cos_r = math.cos(rotation_y)
    sin_r = math.sin(rotation_y)
    rot_matrix = np.array([
        [cos_r, -sin_r],
        [sin_r, cos_r],
    ])
    
    # Rotate corners
    rotated = (rot_matrix @ local_corners.T).T
    
    # Translate to world position
    world_corners = rotated + np.array([cx, cy])
    
    # Extract rotated corner positions
    c0 = world_corners[0]  # front-left
    c1 = world_corners[1]  # front-right
    c2 = world_corners[2]  # back-right
    c3 = world_corners[3]  # back-left
    
    z0 = z_offset
    z1 = z_offset + h
    
    walls = []
    
    # Front face (c0 -> c1)
    walls.append(_create_wall(
        np.array([
            [c0[0], c1[0], c1[0], c0[0]],
            [c0[1], c1[1], c1[1], c0[1]],
            [z0, z0, z1, z1],
        ]),
        absorption, scattering, f"{name_prefix}_front"
    ))
    
    # Right face (c1 -> c2)
    walls.append(_create_wall(
        np.array([
            [c1[0], c2[0], c2[0], c1[0]],
            [c1[1], c2[1], c2[1], c1[1]],
            [z0, z0, z1, z1],
        ]),
        absorption, scattering, f"{name_prefix}_right"
    ))
    
    # Back face (c2 -> c3)
    walls.append(_create_wall(
        np.array([
            [c2[0], c3[0], c3[0], c2[0]],
            [c2[1], c3[1], c3[1], c2[1]],
            [z0, z0, z1, z1],
        ]),
        absorption, scattering, f"{name_prefix}_back"
    ))
    
    # Left face (c3 -> c0)
    walls.append(_create_wall(
        np.array([
            [c3[0], c0[0], c0[0], c3[0]],
            [c3[1], c0[1], c0[1], c3[1]],
            [z0, z0, z1, z1],
        ]),
        absorption, scattering, f"{name_prefix}_left"
    ))
    
    # Top face
    walls.append(_create_wall(
        np.array([
            [c0[0], c1[0], c2[0], c3[0]],
            [c0[1], c1[1], c2[1], c3[1]],
            [z1, z1, z1, z1],
        ]),
        absorption, scattering, f"{name_prefix}_top"
    ))
    
    return walls


def _pra_material(absorption: float, scattering: float):
    """Create a pyroomacoustics Material object."""
    import pyroomacoustics as pra
    return pra.Material(energy_absorption=float(absorption), scattering=float(scattering))


def build_room_with_raytracing(
    spec: RoomSpec,
    furniture: list[FurnitureBoxSpec],
    *,
    fs: int,
    max_order: int = 3,
    air_absorption: bool = True,
) -> tuple[Any, list[str]]:
    """
    Build a pyroomacoustics room with ray tracing and furniture.
    
    This function creates a room suitable for ray tracing simulation,
    including furniture items as additional reflective wall surfaces.
    
    Args:
        spec: Room specification (shoebox or polygon)
        furniture: List of furniture items to include
        fs: Sample rate in Hz
        max_order: Maximum reflection order (recommended: 3 for ray tracing)
        air_absorption: Whether to simulate air absorption
        
    Returns:
        Tuple of (room object, list of warning messages)
    """
    import pyroomacoustics as pra
    
    warnings: list[str] = []
    
    # Build base room with ray tracing enabled
    if isinstance(spec, ShoeboxRoomSpec):
        dims = [float(x) for x in spec.dimensions_m]
        default = _pra_material(
            spec.default_material.absorption,
            spec.default_material.scattering
        )
        
        wall_materials = {}
        for wall_name in ["west", "east", "south", "north", "floor", "ceiling"]:
            mat = spec.wall_materials.get(wall_name, spec.default_material)
            wall_materials[wall_name] = _pra_material(mat.absorption, mat.scattering)
        
        room = pra.ShoeBox(
            dims,
            fs=fs,
            materials=wall_materials,
            max_order=max_order,
            air_absorption=air_absorption,
            ray_tracing=True,
        )
        
    elif isinstance(spec, PolygonRoomSpec):
        corners = np.array(
            [[float(x), float(y)] for x, y in spec.corners_m],
            dtype=float
        ).T
        
        wall_mat = _pra_material(
            spec.wall_material.absorption,
            spec.wall_material.scattering
        )
        
        room = pra.Room.from_corners(
            corners,
            fs=fs,
            max_order=max_order,
            materials=wall_mat,
            air_absorption=air_absorption,
            ray_tracing=True,
        )
        
        room.extrude(
            float(spec.height_m),
            materials={
                "floor": _pra_material(
                    spec.floor_material.absorption,
                    spec.floor_material.scattering
                ),
                "ceiling": _pra_material(
                    spec.ceiling_material.absorption,
                    spec.ceiling_material.scattering
                ),
            },
        )
    else:
        raise ValueError("Unsupported room spec type")
    
    # Add furniture as wall surfaces
    furniture_count = 0
    for item in furniture:
        if item.type != "box":
            warnings.append(f"Skipping non-box furniture: {item.id}")
            continue
            
        # Get material properties
        if item.material:
            absorption = item.material.absorption
            scattering = item.material.scattering
        else:
            # Use default material based on furniture type (if available from id)
            mat = FURNITURE_MATERIALS.get("default")
            absorption = mat.absorption
            scattering = mat.scattering
        
        # Create walls for this furniture box
        name = item.id or f"furniture_{furniture_count}"
        box_walls = create_box_walls(
            item.min_m,
            item.max_m,
            absorption,
            scattering,
            name,
            include_bottom=False,  # Furniture sits on floor
        )
        
        # Add walls to room
        for wall in box_walls:
            room.walls.append(wall)
        
        furniture_count += 1
    
    if furniture_count > 0:
        warnings.append(
            f"Added {furniture_count} furniture items as reflective surfaces "
            f"({furniture_count * 5} wall faces) for ray tracing simulation."
        )
    
    return room, warnings


def convert_frontend_furniture_to_boxes(
    furniture_data: list[dict],
    room_height: float,
) -> list[FurnitureBoxSpec]:
    """
    Convert frontend furniture format to FurnitureBoxSpec for simulation.
    
    Frontend format (from room_plan_exporter.dart):
    {
        'id': 'furniture-1',
        'type': 'table',
        'position': {'x': 1.0, 'y': 0.0, 'z': 2.0},  # center position
        'rotation': {'x': 0.0, 'y': 0.5, 'z': 0.0},  # radians
        'dimensions': {'width': 1.6, 'height': 0.75, 'depth': 1.0},
    }
    
    Note: Frontend uses three.js coordinates where:
    - x: left-right
    - y: up-down (height)
    - z: front-back
    
    Pyroomacoustics uses:
    - x: left-right
    - y: front-back
    - z: up-down (height)
    
    Args:
        furniture_data: List of furniture dicts from frontend
        room_height: Room height for clamping furniture
        
    Returns:
        List of FurnitureBoxSpec objects with rotation applied
    """
    boxes = []
    
    for item in furniture_data:
        item_id = item.get("id", "unknown")
        item_type = item.get("type", "default")
        
        # Skip openings (doors/windows) and audio devices
        if item_type in ("door", "window", "speaker", "microphone"):
            continue
        
        position = item.get("position", {})
        rotation = item.get("rotation", {})
        dims = item.get("dimensions", {})
        
        # Extract values with defaults
        # Frontend: x=left-right, y=vertical, z=front-back
        # Convert to pyroom: x=left-right, y=front-back, z=vertical
        cx = float(position.get("x", 0))
        cy = float(position.get("z", 0))  # Frontend z -> pyroom y
        
        width = float(dims.get("width", 0.5))
        height = float(dims.get("height", 0.5))  # Vertical height
        depth = float(dims.get("depth", 0.5))
        
        # Rotation around vertical axis
        # Frontend stores negative rotation for three.js compatibility
        rotation_y = -float(rotation.get("y", 0))
        
        # Get acoustic material for this furniture type
        material = get_furniture_material(item_type)
        
        # Skip items with zero dimensions
        if width <= 0 or height <= 0 or depth <= 0:
            continue
        
        # Clamp height to room
        clamped_height = min(height, room_height - 0.01)
        
        # If furniture has rotation, we need to compute rotated corners
        if abs(rotation_y) > 0.01:
            # Create walls directly with rotation
            # Store rotation info for later processing
            # For now, compute axis-aligned bounding box as approximation
            # A more accurate approach would create rotated walls
            
            # Compute rotated bounding box
            cos_r = abs(math.cos(rotation_y))
            sin_r = abs(math.sin(rotation_y))
            rotated_width = width * cos_r + depth * sin_r
            rotated_depth = width * sin_r + depth * cos_r
            
            half_w = rotated_width / 2
            half_d = rotated_depth / 2
        else:
            half_w = width / 2
            half_d = depth / 2
        
        # Create axis-aligned bounding box
        min_corner = [cx - half_w, cy - half_d, 0.0]
        max_corner = [cx + half_w, cy + half_d, clamped_height]
        
        boxes.append(FurnitureBoxSpec(
            type="box",
            id=item_id,
            min_m=min_corner,
            max_m=max_corner,
            material=MaterialSpec(
                absorption=material.absorption,
                scattering=material.scattering,
            ),
        ))
    
    return boxes


def create_furniture_walls_with_rotation(
    furniture_data: list[dict],
    room_height: float,
) -> list[Any]:
    """
    Create wall surfaces for all furniture with proper rotation support.
    
    This is the preferred method for accurate furniture modeling as it
    creates properly rotated wall surfaces rather than axis-aligned boxes.
    
    Args:
        furniture_data: List of furniture dicts from frontend
        room_height: Room height for clamping
        
    Returns:
        List of pra.Wall objects representing all furniture surfaces
    """
    all_walls = []
    
    for idx, item in enumerate(furniture_data):
        item_id = item.get("id", f"furniture_{idx}")
        item_type = item.get("type", "default")
        
        # Skip openings and audio devices
        if item_type in ("door", "window", "speaker", "microphone"):
            continue
        
        position = item.get("position", {})
        rotation = item.get("rotation", {})
        dims = item.get("dimensions", {})
        
        # Extract values
        cx = float(position.get("x", 0))
        cy = float(position.get("z", 0))  # Frontend z -> pyroom y
        
        width = float(dims.get("width", 0.5))
        height = float(dims.get("height", 0.5))
        depth = float(dims.get("depth", 0.5))
        
        # Rotation (negate because frontend uses negative for three.js)
        rotation_y = -float(rotation.get("y", 0))
        
        # Get material
        material = get_furniture_material(item_type)
        
        # Skip zero-size items
        if width <= 0 or height <= 0 or depth <= 0:
            continue
        
        # Clamp height
        clamped_height = min(height, room_height - 0.01)
        
        # Create rotated box walls
        walls = create_rotated_box_walls(
            center=[cx, cy],
            dimensions=[width, depth, clamped_height],
            rotation_y=rotation_y,
            absorption=material.absorption,
            scattering=material.scattering,
            name_prefix=f"{item_type}_{item_id}",
            z_offset=0.0,
        )
        
        all_walls.extend(walls)
    
    return all_walls


def add_furniture_to_room(
    room,
    furniture_data: list[dict],
    room_height: float,
) -> int:
    """
    Add furniture walls to an existing pyroomacoustics room.
    
    This should be called after room.extrude() for polygon rooms
    or directly after ShoeBox creation.
    
    Args:
        room: pyroomacoustics Room object
        furniture_data: List of furniture dicts from frontend
        room_height: Room height in meters
        
    Returns:
        Number of furniture items added
    """
    walls = create_furniture_walls_with_rotation(furniture_data, room_height)
    
    for wall in walls:
        room.walls.append(wall)
    
    # Return count of furniture items (each has 5 walls)
    return len(walls) // 5
