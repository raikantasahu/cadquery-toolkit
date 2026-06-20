"""P2 — viewer split + gating helpers (Per-Part-Mesh-Visibility).

Covers Test.md **T1** (Part-vs-Assembly gating) and the **sub-grid-union half of
T2** (the per-part split reconstitutes the whole grid). The helpers under test
(`mesh_parts`) are GTK-free and plotter-free, so this runs headlessly. The
interactive checkbox/hide-show behaviour (R2/R6/R8/R9) is the manual GUI check.
"""
import numpy as np
import pyvista as pv
import cadquery as cq

from mesh_parts import mesh_part_labels, split_grid_by_part
from mesher import create_mesh


def _mesh_grid(model, part_labels=None):
    mesher, _ = create_mesh(model, "tet4", 5.0)
    try:
        return mesher.get_pyvista_mesh(part_labels=part_labels)
    finally:
        mesher.finalize()


def test_gating_assembly_splits_per_part(fixtures):
    """T1: an assembly (>1 part) → split with one entry per part, labels aligned."""
    grid = _mesh_grid(fixtures["bolted"]["model"])
    labels = mesh_part_labels(grid)
    assert len(labels) == 3
    parts = split_grid_by_part(grid)
    assert len(parts) == 3
    assert [lbl for lbl, _ in parts] == labels


def test_gating_single_part_no_control():
    """T1: a single part → one piece (the whole grid); the viewer shows no
    control (gate is len(parts) > 1)."""
    grid = _mesh_grid(cq.Workplane("XY").box(10, 20, 30))
    assert len(mesh_part_labels(grid)) == 1
    parts = split_grid_by_part(grid)
    assert len(parts) == 1
    assert parts[0][1].n_cells == grid.n_cells


def test_split_reconstitutes_whole_grid(fixtures):
    """T2 (union half): the per-part sub-grids partition the whole grid — their
    cell counts sum to the full grid and every part owns at least one cell."""
    grid = _mesh_grid(fixtures["bolted"]["model"])
    parts = split_grid_by_part(grid)
    counts = [sub.n_cells for _lbl, sub in parts]
    assert sum(counts) == grid.n_cells
    assert all(c > 0 for c in counts)


def test_untagged_grid_degrades_to_single_part():
    """A grid with no part tagging → one part (defensive; pure pyvista, no gmsh)."""
    cells = np.array([4, 0, 1, 2, 3])
    celltypes = np.array([10], dtype=np.uint8)  # VTK_TETRA
    pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    grid = pv.UnstructuredGrid(cells, celltypes, pts)
    assert mesh_part_labels(grid) == []
    parts = split_grid_by_part(grid)
    assert len(parts) == 1
    assert parts[0][1].n_cells == 1
