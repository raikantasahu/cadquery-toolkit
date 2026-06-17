"""Pytest harness for the Geometric Entity Identification feature.

The repo's first test package (see docs/plans/Geometric-Entity-Identification/).
Runs headlessly in the `cadquery` conda env against gmsh — no display, no GUI.
Run from the app dir:  python -m pytest tests/
"""
import os
import sys

import pytest

# Make the app package importable regardless of how pytest is invoked.
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import cadquery as cq
from exporter.step_exporter import export as step_export
from models.assemblies import get_assembly_function
from models.parts import get_part_function


def _two_cubes():
    """F-twocubes: two unit cubes touching at the x=1 face (1:1, coincident
    interface faces/edges/vertices) — a 2-part assembly so it has CADModelData."""
    a = cq.Assembly()
    a.add(cq.Workplane("XY").box(1, 1, 1).translate((0.5, 0.5, 0.5)), name="c1")
    a.add(cq.Workplane("XY").box(1, 1, 1).translate((1.5, 0.5, 0.5)), name="c2")
    return a


# Fixtures whose CAD topology gmsh preserves 1:1 (verified 2026-06-17). The
# bolted/interpenetrating case is intentionally NOT here — it violates 1:1 and
# is a P1 concern.
def _build_models():
    return {
        "hertz": get_assembly_function(
            "hertzian_sphere_on_block_quarter_symmetry")(),
        "hemisphere": get_part_function("hemisphere_sector")(
            radius=10.0, sweep_angle=360.0),
        "twocubes": _two_cubes(),
    }


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    """{name: {'model': cq object, 'step': exported STEP path}} built once."""
    out_dir = tmp_path_factory.mktemp("geid_fixtures")
    fx = {}
    for name, model in _build_models().items():
        step = str(out_dir / f"{name}.step")
        step_export(model, step)
        fx[name] = {"model": model, "step": step}
    return fx
