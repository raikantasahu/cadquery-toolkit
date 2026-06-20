"""mesh_parts - split a part-tagged volumetric mesh grid into per-part pieces.

GTK-free and gmsh-free (numpy only), so the viewer's Part-vs-Assembly gating and
the split it drives are unit-testable headlessly and the display code in
``viewer/model_viewer.py`` stays a thin consumer (separate-core-from-UI).

The grids these operate on carry, per cell, a 0-based ``part_index`` and a
parallel ``part_labels`` field-data list — written by the producers
``mesher.gmsh_mesher.gmsh_to_pyvista`` (live) and
``mesher.meshdata_reader.meshdata_to_pyvista`` (loaded).
"""
from typing import List, Tuple

import numpy as np


def mesh_part_labels(ugrid) -> List[str]:
    """Per-part labels carried on a volumetric grid, or ``[]`` if untagged.

    The viewer offers per-part hide/show only when ``len(...) > 1`` (an
    assembly); a single-part mesh (a Part) has one label and gets no controls.
    """
    labels = ugrid.field_data.get("part_labels")
    if labels is None:
        return []
    return [str(x) for x in labels]


def split_grid_by_part(ugrid) -> List[Tuple[str, object]]:
    """Split a part-tagged grid into ``[(label, subgrid)]``, one entry per part.

    Uses ``cell_data["part_index"]`` to extract each part's cells. Pure (no
    plotter), so the partition is checkable headlessly. With no part tagging, or
    a single part, returns one ``(label, ugrid)`` over the whole grid (the Part
    case — the caller then renders a single actor with no checkboxes).
    """
    labels = mesh_part_labels(ugrid)
    part_index = ugrid.cell_data.get("part_index")
    if part_index is None or len(labels) <= 1:
        return [(labels[0] if labels else "Part 1", ugrid)]
    part_index = np.asarray(part_index)
    parts = []
    for i, label in enumerate(labels):
        cell_ids = np.where(part_index == i)[0]
        parts.append((label, ugrid.extract_cells(cell_ids)))
    return parts
