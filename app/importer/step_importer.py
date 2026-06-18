"""
step_importer - Read a STEP file into a CadQuery in-memory model.

If the STEP file contains assembly structure, returns a cq.Assembly with
component names and per-instance locations recovered from the STEP product
hierarchy. Otherwise returns a cq.Workplane wrapping the lone shape.

This module deliberately knows nothing about CADModelData. It reads a
STEP file and hands back a CadQuery object; what to do with it (convert,
re-export, view) is the caller's choice.
"""

import logging
from typing import Union

import cadquery as cq

logger = logging.getLogger(__name__)


def read(path: str) -> Union[cq.Assembly, cq.Workplane]:
    """
    Read a STEP file and return a CadQuery in-memory model.

    Returns:
        cq.Assembly  if the STEP file contains assembly structure
                     (preserves component names and per-instance transforms)
        cq.Workplane if the STEP file contains a single shape, OR if reading it
                     as an assembly fails for any other reason (the model still
                     imports, just flattened — logged loudly).
    """
    # cq.Assembly.importStep walks the STEP product structure via OCCT's XCAF
    # tools. Single-shape STEPs raise ValueError("...does not contain an
    # assembly") — the expected, quiet fall-through. But foreign STEPs can also
    # trip cadquery on odd assembly structure (e.g. KeyError on an empty product
    # label, seen on NIST AP242). Rather than fail the whole import, fall back to
    # the flat shape import loudly — we must read STEP from any source.
    try:
        return cq.Assembly.importStep(path)
    except Exception as e:
        if "does not contain an assembly" not in str(e).lower():
            logger.warning(
                "could not read %s as an assembly (%s: %s); importing as a "
                "single shape", path, type(e).__name__, e)

    return cq.importers.importStep(path)
