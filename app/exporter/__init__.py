"""
exporter - Format-specific writers for CadQuery models.

Each submodule exposes a single `export(thing, path, **kwargs)` function:

    from exporter import step_exporter, cadmodeldata_exporter

    step_exporter.export(workplane_or_assembly, "out.step")
    cadmodeldata_exporter.export(workplane_or_assembly, "out.json")

STEP export is a passthrough to cadquery's native writers (no FreeCAD, no
CAD_ModelData translation). CAD_ModelData JSON export goes through the
`converter` package, which uses FreeCAD internally to walk topology and
tessellate faces.
"""

from . import cadmodeldata_exporter, step_exporter

__all__ = [
    "step_exporter",
    "cadmodeldata_exporter",
]
