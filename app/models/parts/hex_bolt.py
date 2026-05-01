"""Hex bolt model"""

import math
import cadquery as cq

def hex_bolt(
    diameter: float = 8.0,
    length: float = 30.0,
    pitch: float = 1.25,
    head_width: float = 13.0,
    head_height: float = 5.3,
    chamfer: bool = True
):
    """Create a hex bolt (without threads).

    Args:
        diameter: Major thread diameter (e.g., 8.0 for M8)
        length: Bolt shank length (excluding head)
        pitch: Thread pitch (used to calculate minor diameter)
        head_width: Hex head across-flats (wrench size)
        head_height: Height of hex head
        chamfer: Whether to add chamfers

    Returns:
        CadQuery Workplane with the hex bolt
    
    Sample use: hex_bolt(8.0, 30.0, 1.25, 13.0, 5.3, True)
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
    # Step 3: Add tip chamfer
    # =========================================
    if chamfer:
        tip_chamfer = min(diameter * 0.3, pitch)
        try:
            bolt = bolt.faces("<Z").chamfer(tip_chamfer)
        except:
            pass

    return bolt


# Common metric bolt sizes reference
# Format: (diameter, pitch, head_width, head_height)
METRIC_BOLTS = {
    "M4":  (4.0,  0.7,  7.0,  2.8),
    "M5":  (5.0,  0.8,  8.0,  3.5),
    "M6":  (6.0,  1.0,  10.0, 4.0),
    "M8":  (8.0,  1.25, 13.0, 5.3),
    "M10": (10.0, 1.5,  16.0, 6.4),
    "M12": (12.0, 1.75, 18.0, 7.5),
    "M16": (16.0, 2.0,  24.0, 10.0),
    "M20": (20.0, 2.5,  30.0, 12.5),
}
