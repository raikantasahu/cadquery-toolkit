"""P1 — producers tag the rendered grid by part (Per-Part-Mesh-Visibility).

Covers Test.md **T0** (both producers write ``part_index`` + ``part_labels``)
and the **parity half of T2** (the per-cell tag partitions the grid: every cell
tagged exactly once, in range, per-part counts sum to the whole). Headless:
asserts on grid ``cell_data``/``field_data``, never on a plotter.

See docs/plans/Per-Part-Mesh-Visibility/.
"""
import json
import logging

import cadquery as cq
import numpy as np
import pytest

from mesher import create_mesh, save_mesh_meshdata_json
from mesher.meshdata_reader import meshdata_to_pyvista
from model.tessellation import enumerate_part_labels

from helpers import cadmodeldata


def _labels(grid):
    return [str(x) for x in grid.field_data["part_labels"]]


def _part_index(grid):
    return np.asarray(grid.cell_data["part_index"])


def _assert_partition(grid):
    """T2 (parity half): part_index tags every cell exactly once, in range, and
    the per-part counts sum to the whole grid (no cell dropped or double-tagged).
    """
    pi = _part_index(grid)
    n_parts = len(_labels(grid))
    assert pi.shape[0] == grid.n_cells, "every cell must carry a part_index"
    assert pi.min() >= 0 and pi.max() < n_parts, "part_index out of label range"
    counts = np.bincount(pi, minlength=n_parts)
    assert counts.sum() == grid.n_cells
    assert (counts > 0).all(), "every part must own at least one cell"


# ── live path: gmsh_to_pyvista via GmshMesher.get_pyvista_mesh ───────────────

def _mesh_grid(model, part_labels=None):
    mesher, _ = create_mesh(model, "tet4", 5.0)
    try:
        return mesher.get_pyvista_mesh(part_labels=part_labels)
    finally:
        mesher.finalize()


def test_live_assembly_tagged_per_volume(fixtures):
    """F-assembly: 3 solids (2 plate instances + bolt) → 3 parts, labelled."""
    model = fixtures["bolted"]["model"]
    labels = enumerate_part_labels(cadmodeldata(model))
    assert len(labels) == 3, "instanced assembly must yield 3 per-instance labels"
    grid = _mesh_grid(model, part_labels=labels)
    assert _labels(grid) == [str(x) for x in labels]
    assert {int(x) for x in set(_part_index(grid))} == {0, 1, 2}
    _assert_partition(grid)


def test_live_single_part_one_part():
    """F-part: a single solid → exactly one part, no fallback noise."""
    grid = _mesh_grid(cq.Workplane("XY").box(10, 20, 30))
    assert len(_labels(grid)) == 1
    assert {int(x) for x in set(_part_index(grid))} == {0}
    _assert_partition(grid)


def test_live_label_mismatch_falls_back_loudly(fixtures, caplog):
    """A label list that doesn't line up with the volumes must not mislabel
    silently: fall back to Part 1..N and warn loudly (loud-safety-net)."""
    model = fixtures["bolted"]["model"]
    with caplog.at_level(logging.WARNING):
        grid = _mesh_grid(model, part_labels=["only-one"])  # 1 label, 3 volumes
    assert _labels(grid) == ["Part 1", "Part 2", "Part 3"]
    assert "PART LABEL MISMATCH" in caplog.text


def test_live_no_labels_synthesizes(fixtures):
    """No labels available (e.g. imported STEP) → synthesized Part 1..N."""
    grid = _mesh_grid(fixtures["bolted"]["model"])  # part_labels=None
    assert _labels(grid) == ["Part 1", "Part 2", "Part 3"]


# ── loaded path: meshdata_to_pyvista ────────────────────────────────────────

def test_loaded_assembly_tagged_by_owner(fixtures, tmp_path):
    """F-loaded-assembly: save the assembly mesh, reload it, and confirm cells
    tag by distinct fragment owner (3 owners → 3 parts) with a clean partition."""
    model = fixtures["bolted"]["model"]
    mesher, _ = create_mesh(model, "tet4", 5.0)
    out = str(tmp_path / "bolted_mesh.json")
    try:
        save_mesh_meshdata_json(mesher, out, owner="bolted")
    finally:
        mesher.finalize()

    with open(out) as f:
        data = json.load(f)
    grid = meshdata_to_pyvista(data)

    assert len(_labels(grid)) == 3  # 3 distinct fragment owners (one per volume)
    _assert_partition(grid)
