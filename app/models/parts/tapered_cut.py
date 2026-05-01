import numpy as np
import cadquery as cq

def tapered_cut(
    boxx: float = 30,
    boxy: float = 30,
    boxz: float = 30,
    cut_radius: float = 10,
    cut_depth: float = 10,
    taper: float = 15):

    box = cq.Workplane("XY").box(boxx, boxy, boxz)

    # Create tapered annular cut via revolve
    cut_profile = (
        cq.Workplane("XZ")
        .moveTo(5, boxz*0.5)      # Inner top of cut (radius=5, at z=10)
        .lineTo(10, 5)             # Inner bottom (tapered outward)
        .lineTo(15, boxz*0.5)     # Outer top (no taper on outside)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )

    return box.cut(cut_profile)
