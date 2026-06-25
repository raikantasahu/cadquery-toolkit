# Implementation Plan: Edge identity & picking

Status: **complete** (2026-06-24) — P1 (edge identity + inventory) and P2
(viewer edge-pick mode) verified headlessly in the `cadquery` env
(`tests/test_edge_identity.py`, `tests/test_edge_resolve.py`, all green) plus
P2's manual GUI check; P3 (app wiring: Pick/Edit Edges menu, Face/Edge/Vertex
order) verified by hand in the GUI. Edge label-editing is in F1 (rename now,
export later); container export is F2.

Implements `Feature.md`; verified by `Test.md`. Small, mostly-mirror feature:
the edge geometry and the resolver are already in place; we surface edges on the
per-part data, bridge a referenced `E#` to the resolver's edge anchor, list them
headlessly, and add an edge-pick mode that mirrors the face picker.

## Key finding: most of the stack already supports edges

| Layer | Faces / Vertices (existing) | Edges (target) |
|---|---|---|
| Converter PIDs | `F{index}` / `V{index}` (`converter/_freecad.py`) | `E{index}` ✓ already (`_freecad.py:_extract_edges`) |
| Model dict | `faceList[]` / `vertexList[]` | `edgeList[].vertexLocations` (discretized) + `start`/`end` ✓ present (`converter/converter.py`, `model/CADModelData.py:Edge`) |
| Geometric resolver | `resolve_face` / `resolve_vertex` | `resolve_edge(samples)` + `_resolve_anchor(kind="edge")` ✓ **already implemented** (`mesher/resolver.py:98`) |
| Per-part geometry surfaced | `face_pids`, `vertex_points`/`vertex_pids` (`model/tessellation.py:_emit_part`) | ❌ **missing — gap** |
| Pick → anchor bridge | `anchor_for_pick` V/F branches (`model/tessellation.py`) | ❌ **missing — gap** |
| Interactive picker | `_setup_multi_face_picking` / `_setup_multi_vertex_picking`, `show_pick_viewer(pick_mode=)` (`viewer/model_viewer.py`) | ❌ **missing — gap** |
| Headless inventory | `--list-entities` prints `vertex_pids` + `face_pids` (`app_cli.py:_list_entities`) | ❌ **missing — gap** |
| App wiring | `menu_pick_faces`/`menu_pick_vertices`, `_picked_faces`/`_picked_vertices` (`app_gtk.py`) | ❌ **missing — gap** |

The gaps are all in the **middle rows** — surface the edges, bridge the
reference, list them headlessly, and add the pick mode + app wiring. The data
layer (converter/EdgeList) and the resolution layer (`resolve_edge`) need no
change.

## Architecture — surface, bridge, pick

```
  converter/_freecad.py  --(already)-->  CADModelData.EdgeList
     E{index} + discretized vertexLocations + start/end
                              |
   model/tessellation.py: _emit_part  (NEW: surface edges)
     field_data["edge_pids"]    (global E# in traversal order)
     field_data["edge_points"]  (flat N×3, world space)
     field_data["edge_offsets"] (per-edge start indices, n+1)
            |                                   |
            v                                   v
   anchor_for_pick("E#")  (NEW branch)   viewer: _setup_multi_edge_picking (NEW)
     {"kind":"edge","samples":[...]}       cell-pick line actors -> E#
            |          \                        ^
            v           \                       |
   resolver.resolve_edge \  app_cli           app_gtk: Pick Edges menu (NEW)
     (samples) (exists)   --list-entities      self._picked_edges
     -> mesh curve(s)      lists E# + loc (NEW)
```

## Component changes

### 1. Surface edges — `model/tessellation.py: _emit_part`
Today `_emit_part` builds the per-part face PolyData and stashes `face_pids`,
plus topological `vertex_points`/`vertex_pids` from `vertexList`. Add, alongside
the vertex block (guarded by the same `with_face_index`), an **edge block** read
from `_ci_get(model, "edgeList")`, numbered globally with a new
`edge_counter` boxed int (mirroring `face_counter`/`vertex_counter`, so ids are
contiguous `E#` in CAD traversal order):
- For each edge, reshape its `vertexLocations` to (k, 3) and transform to world
  space via `_transform_points(..., transform)` (same call vertices use).
- Accumulate a flat `edge_points` array and an `edge_offsets` list (cumulative
  start index per edge, length n_edges + 1) so variable-length polylines slice
  unambiguously, and the parallel `edge_pids` list (`E{edge_counter[0]}`).
- Stash `field_data["edge_pids"]`, `["edge_points"]` (flattened), and
  `["edge_offsets"]`. Additive: `face_pids`/`vertex_*` are untouched (Test T0).
- A malformed edge (no/short `vertexLocations`) is skipped with a **loud**
  warning naming the part/edge (loud-safety-net), never silently mislabeled.

Thread the `edge_counter` through `create_polydatas_per_part` next to the
existing counters so numbering is global across parts (Test T0 contiguity).
`create_polydata_from_model_data` (the single-merged-mesh path) does **not** need
edges — only the per-part path feeds the picker and `anchor_for_pick`.

### 2. Bridge a referenced `E#` — `model/tessellation.py: anchor_for_pick`
Add an `E#` branch after the `V#`/`F#` branches, walking the same
`create_polydatas_per_part(... with_face_index=True)` parts:
- If `pid.startswith("E")` and `"edge_pids"` in `fd`: find the id's index, slice
  its polyline from `edge_points`/`edge_offsets`, and **subsample** to a handful
  of samples (endpoints + a few interior points — mirror the face branch's
  `centers[::step][:4]`), enough for `resolve_edge`'s projection self-check on a
  curved edge.
- Return `{"kind": "edge", "samples": [(x,y,z), ...]}`; unknown id → `None`
  (mirrors the V/F miss). This is exactly the shape `resolve_edge` /
  `_resolve_anchor(kind="edge")` already consume (Test T1/T2).

### 3. Headless edge inventory — `app_cli.py: _list_entities`
`_list_entities` already walks the per-part field-data, printing a line per
`vertex_pids` entry (with `at`) and per `face_pids` entry (with `centroid`/`area`).
Add a third loop over `edge_pids`, printing each `E#` with its location — reuse
`anchor_for_pick(md, pid)` and report the midpoint of the returned `samples` (or
the samples' centroid) as the edge's location, the value a config author keys on.
Trivial once §1 surfaces `edge_pids`; additive (face/vertex output unchanged).
This is the headless equivalent of GUI picking (Feature R8) and the entry point
F2/F3's CLI configs use. Green: **T5**.

### 4. Edge-pick mode — `viewer/model_viewer.py`
Mirror `_setup_multi_face_picking` (the cell-picker pattern), not the vertex
glyph path:
- New `_setup_multi_edge_picking(plotter, edge_entries, pick_state, single=False)`:
  per part build a line `pv.PolyData` from the `edge_points`/`edge_offsets`/
  `edge_pids` arrays P1 attached to each part's PolyData `field_data` — read from
  the same `parts` list (`create_polydatas_per_part(with_face_index=True)`) the
  face/vertex modes already consume, so no new data plumbing. Slice each polyline
  by `edge_offsets` into VTK polyline cells, tagging every cell with its
  per-part edge ordinal `cell_data["edge_index"]` (parallel to the face picker's
  `face_index`); a `vtkCellPicker` over those line actors maps a picked cell →
  `edge_index` → `edge_pids[edge_index]` → global `E#`; highlight the picked
  polyline (thicker /
  `PICK_HIGHLIGHT_COLOR`, `pickable=False`) and float an `Edge N` label at the
  edge midpoint. Reuse `_next_auto_pick_number(prefix="Edge")` and the toggle /
  remove / overlay-text scaffolding the face picker already has.
- Extend `show_pick_viewer(..., pick_mode=)` with `"edges"`: build the per-part
  line actors, make the face actors **non-pickable** (as vertex mode does), wire
  `_setup_multi_edge_picking`, and add a `picked_edges` property reading the
  mode's `_last_picks`.
- Integrate per-part visibility: pass the edge actors through
  `_add_visibility_checkboxes(..., extra_actors_by_label=)` (the same hook the
  vertex points use) so hiding a part hides its edges and — since VTK pickers
  honor visibility — excludes them from picking (Feature R6).

### 5. App wiring — `app_gtk.py` + `ui/window.ui`
Mirror the Pick/Edit-Vertices wiring (`Vertex-MeshEntityContainer`):
- `ui/window.ui`: add `menu_pick_edges` + `menu_edit_edge_selection`. Order the
  Model-menu pick/edit items by entity — **Face, Edge, Vertex** — each with its
  Pick + Edit pair.
- `app_gtk.py`: `_on_menu_pick_edges` opens the viewer with `pick_mode="edges"`
  via the shared `_open_pick_viewer`/`_finish_pick_viewer`;
  `_on_pick_edges_viewer_closed` stores results into a new `self._picked_edges`
  (initialized beside `_picked_faces`/`_picked_vertices`, cleared at the same
  `_invalidate_selections` points). `_on_menu_edit_edge_selection` reuses the
  generic `edit_face_selection(title="Edit Edge Selection")` dialog to rename
  picked-edge labels (parity with faces/vertices). Sensitivity: Pick Edges on
  when a model is loaded; Edit Edge Selection on when edges are picked.
- **Stop here for F1:** `_picked_edges` is *stored* and its labels are
  *editable*, but it is **not** merged into `entity_owners` (the owner merge —
  `set_face_owners`/`set_vertex_owners` in `_on_menu_save_mesh` — still touches
  only faces/vertices) — that merge and the CLI owner parsing are
  `Edge-MeshEntityContainer` (F2). Rename now, export later keeps F1
  non-destructive (Feature R7).

## Codebase touchpoints (current → target)
- `model/tessellation.py` — `_emit_part` edge surfacing (`edge_pids`/
  `edge_points`/`edge_offsets`) + `edge_counter` threaded through
  `create_polydatas_per_part`; new `E#` branch in `anchor_for_pick`.
- `app_cli.py` — `_list_entities` prints `edge_pids` (with location) alongside
  faces/vertices.
- `viewer/model_viewer.py` — `_setup_multi_edge_picking`; `show_pick_viewer`
  `pick_mode="edges"` + `picked_edges`; edge actors in the visibility hook;
  `_next_auto_pick_number(prefix="Edge")` (already parametrized).
- `app_gtk.py` — `_on_menu_pick_edges` + `_on_menu_edit_edge_selection`
  handlers, `_on_pick_edges_viewer_closed`, `self._picked_edges` (clear with
  faces/vertices), menu sensitivity for both items.
- `ui/window.ui` — `menu_pick_edges` + `menu_edit_edge_selection`, Model-menu
  pick/edit items ordered Face, Edge, Vertex.
- `app/tests/` — `test_edge_identity.py` (T0/T1/T3/T5), `test_edge_resolve.py`
  (T2 keystone, against a meshed F-quarter / F-box / F-assembly).

## Phased delivery (each phase = one PR; tests it must turn green)
- **P1 — Edge identity + inventory (pure data). — DONE (2026-06-24).** §1
  surfacing + §2 `anchor_for_pick` bridge + §3 `--list-entities` listing. Green
  in the `cadquery` env: **T0** (edges surfaced + counts —
  `test_edge_identity.py::test_box_edges_surfaced`,
  `::test_assembly_edges_global_contiguous`), **T1** (anchor shape —
  `::test_edge_anchor_shape_and_on_edge`, `::test_unknown_edge_pid_misses`),
  **T2** (referenced `E#` → correct curve(s), incl. the coincident contact edge
  → 2 curves — `test_edge_resolve.py::test_referenced_edges_resolve_to_matching_curves`,
  loud failure `::test_unresolvable_reference_is_loud`), **T3** (stable —
  `test_edge_identity.py::test_edge_ids_repeatable`), **T5** (headless inventory
  — `::test_list_entities_lists_edges`). The world-space clause of T0 is pinned
  by a dedicated placed-part guard,
  `test_edge_resolve.py::test_surfaced_edges_are_in_assembly_space` — surfaced
  edges land on the assembly-space gmsh curves to ~1e-12 on the off-identity
  `bolted_single_lap_joint` (translation + 180° rotation), the only fixture that
  would expose a missing per-part→assembly transform. (Earlier verification that
  compared per-part-local coordinates was unsound — identity placement made it
  look valid; this guard replaces it.) No UI; foundation both F2 and F3 import.
- **P2 — Interactive edge picking (viewer). — DONE (2026-06-24).** §4
  `_setup_multi_edge_picking` + `pick_mode="edges"` + per-part visibility
  integration; `edge_lines_polydata` GTK-free builder. Green: the builder's
  cell→pid mapping (`test_edge_identity.py::test_edge_lines_polydata_maps_cells_to_pids`)
  headless; the interactive picker verified by hand on the line-contact assembly
  (R1/R4/R6: pick/toggle, contact line on both bodies, per-part hide/show).
- **P3 — App wiring. — DONE (2026-06-24).** §5 Pick Edges + Edit Edge Selection
  menu items (Face/Edge/Vertex order), `_picked_edges` state +
  clear-on-model-change, label-rename via the shared edit dialog. Verified by
  hand in the GUI; `_picked_edges` populated, labels editable, picks independent
  of faces/vertices (export/consumption is F2).

## Risks / decisions to settle while building
- **Variable-length polylines.** Unlike vertices (one point each), edges have
  k-point polylines — hence `edge_offsets`. Keep the offset array the single
  source of slicing for both `anchor_for_pick` and the viewer.
- **Thin-line pick accuracy.** Picking a 1-px curve is fiddly; render edge actors
  with a small line width / tube and a cell-picker tolerance (reuse the face
  picker's `SetTolerance`). If still fiddly, a tube glyph gives a fatter pick
  target without changing identity.
- **Coincident contact edge.** Picking selects the *visible* part's edge; the
  resolver returns all coincident curves — one per touching body (GEI R5).
  Whether a consumer wants just one body's curve or all of them is its own choice
  (F2/F3); F1 surfaces both edges and resolves both, and picking the visible part
  is how the GUI narrows to one.
- **Curved edges & sample density.** `resolve_edge` projects samples onto
  candidate curves; subsample enough interior points (not just endpoints) so a
  curved contact edge still self-checks. The discretization (`Deflection=0.05`)
  is already fine enough.
- **Keep the bridge Gtk-free.** `anchor_for_pick` and the surfacing live in
  `model/tessellation.py` (no `gi`), so the headless tests import them without
  Gtk (per the `mesh_parts.py` separation precedent).
