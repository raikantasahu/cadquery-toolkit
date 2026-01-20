"""Parametric gear model"""

import math
import cadquery as cq

def parametric_gear(
    num_teeth: int,
    outer_radius: float,
    inner_radius: float,
    tooth_depth: float,
    thickness: float,
    teeth_radius: float,
    center_hole: bool = True
):
    """Create a simple parametric gear with rounded teeth

    Args:
        num_teeth: Number of teeth
        outer_radius: Outer radius of gear
        inner_radius: Inner radius (center hole)
        tooth_depth: Depth of each tooth
        thickness: Gear thickness
        teeth_radius: Fillet radius for teeth edges
        center_hole: Whether to cut center hole

    Sample use: parametric_gear(12, 20, 10, 3, 5, 0.5, True)
    """
    # Create gear profile
    points = []
    for i in range(num_teeth * 2):
        angle = 2 * math.pi * i / (num_teeth * 2)
        radius = outer_radius if i % 2 == 0 else outer_radius - tooth_depth
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        points.append((x, y))

    # Create gear base shape
    gear = (
        cq.Workplane("XY")
        .polyline(points)
        .close()
        .extrude(thickness)
    )

    # Apply fillet to round the teeth edges if teeth_radius > 0
    if teeth_radius > 0:
        gear = gear.edges("|Z").fillet(teeth_radius)

    # Cut center hole if requested
    if center_hole:
        gear = (
            gear.faces(">Z")
            .workplane()
            .circle(inner_radius)
            .cutThruAll()
        )

    return gear
