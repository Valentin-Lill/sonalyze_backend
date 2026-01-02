"""
Acoustic material library for room simulation.

Provides predefined materials with absorption and scattering coefficients
commonly used in room acoustics simulation.
"""

from __future__ import annotations

from sonalyze_simulation.schemas import MaterialSpec


# Material library with typical absorption/scattering coefficients
# Values are averages across typical frequency bands (250-4000 Hz)
_MATERIALS: dict[str, tuple[str, float, float]] = {
    # (display_name, absorption, scattering)
    # Hard surfaces
    "concrete": ("Concrete", 0.02, 0.05),
    "brick": ("Brick (unpainted)", 0.03, 0.10),
    "marble": ("Marble / Tile", 0.01, 0.02),
    "glass": ("Glass", 0.04, 0.02),
    "plaster": ("Plaster / Drywall", 0.10, 0.05),
    "painted_concrete": ("Painted Concrete", 0.06, 0.05),
    # Wood surfaces
    "hardwood": ("Hardwood Floor", 0.10, 0.10),
    "parquet": ("Parquet Floor", 0.07, 0.10),
    "wood_panel": ("Wood Paneling", 0.15, 0.15),
    "plywood": ("Plywood", 0.12, 0.10),
    # Soft / absorptive surfaces
    "carpet_thin": ("Thin Carpet", 0.20, 0.20),
    "carpet_thick": ("Thick Carpet", 0.50, 0.30),
    "carpet_padded": ("Carpet with Underlay", 0.60, 0.35),
    "curtain_light": ("Light Curtain", 0.15, 0.20),
    "curtain_heavy": ("Heavy Curtain", 0.55, 0.25),
    "upholstery": ("Upholstered Furniture", 0.45, 0.20),
    # Acoustic treatments
    "acoustic_panel": ("Acoustic Panel", 0.80, 0.15),
    "acoustic_foam": ("Acoustic Foam", 0.70, 0.10),
    "acoustic_tile": ("Acoustic Ceiling Tile", 0.65, 0.20),
    "perforated_panel": ("Perforated Panel", 0.50, 0.40),
    "diffuser": ("Diffuser Panel", 0.15, 0.80),
    # Ceiling materials
    "suspended_ceiling": ("Suspended Ceiling", 0.50, 0.25),
    "mineral_fiber": ("Mineral Fiber Ceiling", 0.70, 0.25),
    "gypsum_ceiling": ("Gypsum Board Ceiling", 0.15, 0.10),
    # Default / generic
    "default": ("Default", 0.20, 0.05),
}


class MaterialInfo:
    """Represents a single material with its acoustic properties."""

    def __init__(self, id: str, display_name: str, absorption: float, scattering: float):
        self.id = id
        self.display_name = display_name
        self.absorption = absorption
        self.scattering = scattering

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "absorption": self.absorption,
            "scattering": self.scattering,
        }

    def to_material_spec(self) -> MaterialSpec:
        return MaterialSpec(absorption=self.absorption, scattering=self.scattering)


def get_all_materials() -> list[MaterialInfo]:
    """Return all available materials."""
    return [
        MaterialInfo(id=mat_id, display_name=data[0], absorption=data[1], scattering=data[2])
        for mat_id, data in _MATERIALS.items()
    ]


def get_material_by_id(material_id: str) -> MaterialInfo | None:
    """Look up a material by its ID."""
    data = _MATERIALS.get(material_id)
    if data is None:
        return None
    return MaterialInfo(id=material_id, display_name=data[0], absorption=data[1], scattering=data[2])


def get_material_spec_by_id(material_id: str) -> MaterialSpec | None:
    """Get a MaterialSpec by material ID for use in simulation."""
    material = get_material_by_id(material_id)
    if material is None:
        return None
    return material.to_material_spec()


def get_default_material() -> MaterialInfo:
    """Return the default material."""
    return get_material_by_id("default") or MaterialInfo(
        id="default", display_name="Default", absorption=0.20, scattering=0.05
    )
