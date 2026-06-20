# Implementation Plan: Per-part visibility in the volumetric mesh viewer

Status: **shipped** (2026-06-20) — P1–P3 all DONE; acceptance MET (see end).

Implements `Feature.md`; verified by `Test.md`. Small, mostly-reuse feature: the
checkbox column and the per-part split already exist for the surface viewer; we
carry a per-part tag onto the **volumetric** grid and add a part-aware volumetric
viewer entry point.

## Architecture — tag the grid, split in the viewer

```
  live path                              loaded path
  GmshMesher.get_pyvista_mesh()          ModelViewer.set_mesh_from_dict()
   -> gmsh_to_pyvista(part_labels=...)    -> meshdata_to_pyvista(data)
        tags cell_data["part_index"]           tags cell_data["part_index"]
        field_data["part_labels"]              field_data["part_labels"]
                     \                         /
                      v                       v
            ModelViewer.show_viewer → show_volumetric_viewer(ugrid)
                #parts <= 1  -> one actor, no checkboxes      (Part)
                #parts  > 1  -> one actor per part + checkbox column  (Assembly)
                               (reuses _add_visibility_checkboxes)
```

The viewer decides Part vs Assembly purely from the grid it is handed (the count
of `part_labels`), so the same rule governs both producers — no separate
`is_assembly` flag reaches the viewer (Feature Decision: single source of the
signal).

## The two existing primitives we reuse
- **`_add_visibility_checkboxes(plotter, part_entries, ...)`** in
  `viewer/model_viewer.py` — already toggles per-actor visibility from a
  `[(label, actor, mesh)]` list; used by `show_pick_viewer`. Reused verbatim.
- **Per-volume fragment owners** — `mesher/export/meshdata._collect_fragments`
  already emits one fragment per (gmsh volume, element type) with an `owner`
  string, and assembly order == gmsh volume order == `enumerate_part_labels`
  order (documented contract; see `Part-Specific-Mesh-Controls.md`). Same
  segmentation we surface in the viewer.

## Component changes

### 1. Live producer — `mesher/gmsh_mesher.py: gmsh_to_pyvista()`
Today it reads `getElements(dim=3)` over the whole model at once, losing volume
identity. Change it to iterate `gmsh.model.getEntities(dim=3)` and call
`getElements(3, vol_tag)` per volume (mirroring `_collect_fragments`), recording
the volume ordinal per cell. Result grid gains:
- `cell_data["part_index"]` — 0-based volume ordinal per cell;
- `field_data["part_labels"]` — from a new optional `part_labels` arg.
Cells are grouped by volume (vs the flat read's type-grouping); the total cell
count and each element's connectivity/node reordering are unchanged — the tag is
additive and display-only. `get_pyvista_mesh(part_labels=None)` passes the arg
through.

### 2. Loaded producer — `mesher/meshdata_reader.py: meshdata_to_pyvista()`
Fragments already carry `owner`. In the existing cell-building loop, assign each
cell `part_index` = index of its fragment's owner in the distinct-owner list, and
set `field_data["part_labels"]` to those owners. Key by **owner**, so two
fragments of the same body that differ only by element type collapse to one part
(Feature R4 / Test T0). (Mirror the same tagging in `meshdata_xml_to_dict`'s
consumer path if the XML reader feeds the viewer.)

### 3. Viewer split — `mesh_parts.py` (helpers) + `viewer/model_viewer.py` (display)
The two **pure, display-free helpers** live in a new top-level `mesh_parts.py`
(numpy only — **not** in `model_viewer`, which pulls `gi`/Gtk via the `viewer`
package's eager `__init__`), so the gating and split import and test headlessly
(Test T1/T2) and the display code stays a thin consumer (separate-core-from-UI):
- `mesh_part_labels(ugrid) -> list[str]` — read `field_data["part_labels"]`
  (empty/absent → `[]`); the gate is `len(...) > 1`. The decision T1 asserts on.
- `split_grid_by_part(ugrid) -> list[(label, subgrid)]` — for each part index,
  `ugrid.extract_cells(part_index == i)` into a sub-grid; no/≤1 part → one
  `(label, ugrid)` over the whole grid. Pure; returns the sub-grids the viewer
  renders, so T2 can check the partition/parity without a display.

Then `show_volumetric_viewer(ugrid, title=...)` in `viewer/model_viewer.py`
consumes them:
- **≤ 1 part** → render one actor exactly as `show_pyvista` does today, **no
  checkboxes** (Part).
- **> 1 part** → add one actor per `split_grid_by_part` sub-grid with the
  existing volumetric styling (`show_edges=True`, `VOLUMETRIC_COLOR`), collect
  `(label, actor, subgrid)`, then call `_add_visibility_checkboxes(...)`.
- Reuse the shared camera / grid-floor / view-keybinding / help-text scaffold.
  That scaffold is duplicated across `show_pyvista` and `show_pick_viewer` today;
  factor it into one helper while here so the new function stays small (optional
  but recommended cleanup, keeps three viewers consistent — Feature R9).

`ModelViewer.show_viewer` is the single display entry point for both paths (the
live path reaches it via `show_mesh` → `set_mesh_from_pyvista` → `show_viewer`;
the loaded path via `set_mesh_from_dict` → `show_viewer`). Route its volumetric
branch through `show_volumetric_viewer` instead of `show_pyvista`; the setters
only store the grid (+ labels).

### 4. Label threading (live path) — `app_core.py` + `app_gtk.py`
`gmsh_to_pyvista` has no model context; the labels live in `AppCore`, which
already builds ordered part labels via `enumerate_part_labels` (used for
`entity_owners` `P{i}` in `selection_anchors`). `AppCore.part_labels()` returns
that ordered list (the assembly child names — `bottom-plate`, `top-plate`,
`bolt-1` — or the single part's name), or `None` when unavailable.
`app_gtk._on_menu_view_mesh` passes it **straight into** the producer:
`mesh_object.get_pyvista_mesh(part_labels=core.part_labels())`, so the grid is
tagged with the real names at extraction. When labels are unavailable (imported
STEP without names → `None`), `gmsh_to_pyvista` synthesizes `Part 1..N` from the
volume count so the assembly still gets toggles (Feature R3 fallback).

`enumerate_part_labels` walks `_iter_envelope` **per leaf instance** (with a
`#N` suffix for repeats), so its length equals the gmsh **volume** count that
`part_index` ranges over — including the instanced case (the bolted joint's two
identical plates count as two labels, two volumes), the definitions-vs-instances
trap flagged in `Geometric-Entity-Identification`. `gmsh_to_pyvista` must treat
this as a contract: if the supplied `part_labels` length ≠ the volume count, do
**not** mislabel silently — fall back to `Part 1..N` and **warn loudly** naming
the mismatch (loud-safety-net convention).

### 5. Wire-up — no `show_mesh` change needed
Because the grid is tagged at extraction (§4), `show_mesh` /
`set_mesh_from_pyvista` / `show_viewer` pass it through unchanged — the labels
already ride on `field_data["part_labels"]`. (An earlier plan threaded a
`part_labels` arg through `show_mesh`; dropped as redundant once the producer
tags directly.)

## Codebase touchpoints (current → target)
- `mesher/gmsh_mesher.py` — `gmsh_to_pyvista` per-volume iteration + tags;
  `get_pyvista_mesh(part_labels=None)`.
- `mesher/meshdata_reader.py` — `meshdata_to_pyvista` cell tags + labels.
- `mesh_parts.py` (new, GTK-free, numpy-only) — pure `mesh_part_labels` +
  `split_grid_by_part` helpers (headless-testable).
- `viewer/model_viewer.py` — `_setup_scene` shared scaffold (factored out of
  `show_pyvista`/`show_pick_viewer`); new `show_volumetric_viewer` consuming the
  `mesh_parts` helpers; `show_viewer` routes its volumetric branch through it.
- `app_core.py` — `part_labels()` accessor (ordered assembly child names /
  single-part name; `None` when unavailable).
- `app_gtk.py` — `_on_menu_view_mesh` passes `core.part_labels()` straight to
  `get_pyvista_mesh(part_labels=...)`. (`show_mesh`/`mesh_viewer.py` unchanged.)

## Phased delivery (each phase = one PR; tests it must turn green)
- **P1 — Tag the grids (producers). — DONE.** `gmsh_to_pyvista` per-volume
  tagging (+ `_resolve_part_labels` loud-fallback guard) + `meshdata_to_pyvista`
  owner tagging, both writing `part_index` + `part_labels`. Green: **T0**
  (producers tag correctly) and the parity half of **T2** (the tag partitions
  the grid) — `app/tests/test_p1_part_tagging.py`, 5 tests passing in the
  `cadquery` env. Pure data; no viewer change yet. (Confirmed `enumerate_part_labels`
  expands instances → 3 labels for the bolted joint's 3 volumes; no off-by-one.)
- **P2 — Part-aware volumetric viewer. — DONE.** `show_volumetric_viewer` (split
  + checkboxes, ≤1-part → single actor); `show_viewer`'s volumetric branch routed
  through it; shared scaffold factored into `_setup_scene` (also used by
  `show_pyvista`/`show_pick_viewer`); pure helpers in `mesh_parts.py`. Green:
  **T1** (gating) + sub-grid-union half of **T2** — `app/tests/test_p2_viewer_split.py`.
  Manual GUI checks (R2/R6/R8/R9) confirmed on the bolted assembly, incl. no
  regression in the refactored pick viewer.
- **P3 — Label threading + sources. — DONE.** `AppCore.part_labels()` →
  `_on_menu_view_mesh` passes it to `get_pyvista_mesh` (no `show_mesh` change);
  `Part {n}` fallback when unavailable. Green: **T3** (labels —
  `test_p3_part_labels.py`), **T4** (live vs loaded agree) + **T5**
  (non-destructive) — `test_p3_sources.py`. GUI confirmed real names
  (`bottom-plate` / `top-plate` / `bolt-1`).

Acceptance (per `Test.md`): **MET** — T0–T5 green headlessly in the `cadquery`
env + the manual GUI checks pass. Feature complete.

## Risks / decisions to settle while building
- **Label availability for imported STEP.** Until `Component.Name` flows through
  (`Mesh-Format-Notes.md` Step 1), imported assemblies fall back to `Part 1..N`.
  Acceptable per Feature R3; revisit when names land.
- **Mixed element types per part.** A body meshed into multiple element types
  produces multiple fragments with the same owner — collapse by owner to one
  part so it stays one toggle (handled in §2; covered by T0).
- **`extract_cells` cost.** Splitting a large assembly grid into N sub-grids is
  O(cells) per part; fine for interactive meshes. If it ever bites, mask once and
  reuse; not a launch concern.
- **Single-solid-from-assembly edge case.** An assembly that happens to mesh to
  one volume reads as one part → no control. That is the correct, data-driven
  outcome (Feature R1 is about parts, not the source model kind).
