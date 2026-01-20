"""Box with rounded edges and optional hole model"""

import cadquery as cq
from typing import Optional

def box_with_rounded_edges_and_hole(
    boxx: float,
    boxy: float,
    boxz: float,
    fillet_radius: float,
    hole_radius: Optional[float] = None
):
    """Create a box with rounded edges and an optional hole

    Args:
        boxx: Width (X dimension)
        boxy: Depth (Y dimension)
        boxz: Height (Z dimension)
        fillet_radius: Radius for edge fillets
        hole_radius: Optional center hole radius (None = no hole)

    Sample use: box_with_rounded_edges_and_hole(20, 20, 10, 0.5, 3)
    Use hole_radius=None or leave empty to create box without hole
    """
    result = (
        cq.Workplane("XY")
        .box(boxx, boxy, boxz)
        .edges("|Z")
        .fillet(fillet_radius)
    )

    # Only add hole if hole_radius is specified
    if hole_radius is not None:
        result = (
            result.faces(">Z")
            .workplane()
            .hole(hole_radius)
        )

    return result
