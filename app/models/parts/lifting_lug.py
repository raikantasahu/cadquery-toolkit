"""Lifting lug — flat-plate single-hole lug for first-pass capacity analysis.

A rectangular plate with a single through-hole. The bottom edge represents the
attachment to a parent structure; the hole receives a pin bearing load
representing a vertical lift.

Geometry conventions (units = mm):
    X : in-plane width direction (transverse to load)
    Y : in-plane height direction, parallel to load (load points +Y)
    Z : out-of-plane thickness direction
    Origin at bottom-center of the lug face; lug spans y in [0, height].

Anchor faces (resolved by selector at runtime):
    bottom_face  : selector "<Y" — y=0 face; fixed support target.
    hole_surface : selector "%CYLINDER" — full cylindrical inner surface of the
                   hole; pin bearing load target. The first-pass template
                   applies a uniform bearing pressure over the whole surface;
                   directional refinement (upper-half only) is deferred.
"""

import cadquery as cq


def lifting_lug(
    width: float = 80.0,
    height: float = 100.0,
    thickness: float = 12.0,
    hole_diameter: float = 25.0,
    edge_distance: float = 35.0,
) -> cq.Workplane:
    # edge_distance is measured from the top edge to the hole center.
    hole_y = height - edge_distance

    lug = (
        cq.Workplane("XY")
        .box(width, height, thickness, centered=(True, False, False))
    )

    hole = (
        cq.Workplane("XY")
        .moveTo(0, hole_y)
        .circle(hole_diameter / 2)
        .extrude(thickness)
    )

    return lug.cut(hole)
