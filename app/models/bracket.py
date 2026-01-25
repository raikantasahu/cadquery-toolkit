"""Mounting bracket model"""

import cadquery as cq
from typing import Optional

def bracket(
    leg_a: float = 50.0,
    leg_b: float = 50.0,
    thickness: float = 5.0,
    depth: float = 20.0,
    inner_radius: Optional[float] = None,
    hole_diameter: Optional[float] = None,
    num_holes_a: Optional[int] = None,
    num_holes_b: Optional[int] = None,
) -> cq.Workplane:
    """
    Create an L-shaped bracket with optional filleted corners and mounting holes.
    
    The bracket is oriented with leg A extending along the +X axis and leg B
    extending along the +Y axis. The bracket is extruded along the +Z axis.
    
    Parameters
    ----------
    leg_a : float, default 50.0
        Length of the horizontal leg (along +X axis), measured from the outer corner.
    leg_b : float, default 50.0
        Length of the vertical leg (along +Y axis), measured from the outer corner.
    thickness : float, default 5.0
        Material thickness of both legs.
    depth : float, default 20.0
        Depth of the bracket (extrusion distance along +Z axis).
    inner_radius : float, optional
        Fillet radius for the inner corner. If specified, the outer corner is
        also filleted with radius equal to inner_radius + thickness.
    hole_diameter : float, optional
        Diameter of mounting holes. Required if num_holes_a or num_holes_b is specified.
    num_holes_a : int, optional
        Number of mounting holes in leg A. Holes are centered across the depth
        and equally spaced along the leg length.
    num_holes_b : int, optional
        Number of mounting holes in leg B. Holes are centered across the depth
        and equally spaced along the leg length.
    
    Returns
    -------
    cq.Workplane
        A CadQuery Workplane containing the bracket solid.
    
    Examples
    --------
    Basic bracket with default dimensions:
    
        >>> result = bracket()
    
    Bracket with filleted corners:
    
        >>> result = bracket(leg_a=60, leg_b=40, thickness=4, inner_radius=5)
    
    Bracket with mounting holes:
    
        >>> result = bracket(
        ...     leg_a=80,
        ...     leg_b=60,
        ...     thickness=5,
        ...     depth=25,
        ...     inner_radius=8,
        ...     hole_diameter=6,
        ...     num_holes_a=3,
        ...     num_holes_b=2
        ... )
    """
    # ... implementation

    outer_radius = None
    if inner_radius is not None:
        outer_radius = inner_radius + thickness
        ri = inner_radius
        ro = outer_radius
        
        # Profile with arcs at corners
        profile = (
            cq.Workplane("XY")
            .moveTo(leg_a, 0)
            .lineTo(leg_a, thickness)
            .lineTo(ro, thickness)
            .radiusArc((thickness, ro), ri)
            .lineTo(thickness, leg_b)
            .lineTo(0, leg_b)
            .lineTo(0, ro)
            .radiusArc((ro, 0), -ro)
            .close()
        )
    else:
        # Sharp corners
        profile = (
            cq.Workplane("XY")
            .moveTo(0, 0)
            .lineTo(leg_a, 0)
            .lineTo(leg_a, thickness)
            .lineTo(thickness, thickness)
            .lineTo(thickness, leg_b)
            .lineTo(0, leg_b)
            .close()
        )

    # for v in profile.vertices().vals():
    #    print(v.toTuple())
    
    bracket = profile.extrude(depth)

    # Add holes to leg A (horizontal leg)
    if hole_diameter is not None and num_holes_a is not None and num_holes_a > 0:
        bracket = add_holes_to_horizontal_leg(
            bracket,
            leg_a,
            thickness,
            depth,
            hole_diameter,
            num_holes_a,
            outer_radius)
    
    # Add holes to leg B (vertical leg)
    if hole_diameter is not None and num_holes_b is not None and num_holes_b > 0:
        bracket = add_holes_to_vertical_leg(
            bracket,
            leg_b,
            thickness,
            depth,
            hole_diameter,
            num_holes_b,
            outer_radius)
    
    return bracket

def add_holes_to_horizontal_leg(
    bracket,
    leg_a,
    thickness,
    depth,
    hole_diameter,
    num_holes,
    outer_radius: Optional[float] = None):

    start_x = outer_radius if outer_radius is not None else thickness
    available_length = leg_a - start_x
    spacing = available_length / num_holes
    edge_margin = spacing / 2 + start_x
    x_positions = [edge_margin + i * spacing for i in range(num_holes)]
    # print(f"Hole positions: {x_positions}")

    hole_points = [(x, depth / 2) for x in x_positions]

    # Create holes by explicitly cutting cylinders through the horizontal leg
    holes = (
        cq.Workplane("XZ")
        .pushPoints(hole_points)
        .circle(hole_diameter / 2)
        .extrude(-thickness)
    )

    return bracket.cut(holes)

def add_holes_to_vertical_leg(
    bracket,
    leg_b,
    thickness,
    depth,
    hole_diameter,
    num_holes,
    outer_radius: Optional[float] = None):

    start_y = outer_radius if outer_radius is not None else thickness
    available_length = leg_b - start_y
    spacing = available_length / num_holes
    edge_margin = spacing / 2 + start_y
    y_positions = [edge_margin + i * spacing for i in range(num_holes)]
    # print(f"Hole positions: {y_positions}")

    hole_points = [(y, depth / 2) for y in y_positions]

    # Create holes by explicitly cutting cylinders through the vertical leg
    holes = (
        cq.Workplane("YZ")
        .pushPoints(hole_points)
        .circle(hole_diameter / 2)
        .extrude(thickness)
    )

    return bracket.cut(holes)

