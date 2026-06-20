"""P3 — real per-part labels reach the viewer mesh (Per-Part-Mesh-Visibility).

Covers Test.md **T3** (labels are the assembly's part names, in stable order,
unique) and the `AppCore.part_labels` → `get_pyvista_mesh` wiring the GUI uses.
Headless: AppCore + the producer, no GUI.
"""
import cadquery as cq

from app_core import AppCore
from mesh_parts import mesh_part_labels
from mesher import create_mesh
from models.assemblies import get_assembly_function

_BOLTED = ["bottom-plate", "top-plate", "bolt-1"]


def _core(model, name):
    core = AppCore()
    core.set_model(model, name)
    return core


def test_part_labels_are_assembly_child_names():
    """T3: labels come from the assembly's child names, in volume order."""
    core = _core(get_assembly_function("bolted_single_lap_joint")(), "bolted")
    labels = core.part_labels()
    assert labels == _BOLTED
    assert len(labels) == len(set(labels)), "labels must be unique per part"


def test_part_labels_tag_the_live_grid():
    """The labels AppCore supplies land on the grid the viewer renders — so the
    checkboxes read 'bottom-plate' / 'top-plate' / 'bolt-1', not 'Part N'."""
    model = get_assembly_function("bolted_single_lap_joint")()
    core = _core(model, "bolted")
    mesher, _ = create_mesh(model, "tet4", 5.0)
    try:
        grid = mesher.get_pyvista_mesh(part_labels=core.part_labels())
    finally:
        mesher.finalize()
    assert mesh_part_labels(grid) == _BOLTED


def test_single_part_label_is_the_part_name():
    """A single part → one label (no assembly children); viewer shows no
    control, and what label exists is the part's own name, not 'Part 1'."""
    core = _core(cq.Workplane("XY").box(10, 20, 30), "box-10x20x30")
    labels = core.part_labels()
    assert labels is not None and len(labels) == 1
