"""P3 (cont.) — sources agree (T4) and the split is non-destructive (T5).

- **T4 (R5):** a live grid and the same mesh saved + reloaded describe the same
  parts — same count and same per-part cell counts (up to ordering).
- **T5 (R7):** tagging/splitting the viewer grid does not change the saved
  MeshData; the feature is view-only.

Headless: mesh → save → reload / compare, no GUI.
"""
import json

import numpy as np

from app_core import AppCore
from mesh_parts import mesh_part_labels, split_grid_by_part
from mesher import create_mesh, save_mesh_meshdata_json
from mesher.meshdata_reader import meshdata_to_pyvista
from models.assemblies import get_assembly_function


def _core(model, name):
    core = AppCore()
    core.set_model(model, name)
    return core


def _part_cell_counts(grid):
    """Per-part cell counts, sorted (partition compared up to ordering)."""
    pi = np.asarray(grid.cell_data["part_index"])
    n = len(mesh_part_labels(grid))
    return sorted(np.bincount(pi, minlength=n).tolist())


def test_live_and_loaded_describe_same_parts(tmp_path):
    """T4: live grid vs saved+reloaded grid — same part count and partition.

    Live tags by gmsh volume; loaded tags by distinct fragment owner. They must
    still describe the same 3 parts with the same per-part cell counts.
    """
    model = get_assembly_function("bolted_single_lap_joint")()
    core = _core(model, "bolted")
    mesher, _ = create_mesh(model, "tet4", 5.0)
    try:
        live = mesher.get_pyvista_mesh(part_labels=core.part_labels())
        live_counts = _part_cell_counts(live)
        out = str(tmp_path / "bolted.json")
        save_mesh_meshdata_json(mesher, out, owner="bolted")
    finally:
        mesher.finalize()

    with open(out) as f:
        data = json.load(f)
    loaded = meshdata_to_pyvista(data)

    assert len(mesh_part_labels(loaded)) == len(mesh_part_labels(live)) == 3
    assert _part_cell_counts(loaded) == live_counts


def test_save_is_unaffected_by_viewer_split(tmp_path):
    """T5: extracting/tagging/splitting the viewer grid leaves the saved
    MeshData byte-for-byte identical — the feature is view-only (R7)."""
    model = get_assembly_function("bolted_single_lap_joint")()
    core = _core(model, "bolted")
    mesher, _ = create_mesh(model, "tet4", 5.0)
    try:
        before = str(tmp_path / "before.json")
        save_mesh_meshdata_json(mesher, before, owner="bolted")
        # The viewer-side operations this feature adds — must not touch save:
        grid = mesher.get_pyvista_mesh(part_labels=core.part_labels())
        split_grid_by_part(grid)
        after = str(tmp_path / "after.json")
        save_mesh_meshdata_json(mesher, after, owner="bolted")
    finally:
        mesher.finalize()

    with open(before) as f:
        before_text = f.read()
    with open(after) as f:
        after_text = f.read()
    assert before_text == after_text
