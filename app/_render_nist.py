"""Regenerate the NIST showcase mesh images, off-screen.

Imports the vendored NIST STEP, tet-meshes it (size 20, sag 0.02), and writes
docs/screenshots/Mesh-NIST-{full,crosssection,detail}.png in the model viewer's
mesh colours (VOLUMETRIC_COLOR on the dark background). Run from app/ in the
cadquery conda env:  python _render_nist.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pyvista as pv

from importer.step_importer import read
from mesher import create_mesh

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "docs", "screenshots")
STEP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "tests", "models", "nist_ctc_01_asme1_ap242-e1.stp")

FILL = "#4fc3f7"      # VOLUMETRIC_COLOR — the viewer's MESH display color
EDGE = "#333333"      # the viewer's mesh edge color
BG = "#1a1a1a"        # matches the GUI viewer's BACKGROUND_COLOR


def shot(mesh, path, zoom=1.0):
    pl = pv.Plotter(off_screen=True, window_size=(1500, 1100))
    pl.set_background(BG)
    pl.add_mesh(mesh, color=FILL, show_edges=True, edge_color=EDGE,
                opacity=1.0, smooth_shading=False, lighting=True)
    pl.enable_3_lights()
    pl.show_axes()
    pl.camera_position = "iso"
    pl.camera.azimuth = 25
    pl.camera.elevation = 18
    pl.reset_camera()
    pl.camera.zoom(zoom)
    pl.screenshot(os.path.join(OUT, path))
    pl.close()
    print("wrote", path)


model = read(STEP)
mesher, stats = create_mesh(model, "tet4", 20.0, model_name="nist",
                            relative_sag_tolerance=0.02)
print("nist stats:", stats)
grid = mesher.get_pyvista_mesh()
mesher.finalize()

b = grid.bounds  # xmin,xmax,ymin,ymax,zmin,zmax
cx = (b[0] + b[1]) / 2.0
cy = (b[2] + b[3]) / 2.0
cz = (b[4] + b[5]) / 2.0

# 1. Full part (reference — likely a dense blob)
shot(grid, "Mesh-NIST-full.png", zoom=1.0)

# 2. Cross-section: keep the half with x <= centre, exposing interior tets.
clipped = grid.clip(normal="x", origin=(cx, cy, cz), invert=True)
shot(clipped, "Mesh-NIST-crosssection.png", zoom=1.1)

# 3. Detail crop: a sub-box (~1/3 of each extent) near one corner of the part.
dx = (b[1] - b[0]) / 3.0
dy = (b[3] - b[2]) / 3.0
dz = (b[5] - b[4])
detail = grid.clip_box(
    bounds=(b[0], b[0] + dx, b[2], b[2] + dy, b[4], b[4] + dz), invert=False)
shot(detail, "Mesh-NIST-detail.png", zoom=1.2)
