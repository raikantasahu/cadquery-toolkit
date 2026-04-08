"""
step_importer - Read a STEP file into a CadQuery in-memory model.

If the STEP file contains assembly structure, returns a cq.Assembly with
component names and per-instance locations recovered from the STEP product
hierarchy. Otherwise returns a cq.Workplane wrapping the lone shape.

This module deliberately knows nothing about CADModelData. It reads a
STEP file and hands back a CadQuery object; what to do with it (convert,
re-export, view) is the caller's choice.
"""

from typing import Union

import cadquery as cq


def read(path: str) -> Union[cq.Assembly, cq.Workplane]:
    """
    Read a STEP file and return a CadQuery in-memory model.

    Returns:
        cq.Assembly  if the STEP file contains assembly structure
                     (preserves component names and per-instance transforms)
        cq.Workplane if the STEP file contains a single shape
    """
    # cq.Assembly.importStep walks the STEP product structure via OCCT's
    # XCAF document tools. It raises ValueError("Step file does not contain
    # an assembly") for single-shape STEPs — fall through to the flat path
    # in that case.
    try:
        return cq.Assembly.importStep(path)
    except ValueError as e:
        if "does not contain an assembly" not in str(e).lower():
            raise

    return cq.importers.importStep(path)
