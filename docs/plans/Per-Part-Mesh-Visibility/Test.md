# Test Plan: Per-part visibility in the volumetric mesh viewer

Tests verify the behaviors in `Feature.md` (R1–R9 + success criteria). The
**data** the viewer relies on — per-part tagging of the rendered grid and the
split-by-part it drives — is exercised **headlessly** (build a grid, assert its
tags, split it, compare). The actual checkbox interaction and on-screen
hide/show are the only manually-verified parts (no display in CI).

## Oracle — how we know per-part display is "correct"
The viewer splits the rendered mesh into parts using a per-cell **part tag** and
a parallel **part-label list** carried on the grid. Correctness is checked
against the mesh itself, not against the viewer's own bookkeeping:
- **Part count** equals the number of solid bodies in the source — gmsh volume
  count for the live path, distinct fragment-owner count for a loaded MeshData
  file. A single-part mesh yields exactly one part.
- **Partition / parity (R4):** the per-cell part tag assigns every cell to
  exactly one part; the parts' cell counts sum to the whole grid's cell count;
  and the union of the per-part sub-grids reconstitutes the full grid with no
  cell lost or duplicated.
- **Labels (R3):** the label list has one entry per part, in a stable order, and
  matches the source's part names where the source provides them.

The oracle deliberately does **not** trust the viewer's actor list; it asserts on
the grid tags and the sub-grids derived from them, which is what the viewer in
turn renders.

## Fixtures
- **F-assembly:** an app assembly meshed to a volumetric grid — the
  `bolted_single_lap_joint` (two **identical** plate instances + a bolt → 3 solid
  bodies / 3 gmsh volumes). The multi-part case, and the instanced case
  (`enumerate_part_labels` must yield 3 labels, not 2 — see T0); primary fixture
  for R1/R2/R3/R4.
- **F-part:** a single-part mesh — `box-10x20x30` (one solid). The single-part
  case (R1: no control).
- **F-loaded-assembly:** a saved **MeshData JSON** of an assembly (multiple
  fragments with distinct owners), read back through the loaded path — exercises
  R5 on the file reader without re-meshing.
- **F-twobody:** a minimal two-body assembly (e.g. two separated boxes) — the
  smallest case that must offer the control; cheap parity/labels check.

Vendor any non-trivial mesh fixture under `app/tests/models/` per the fixtures
convention (gitignore `!tests/models/**`); single-part / two-box grids can be
built in-test from the registry + mesher.

## Test groups

### T0 — Producers tag the grid by part (precondition for everything)
For both producers of the rendered grid:
- **Live path** (`gmsh_to_pyvista`): on F-assembly the grid carries a per-cell
  part tag with one distinct value per gmsh volume, and a label list of that
  length (F-assembly's two identical plates count as two labels / two volumes,
  not one — the instanced case); on F-part exactly one part. Cells are grouped
  by volume (vs the flat read's type-grouping); the total cell count and each
  element's connectivity are unchanged — the tag is additive. A supplied
  `part_labels` whose length ≠ the volume count must **not** mislabel silently:
  the producer falls back to `Part 1..N` and warns **loudly** (loud-safety-net).
- **Loaded path** (`meshdata_to_pyvista`): on F-loaded-assembly each cell is
  tagged with the index of its fragment's owner, and the label list is the
  distinct owners. Fragments that differ only by element type but share an owner
  collapse to **one** part.
**Pass:** correct part count + label length on each fixture; single part for
F-part; total cell count and element identity unchanged vs the untagged grid.

### T1 — Assembly-only gating (R1)
Given each fixture's grid, the viewer's decision function returns "show per-part
control" iff the grid has more than one part. **Pass:** F-assembly /
F-twobody / F-loaded-assembly → control shown (N toggles for N parts); F-part →
no control.

### T2 — Partition & parity (R4) — the keystone
On F-assembly and F-twobody: every cell has exactly one part tag (no cell
untagged, no tag out of range); the per-part cell counts sum to the full grid's
cell count; and concatenating the per-part sub-grids yields a grid with the same
cell count and the same set of cells as the full grid. **Pass:** exact parity;
a mismatch fails **loudly** (a dropped or double-counted element is a defect, per
the loud-safety-net convention).

### T3 — Labels (R3)
On F-assembly the label list has one entry per part in a stable order across
repeated builds, and matches the assembly's part names where the source carries
them (else positional `Part {n}`). **Pass:** count, stability, and name match;
no two parts share a label.

### T4 — Both sources agree (R5)
Mesh F-assembly live, save it to MeshData JSON, reload it, and confirm the
reloaded grid yields the **same part count** and an equivalent partition (same
number of parts, same per-part cell counts up to ordering) as the live grid.
**Pass:** live and loaded paths describe the same parts.

### T5 — Non-destructive (R7)
Build the per-part split, then save/export the mesh; the saved MeshData is
byte-for-byte independent of any visibility state (there is no visibility state
to persist). **Pass:** the split/tagging adds nothing to saved output; saving an
assembly mesh is unchanged by this feature.

## Priority / acceptance
- **Must-pass core:** **T2** (partition/parity — the silent dropped/duplicated-
  element guard) and **T1** (the user-visible Part-vs-Assembly gating, R1).
- **Broaden coverage:** T0, T3, T4, T5.
- The feature is **accepted** when T0–T5 pass headlessly in the `cadquery` env
  and the manual GUI checks below pass.
- **Status (2026-06-20): ACCEPTED.** T0–T5 pass headlessly in the `cadquery`
  env — `test_p1_part_tagging.py`, `test_p2_viewer_split.py`,
  `test_p3_part_labels.py`, `test_p3_sources.py` — and the manual GUI checks
  pass (per-part hide/show with real names; pick-viewer refactor regression-free).

## Surface model viewer (P4 extension)
The same per-part hide/show was extended to the plain **CAD model** geometry
view. Headless gate (`test_model_viewer_parts.py`): `create_polydatas_per_part`
yields >1 named part for an assembly (`bottom-plate`/`top-plate`/`bolt-1`) and
exactly one for a single part — the data `show_viewer` gates on. The
rendering/checkbox interaction is a manual GUI check (below), the same R2/R6/R8/R9
behaviours as the mesh viewer applied to the geometry view.

## Manual (GUI) checks
Not headless-automatable; verify by hand on F-assembly and F-part:
- **R1:** assembly mesh shows one toggle per part; single-part mesh shows none.
- **R2/R6:** all parts visible on open; toggling a part hides/shows only that
  part, immediately.
- **R8:** hiding every part leaves axes/floor/camera usable; unhiding restores.
- **R9:** with a part hidden, camera rotation, the view presets, reset, and
  wireframe toggle all still work on the visible parts.
- **R3:** each toggle's label identifies the right part (cross-check against the
  assembly tree).

## Harness / how to run
- Headless tests run in the `cadquery` conda env against gmsh + pyvista, in the
  existing `app/tests/` pytest suite. No display required — they assert on grid
  cell-data/field-data and on sub-grids, never on a live plotter. The split /
  gating helpers live in a GTK-free `mesh_parts.py`, so T1/T2 import them
  without pulling Gtk (the `viewer` package's eager `__init__` does).
- F-assembly / F-loaded-assembly are built once (registry + mesher + the
  MeshData JSON exporter/reader already in the repo).
- GUI checks are run by hand.

## What is NOT tested here
- Mesh quality or element generation (unchanged by this feature).
- The surface CAD viewer's existing per-part hide/show (already shipped).
- Per-part mesh **controls** (size/type) — separate feature; only that the
  viewer **displays** parts separately is tested here.
- Exact rendering/styling (colors, edge display) beyond "all-visible matches the
  current single-body view".
