"""
cadquery_models.py - Functions to create a few different types CadQuery models.

This script demonstrates how to create CadQuery models.

Requirements:
    pip install cadquery numpy requests
"""

import cadquery as cq


def box(boxx, boxy, boxz):
    """Create a simple box
    Sample use: box(10, 20, 30)
    """
    print("Box")
    print("-" * 50)
    
    # Create a box
    return cq.Workplane("XY").box(boxx, boxy, boxz)


def bracket(basex, basey, basez, holex, holey):
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


def cylinder(radius, height):
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


def cylinder_with_holes(radius, height, hole_radius):
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


def parametric_gear(num_teeth, outer_radius, inner_radius, tooth_depth, thickness, teeth_radius):
    """Create a simple parametric gear with rounded teeth
    Sample use: parametric_gear(30, 20, 10, 3, 5, 0.5)
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
    
    # Cut center hole
    return (
        gear.faces(">Z")
        .workplane()
        .circle(inner_radius)
        .cutThruAll()
    )

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


def box_with_rounded_edges_and_hole(boxx, boxy, boxz, fillet_radius, hole_radius):
    """Create a box with rounded edges and a hole
    Sample use: box_with_rounded_edges_and_hole(20, 20, 10, 0.5, 3)
    """
    return (
        cq.Workplane("XY")
        .box(boxx, boxy, boxz)
        .edges("|Z")
        .fillet(fillet_radius)
        .faces(">Z")
        .workplane()
        .hole(hole_radius)
    )


def complex_part():
    """Create a more complex part"""
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
        .edges("|Z")
        .fillet(1)  # Fillet edges
    )
    return result
