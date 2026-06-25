# Test Plan: Edge identity & picking

Tests verify the behaviors in `Feature.md` (R1–R8). The **identity layer** —
edges surfaced on the per-part geometry, the `E#` → anchor → resolve round trip,
and the headless edge inventory — is exercised **headlessly** (build the data,
assert the arrays, run the anchor through the resolver against a real gmsh mesh,
capture the entity listing). The on-screen click/highlight is the only
manually-verified part (no display in CI), in the same manual-GUI bucket as the
face/vertex pickers.

## Oracle — how we know an edge reference is "correct"
Correctness is checked against the geometry and the mesh, not the viewer's
bookkeeping:
- **Surfaced edges** match the model: the per-part `edge_pids` count equals the
  part's `edgeList` length, ids are contiguous `E#` in traversal order, and each
  surfaced polyline's points equal the model's discretized edge points
  transformed to world space (assembly-instance transform applied).
- **Anchor → resolve (the keystone):** for a referenced `E#`, the resolver maps
  the anchor's sample points to the mesh curve whose geometry matches — the same
  geometric self-check the resolver already applies (centroid + length, or
  projection). For the coincident contact edge on an assembly, it resolves to
  **one curve per touching body** (`Geometric-Entity-Identification` R5).
- **No collision:** `E#` ids never equal a `F#` or `V#` id used in the same
  selection set; the three pick lists are independent.

The oracle deliberately does **not** trust a live plotter; it asserts on the
field-data arrays and on `GeometricResolver.resolve_edge` against an actual
meshed model.

## Fixtures
- **F-quarter:** `hertzian_cylinder_on_block_quarter_symmetry` — the motivating
  model. Carries the **contact-line edge** on both the cylinder (curved-face ∩
  x=0-face) and the block (top-face ∩ x=0-face), coincident at `x=0, z=-R`.
  Primary fixture for R3/R4 and the keystone round trip.
- **F-box:** `box-10x20x30` (one solid, 12 straight edges). Smallest fixture for
  edge surfacing (T0), id contiguity (R2), and a straight-edge round trip.
- **F-assembly:** `bolted_single_lap_joint` (3 solid bodies, instanced plates) —
  per-part edge surfacing across instances and the coincident/independent-list
  checks (R6). The instancing trap (`Geometric-Entity-Identification` R4): a part
  placed twice surfaces its edges per **instance**.

Vendor any non-trivial fixture under `app/tests/models/` per the fixtures
convention (gitignore `!tests/models/**`); registry models are built in-test.

## Test groups

### T0 — Tessellation surfaces edges (precondition for everything)
`create_polydatas_per_part(data, with_face_index=True)` on F-box and F-assembly:
each part mesh carries `field_data["edge_pids"]` (contiguous global `E#` in
traversal order), `["edge_points"]` (flat N×3 world-space), and
`["edge_offsets"]` (per-edge start indices, length = n_edges + 1, so
variable-length polylines slice unambiguously). The `edge_pids` count equals the
part's `edgeList` length (F-box = 12); ids do not collide with that part's
`F#`/`V#`. The existing `face_pids`/`vertex_pids` arrays are **unchanged** (the
edge arrays are additive). A malformed/empty `edgeList` does **not** corrupt the
mesh — it yields no edge arrays and warns loudly (loud-safety-net), it does not
silently mislabel.
**Pass:** correct edge count + contiguous ids + world-space points on each
fixture; face/vertex arrays untouched.

### T1 — `anchor_for_pick` bridges `E#` to an edge anchor
For surfaced `E#` ids on F-box and F-quarter, `anchor_for_pick(data, "E#")`
returns `{"kind": "edge", "samples": [...]}` with **≥ 2** samples, each lying on
the edge (within tolerance of the discretized polyline). An unknown `E#` returns
`None` (mirrors the `V#`/`F#` miss). **Pass:** well-formed anchor with on-edge
samples; clean miss for an absent id.

### T2 — Referenced edge resolves to the right mesh curve(s) — the keystone
Mesh F-quarter and F-box with gmsh; build a `GeometricResolver`; for the contact
edge `E#` (and a couple of arbitrary edges), `resolve_edge(anchor["samples"])`
returns the curve(s) whose geometry matches the referenced edge (length +
location self-check). On **F-quarter as an assembly**, the coincident contact edge
resolves to **exactly two** curves — one on the cylinder, one on the block
(`Geometric-Entity-Identification` R5). A samples set that matches no curve, or
matches one whose extent disagrees, fails **loudly** (R5). **Pass:** correct
curve set per edge; two curves for the coincident contact edge; loud failure on
a bad reference.

### T3 — Identity is stable and repeatable (R2, GEI R8)
Building the per-part data twice yields identical `edge_pids` (same ids, same
order); the same `E#` resolves to the same curve(s) across repeated meshing.
**Pass:** byte-stable ids and stable resolution.

### T4 — Selection independence (R6)
Edge, face, and vertex pick lists are independent: an `E#` id never equals an
`F#`/`V#` id in the same model, and the app's `_picked_edges` list is cleared
and merged independently of `_picked_faces`/`_picked_vertices`. **Pass:** no id
collision; independent lists. (The id-namespace half — `E#` disjoint from
`F#`/`V#` — is already shown by P1's T0; the `_picked_edges` app-state half lands
with P2/P3, where that list first exists.)

### T5 — Headless edge inventory (R8)
`app_cli --list-entities` on F-box and F-quarter lists each part's edges — one
line per `E#` with its location — alongside the faces and vertices it already
prints. The listed `E#` set equals the surfaced `edge_pids` (T0), and each
listed location lies on that edge (consistent with the anchor's samples, T1).
The face/vertex lines are unchanged (additive). **Pass:** every edge listed with
an on-edge location; pre-existing face/vertex output intact. Assert by capturing
the command's stdout (no display); the listing is plain data.

## Manual (GUI) checks
Not headless-automatable; verify by hand on F-quarter and F-box:
- **R1:** Pick Edges mode — left-click an edge toggles it; the edge highlights
  and the overlay shows `Edge N [E#]`; a left drag rotates instead of picking.
- **R4:** on F-quarter, the contact line is clickable on the cylinder; hide the
  cylinder via its checkbox and the block's contact edge becomes the pickable one.
- **R6:** hiding a part hides its edges and excludes them from picking; camera
  rotation, view presets, reset, and wireframe still work in edge mode; switching
  among Pick Faces / Vertices / Edges keeps each mode's picks separate.
- **Rename (R7):** with edges picked, Edit Edge Selection… renames a label;
  status reports the count; the rename changes only the stored label (no export).
  Edit Edge Selection is disabled until at least one edge is picked.
- **Menu order:** the Model menu lists pick/edit items by entity — Face, Edge,
  Vertex — each with its Pick + Edit pair.

## Harness / how to run
- Headless tests run in the `cadquery` conda env against gmsh + pyvista in
  `app/tests/` (pytest). No display: they assert on `field_data` arrays and on
  `GeometricResolver.resolve_edge` against a real meshed model, never on a live
  plotter.
- The anchor bridge (`anchor_for_pick`) and the tessellation surfacing are pure
  data — importable without Gtk (keep them out of the eager-`gi` `viewer`
  package, per `mesh_parts.py` precedent).
- GUI checks are run by hand (conda-env rule: do not run gmsh/pyvista/cadquery
  from the default shell).

## Priority / acceptance
- **Must-pass core:** **T2** (referenced edge → correct curve(s), incl. the
  coincident contact edge — the silent-wrong-attachment guard) and **T0** (edges
  surfaced correctly — the precondition).
- **Broaden coverage:** T1, T3, T4, T5.
- The feature is **accepted** when T0–T5 pass headlessly in the `cadquery` env
  and the manual GUI checks pass.
- **Status (2026-06-24): ACCEPTED (feature complete).** T0/T1/T2/T3/T5 pass
  headlessly in the `cadquery` env (`test_edge_identity.py`,
  `test_edge_resolve.py`), plus the placed-part assembly-space guard
  (`::test_surfaced_edges_are_in_assembly_space`, ~1e-12 on the off-identity
  bolted joint) and the P2 line-builder mapping
  (`::test_edge_lines_polydata_maps_cells_to_pids`). **T4**'s id-namespace half
  is shown by T0; its `_picked_edges` app-state half plus all manual GUI checks
  (edge pick/toggle, rename, Face/Edge/Vertex order, per-part hide/show) verified
  by hand on P2+P3. Edge owners are not exported (F2).

## What is NOT tested here
- Edge **container** export and edge **mesh controls** — separate features (F2,
  F3); only that an edge is *identifiable and pickable* is tested here.
- Mesh quality / element generation (unchanged).
- The geometric resolver's edge resolution internals (already covered by
  `Geometric-Entity-Identification` tests); here we test the `E#` → anchor bridge
  feeding it.
- Exact rendering/styling of the highlighted edge beyond "the picked edge is
  visibly highlighted and labelled".
