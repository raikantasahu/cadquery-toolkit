"""
cadquery_models.py - Functions to create a few different types CadQuery models.

This script demonstrates how to create CadQuery models with type hints
for better parameter handling in the GUI.

Requirements:
    pip install cadquery numpy requests
"""

import math
import cadquery as cq
from typing import Optional


def box(boxx: float, boxy: float, boxz: float):
    """Create a simple box
    Sample use: box(10, 20, 30)
    """
    print("Box")
    print("-" * 50)

    # Create a box
    return cq.Workplane("XY").box(boxx, boxy, boxz)


def bracket(basex: float, basey: float, basez: float, holex: float, holey: float):
    """Create a mounting bracket
    Sample use: bracket(40, 40, 5, 30, 30)
    """
    print("Mounting Bracket")
    print("-" * 50)

    # Create a mounting bracket
    return (
        cq.Workplane("XY")
        .box(basex, basey, basez)  # Base plate
        .faces(">Z")
        .workplane()
        .rect(holex, holey)
        .cutThruAll()  # Center hole
        .faces(">Z")
        .workplane()
        .pushPoints([(-12, 12), (12, 12), (-12, -12), (12, -12)])
        .circle(2)
        .cutThruAll()  # Mounting holes
        .faces(">Y")
        .workplane()
        .move(0, 2.5)
        .rect(10, 5)
        .extrude(20)  # Mounting tab
    )


def cylinder(radius: float, height: float):
    """Create a cylinder
    Sample use: cylinder(20, 30)
    """
    print("Cylinder")
    print("-" * 50)

    # Create a cylinder
    return (
        cq.Workplane("XY")
        .circle(radius)
        .extrude(height)
    )


def cylinder_with_holes(radius: float, height: float, hole_radius: float):
    """Create a cylinder with holes
    Sample use: cylinder_with_holes(20, 30, 10)
    """
    print("Cylinder with Holes")
    print("-" * 50)

    # Create a cylinder with holes
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
    Sample use: parametric_gear(12, 20, 10, 3, 5, 0.5, True)
    """
    print("Parametric Gear")
    print("-" * 50)

    # Create gear profile
    points = []
    import math
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


def loft():
    """Create a lofted shape
    Sample use: loft()
    """
    print("Lofted Shape")
    print("-" * 50)

    # Create a loft between two shapes
    return (
        cq.Workplane("XY")
        .rect(20, 20)
        .workplane(offset=20)
        .circle(10)
        .loft()
    )


def box_with_rounded_edges_and_hole(
    boxx: float,
    boxy: float,
    boxz: float,
    fillet_radius: float,
    hole_radius: Optional[float] = None
):
    """Create a box with rounded edges and an optional hole
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


def complex_part(add_fillets: bool = True):
    """Create a more complex part
    Sample use: complex_part(True)
    """
    print("Complex Part")
    print("-" * 50)

    # Create a complex part with multiple features
    result = (
        cq.Workplane("XY")
        .box(50, 50, 10)  # Base
        .faces(">Z")
        .workplane()
        .pushPoints([(-15, 15), (15, 15), (-15, -15), (15, -15)])
        .circle(3)
        .cutThruAll()  # Corner holes
        .faces(">Z")
        .workplane()
        .circle(10)
        .extrude(15)  # Center boss
        .faces(">Z")
        .workplane()
        .circle(5)
        .cutThruAll()  # Center hole through everything
    )

    if add_fillets:
        result = result.edges("|Z").fillet(1)  # Fillet edges

    return result

def hex_bolt(
    diameter: float = 8.0,          # M8 nominal diameter
    length: float = 30.0,           # 30mm bolt length
    pitch: float = 1.25,            # M8 coarse pitch
    head_width: float = 13.0,       # M8 across-flats
    head_height: float = 5.3,       # M8 head height
    chamfer: Optional[bool] = True  # Add chamfers
):
    """
    Create a hex bolt (without threads).

    Args:
        diameter: Major thread diameter (e.g., 8.0 for M8)
        length: Bolt shank length (excluding head)
        pitch: Thread pitch (used to calculate minor diameter)
        head_width: Hex head across-flats (wrench size)
        head_height: Height of hex head
        chamfer: Whether to add chamfers

    Returns:
        CadQuery Workplane with the hex bolt
    """

    # Head across-corners (point to point)
    head_across_corners = head_width / math.cos(math.radians(30))

    # Thread depth for ISO metric
    thread_depth = 0.5413 * pitch
    minor_diameter = diameter - 2 * thread_depth

    # =========================================
    # Step 1: Create the hex head
    # =========================================
    head = (
        cq.Workplane("XY")
        .polygon(6, head_across_corners)
        .extrude(head_height)
    )

    # Add chamfer to top of head
    if chamfer:
        chamfer_size = min(head_height * 0.2, 1.0)
        head = head.faces(">Z").chamfer(chamfer_size)
        head = head.faces("<Z").chamfer(0.3)

    # =========================================
    # Step 2: Create the shank (minor diameter to suggest threads)
    # =========================================
    bolt = head

    shank = (
        cq.Workplane("XY")
        .workplane(offset=-length)
        .circle(minor_diameter / 2)
        .extrude(length)
    )
    bolt = bolt.union(shank)

    # =========================================
    # Step 4: Add tip chamfer
    # =========================================
    if chamfer:
        tip_chamfer = min(diameter * 0.3, pitch)
        try:
            bolt = bolt.faces("<Z").chamfer(tip_chamfer)
        except:
            pass

    return bolt
