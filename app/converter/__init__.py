"""
converter - Convert CadQuery objects to CAD_ModelData.

This package centralizes "CadQuery → CAD_ModelData" conversion. It is the
single home for code that turns CadQuery shapes (Workplane / Shape) and
assemblies (cq.Assembly) into typed CAD_ModelData instances. Internally it
uses FreeCAD for OCCT topology walking and face tessellation, but that is
an implementation detail and not part of the public surface.

Public API:

    from converter import part_to_modeldata, assembly_to_modeldata, to_modeldata

    # A single CadQuery part (Workplane or Shape)
    part = part_to_modeldata(workplane, name="bracket")

    # A cq.Assembly tree
    asm = assembly_to_modeldata(cq_assembly)

    # Type-dispatching convenience
    md = to_modeldata(thing)   # picks part_ vs assembly_ based on type
"""

from ._freecad import HAS_CADQUERY, HAS_FREECAD
from .converter import (
    part_to_modeldata,
    assembly_to_modeldata,
    to_modeldata,
)

__all__ = [
    "part_to_modeldata",
    "assembly_to_modeldata",
    "to_modeldata",
    "HAS_CADQUERY",
    "HAS_FREECAD",
]
