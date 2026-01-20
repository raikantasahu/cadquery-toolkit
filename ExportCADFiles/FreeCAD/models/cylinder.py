"""Cylinder model"""

import cadquery as cq

def cylinder(radius: float = 20, height: float = 30):
    """Create a cylinder

    Args:
        radius: Cylinder radius
        height: Cylinder height

    Sample use: cylinder(20, 30)
    """
    return (
        cq.Workplane("XY")
        .circle(radius)
        .extrude(height)
    )
