"""Rectangular plate with a single through-hole.

Local frame (units = mm):
    Plate spans x in [0, length], centered in y, z in [0, thickness].
    The hole is a through-cylinder along the +Z axis at (length - edge_distance, 0).
    The edge_distance is measured from the +X end face — i.e. the "lap end"
    in a lap-joint configuration. To orient the plate with its lap end on
    the -X side instead, rotate it 180 deg around Z in the assembly.
"""

import cadquery as cq


def plate_with_hole(
    length: float = 130.0,
    width: float = 60.0,
    thickness: float = 6.0,
    hole_diameter: float = 12.0,
    edge_distance: float = 25.0,
) -> cq.Workplane:
    plate = (
        cq.Workplane("XY")
        .box(length, width, thickness, centered=(False, True, False))
    )
    hole = (
        cq.Workplane("XY")
        .moveTo(length - edge_distance, 0)
        .circle(hole_diameter / 2)
        .extrude(thickness)
    )
    return plate.cut(hole)
