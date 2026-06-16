"""Thick tube model"""

import math
from typing import Optional

import cadquery as cq


def thick_tube(
    radius: float = 20,
    height: float = 30,
    hole_radius: float = 10,
    sweep_angle_deg: Optional[float] = None,
):
    """Create a thick tube, optionally an angular sector.

    Args:
        radius: Outer radius
        height: Tube height
        hole_radius: Concentric hole radius
        sweep_angle_deg: Optional angular extent in degrees, swept about the Z
            axis starting from the +X axis (None or >=360 = full tube). Use 90
            to model a quarter for symmetric loads and boundary conditions.

    Sample use: thick_tube(20, 30, 10), thick_tube(20, 30, 10, 90)
    """
    # Full revolution: keep the simple disk profile, then bore the hole.
    if sweep_angle_deg is None or sweep_angle_deg >= 360:
        return (
            cq.Workplane("XY")
            .circle(radius)
            .extrude(height)
            .faces(">Z")
            .workplane()
            .circle(hole_radius)
            .cutThruAll()
        )

    # Angular sector: build the annular cross-section, then extrude.
    # threePointArc uses the arc midpoint so it is unambiguous for any angle.
    theta = math.radians(sweep_angle_deg)
    half = theta / 2.0

    def pt(r, a):
        return (r * math.cos(a), r * math.sin(a))

    profile = (
        cq.Workplane("XY")
        .moveTo(*pt(hole_radius, 0))
        .lineTo(*pt(radius, 0))
        .threePointArc(pt(radius, half), pt(radius, theta))
        .lineTo(*pt(hole_radius, theta))
        .threePointArc(pt(hole_radius, half), pt(hole_radius, 0))
        .close()
    )

    return profile.extrude(height)
