"""
step_exporter - Write CadQuery parts and assemblies to STEP files.

STEP export is essentially a passthrough — both single parts and assemblies
are already OCCT shapes on the cadquery side, and cadquery has native STEP
writers for both. This module just dispatches by type.

No FreeCAD dependency, no CAD_ModelData translation.
"""

from typing import Any, Union

import cadquery as cq


def export(thing: Union[cq.Assembly, cq.Workplane, cq.Shape], path: str) -> None:
    """
    Write a CadQuery object to a STEP file.

    Dispatches by type:
      - cq.Assembly  → preserves component names, transforms, and colors via
                       cadquery's exportAssembly.
      - cq.Workplane → workplane.val().exportStep(path)
      - cq.Shape     → shape.exportStep(path)
    """
    if isinstance(thing, cq.Assembly):
        # exportAssembly preserves the assembly tree, names, and colors —
        # better than flattening to a single compound.
        from cadquery.occ_impl.exporters.assembly import exportAssembly
        exportAssembly(thing, path)
        return

    if isinstance(thing, cq.Workplane):
        thing.val().exportStep(path)
        return

    if isinstance(thing, cq.Shape):
        thing.exportStep(path)
        return

    raise TypeError(
        f"Cannot export {type(thing).__name__} to STEP "
        f"(expected cq.Assembly, cq.Workplane, or cq.Shape)"
    )
