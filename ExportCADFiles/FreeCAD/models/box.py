"""Box model"""

import cadquery as cq

def box(boxx: float, boxy: float, boxz: float):
    """Create a simple box

    Args:
        boxx: Width (X dimension)
        boxy: Depth (Y dimension)
        boxz: Height (Z dimension)

    Sample use: box(10, 20, 30)
    """
    return cq.Workplane("XY").box(boxx, boxy, boxz)
