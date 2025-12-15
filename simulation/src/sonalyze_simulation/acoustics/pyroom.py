from __future__ import annotations

from typing import cast

import numpy as np

from sonalyze_simulation.schemas import PolygonRoomSpec, RoomSpec, ShoeboxRoomSpec


def _pra_material(absorption: float, scattering: float):
    import pyroomacoustics as pra

    # pyroomacoustics expects ``energy_absorption`` as the parameter name since
    # v0.7.x, so forward the scalar coefficients accordingly.
    return pra.Material(energy_absorption=float(absorption), scattering=float(scattering))


def build_room(
    spec: RoomSpec,
    *,
    fs: int,
    max_order: int,
    air_absorption: bool,
):
    warnings: list[str] = []

    import pyroomacoustics as pra

    if isinstance(spec, ShoeboxRoomSpec):
        dims = [float(x) for x in spec.dimensions_m]

        default = _pra_material(spec.default_material.absorption, spec.default_material.scattering)
        wall = {k: spec.wall_materials.get(k, spec.default_material) for k in [
            "west",
            "east",
            "south",
            "north",
            "floor",
            "ceiling",
        ]}
        materials = [
            _pra_material(wall["west"].absorption, wall["west"].scattering),
            _pra_material(wall["east"].absorption, wall["east"].scattering),
            _pra_material(wall["south"].absorption, wall["south"].scattering),
            _pra_material(wall["north"].absorption, wall["north"].scattering),
            _pra_material(wall["floor"].absorption, wall["floor"].scattering),
            _pra_material(wall["ceiling"].absorption, wall["ceiling"].scattering),
        ]

        room = pra.ShoeBox(
            dims,
            fs=fs,
            materials=materials,
            max_order=max_order,
            air_absorption=air_absorption,
        )
        return room, warnings

    if isinstance(spec, PolygonRoomSpec):
        corners = np.array([[float(x), float(y)] for x, y in spec.corners_m], dtype=float).T
        wall_mat = _pra_material(spec.wall_material.absorption, spec.wall_material.scattering)

        room2d = pra.Room.from_corners(
            corners,
            fs=fs,
            max_order=max_order,
            materials=wall_mat,
            air_absorption=air_absorption,
        )
        room2d.extrude(
            float(spec.height_m),
            materials={
                "floor": _pra_material(spec.floor_material.absorption, spec.floor_material.scattering),
                "ceiling": _pra_material(spec.ceiling_material.absorption, spec.ceiling_material.scattering),
            },
        )

        return cast(pra.Room, room2d), warnings

    warnings.append("Unsupported room type")
    raise ValueError("Unsupported room spec")
