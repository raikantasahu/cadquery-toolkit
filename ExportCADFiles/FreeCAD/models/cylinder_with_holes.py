"""Cylinder with holes model"""

import cadquery as cq

def cylinder_with_holes(radius: float, height: float, hole_radius: float):
    """Create a cylinder with holes

    Args:
        radius: Cylinder outer radius
        height: Cylinder height
        hole_radius: Center hole radius

    Sample use: cylinder_with_holes(20, 30, 10)
    """
    return (
        cq.Workplane("XY")
        .circle(radius)
        .extrude(height)
        .faces(">Z")
        .workplane()
        .circle(hole_radius)
        .cutThruAll()  # Center hole
        .faces(">Z")
        .workplane()
        .pushPoints([(12, 0), (0, 12), (-12, 0), (0, -12)])
        .circle(3)
        .cutThruAll()  # Side holes
    )
