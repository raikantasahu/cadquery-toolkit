"""Mounting bracket model"""

import cadquery as cq

def bracket(basex: float, basey: float, basez: float, holex: float, holey: float):
    """Create a mounting bracket

    Args:
        basex: Base plate width
        basey: Base plate depth
        basez: Base plate height
        holex: Center hole X dimension
        holey: Center hole Y dimension

    Sample use: bracket(40, 40, 5, 30, 30)
    """
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
