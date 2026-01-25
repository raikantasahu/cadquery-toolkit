"""
CadQuery Hex Nut Generator

Creates parametric hex nuts with vertex chamfers on top face corners.
"""

from typing import Optional
import cadquery as cq
import math


def hex_nut(
    across_flats: float = 7.0,
    thickness: float = 3.2,
    hole_diameter: float = 4.0,
    chamfer_angle_top: Optional[float] = None,
    chamfer_angle_bottom: Optional[float] = None,
) -> cq.Workplane:
    """
    Create a hex nut with optional vertex chamfers.

    Parameters
    ----------
    across_flats : float
        Distance across the flat sides of the hexagon (wrench size).
    thickness : float
        Height/thickness of the nut.
    hole_diameter : float
        Diameter of the center hole.
    chamfer_angle_top : float, optional
        Angle of chamfer on top surface. Default is 30 degrees
    chamfer_angle_bottom : float, optional
        Angle of chamfer on top surface. Default is 30 degrees

    Returns
    -------
    cq.Workplane
        The hex nut solid.

    Example
    -------
    >>> # M10 nut (approximate dimensions)
    >>> nut = hex_nut(across_flats=17.0, thickness=8.0, hole_diameter=10.0)
    """
    # Calculate across corners from across flats
    # For a regular hexagon: across_corners = across_flats / cos(30°)
    across_corners = across_flats / (math.sqrt(3) / 2)

    # Default chamfer size
    # if chamfer_size is None:
    #    chamfer_size = thickness * 0.15

    # Create the hex prism
    nut = (
        cq.Workplane("XY")
        .polygon(6, across_corners)
        .extrude(thickness)
    )

    # Cut the center hole
    nut = (
        nut.faces(">Z")
        .workplane()
        .hole(hole_diameter)
    )

    if chamfer_angle_top != None:
        nut = add_chamfer_top(nut, across_corners, across_flats, thickness, chamfer_angle_top)

    if chamfer_angle_bottom != None:
        nut = add_chamfer_bottom(nut, across_corners, across_flats, thickness, chamfer_angle_bottom)

    return nut

def add_chamfer_top(
    nut,
    across_corners,
    across_flats,
    thickness,
    chamfer_angle):

    print("Adding chamfer at the top.")
    print(f"across_corners: {across_corners}")
    print(f"across_flats: {across_flats}")
    print(f"thickness: {thickness}")
    print(f"Chamfer angle: {chamfer_angle}")

    # Create tapered cuts via revolve

    # Create profile for the top
    chamfer_depth = math.tan(math.radians(chamfer_angle))*0.5*(across_corners - across_flats)
    cut_profile = (
        cq.Workplane("XZ")
        .moveTo(0.5*across_corners, thickness)
        .lineTo(0.5*across_flats, thickness)
        .lineTo(0.5*across_corners, thickness - chamfer_depth)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )

    return nut.cut(cut_profile)

def add_chamfer_bottom(
    nut,
    across_corners,
    across_flats,
    thickness,
    chamfer_angle):

    print(f"Adding chamfer at the bottom. Chamfer angle: {chamfer_angle}")

    # Create tapered cuts via revolve

    # Create profile for the bottom
    chamfer_depth = math.tan(math.radians(chamfer_angle))*0.5*(across_corners - across_flats)
    cut_profile = (
        cq.Workplane("XZ")
        .moveTo(0.5*across_corners, 0)
        .lineTo(0.5*across_flats, 0)
        .lineTo(0.5*across_corners, chamfer_depth)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )

    return nut.cut(cut_profile)

def hex_nut_iso(size: str) -> cq.Workplane:
    """
    Create a hex nut using standard ISO metric dimensions.

    Parameters
    ----------
    size : str
        Metric size designation (e.g., "M6", "M10", "M12").

    Returns
    -------
    cq.Workplane
        The hex nut solid.

    Example
    -------
    >>> nut = hex_nut_iso("M10")
    """
    # ISO 4032 standard hex nut dimensions (approximate)
    # Format: (across_flats, thickness, hole_diameter)
    iso_dimensions = {
        "M3": (5.5, 2.4, 3.0),
        "M4": (7.0, 3.2, 4.0),
        "M5": (8.0, 4.7, 5.0),
        "M6": (10.0, 5.2, 6.0),
        "M8": (13.0, 6.8, 8.0),
        "M10": (17.0, 8.4, 10.0),
        "M12": (19.0, 10.8, 12.0),
        "M14": (22.0, 12.8, 14.0),
        "M16": (24.0, 14.8, 16.0),
        "M20": (30.0, 18.0, 20.0),
        "M24": (36.0, 21.5, 24.0),
    }

    if size not in iso_dimensions:
        available = ", ".join(sorted(iso_dimensions.keys(), key=lambda x: int(x[1:])))
        raise ValueError(f"Unknown size '{size}'. Available: {available}")

    af, t, d = iso_dimensions[size]
    return hex_nut(across_flats=af, thickness=t, hole_diameter=d)


# Demo / test
if __name__ == "__main__":
    # Create an M10 nut
    nut = hex_nut_iso("M10")

    # Export to STEP
    cq.exporters.export(nut, "hex_nut_m10.step")
    print("Exported hex_nut_m10.step")

    # Also create a custom nut
    custom = hex_nut(
        across_flats=25.0,
        thickness=12.0,
        hole_diameter=14.0,
        chamfer_angle_top=30
    )
    cq.exporters.export(custom, "hex_nut_custom.step")
    print("Exported hex_nut_custom.step")
