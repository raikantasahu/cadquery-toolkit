# Feature: Edge identity & picking (select edges from the model)

Status: **shipped** (2026-06-24) — delivered in `Implementation.md` phases
P1–P3; verified per `Test.md` (T0–T5 headless + manual GUI checks). Foundation
feature: two consumers build on it and are tracked separately —
`Edge-MeshEntityContainer` (export named edge containers) and `Edge-Mesh-Controls`
(local + contact mesh control on edges). Neither depends on the other; both
depend on this.

## Summary
Make a CAD **edge** a first-class, identifiable entity — pickable in the GUI and
discoverable headlessly — exactly as **faces** and **vertices** already are. A
user can enter an edge-pick mode in the surface model viewer and left-click an
edge to select it; a config author with no viewer can **list** the model's edges
(`E#` + geometry) to reference one. In both cases the edge id (`E#`) resolves to
a geometric edge **anchor** that the mesher's resolver maps to the correct mesh
curve(s). This is the identity layer the edge-owner export and edge mesh-control
features build on; it produces a selection and a resolvable reference, nothing
downstream yet.

The motivating case is **line contact**: the
`hertzian_cylinder_on_block_quarter_symmetry` model touches along a contact
**line** (a CAD edge shared by the cylinder and the block). To refine the mesh
along that line — or name it as a node set — the user must first be able to
*point at the edge*. Today they cannot: the picker resolves only faces and
vertices.

## Why this is needed
Faces and vertices are pickable and resolvable; edges are not, even though the
edge geometry already ships in the model. The CAD→data converter
(`converter/_freecad.py`) already discretizes every edge into a polyline with a
stable `E{index}` persistent id and start/end vertices, and
`CADModelData.EdgeList` already carries it; the geometric resolver already
resolves an edge anchor (`GeometricResolver.resolve_edge`,
`_resolve_anchor(kind="edge")`). The only gap is the **middle**: the edges are
never surfaced for rendering/picking, and there is no bridge from a referenced
`E#` to the resolver's edge anchor. This feature closes that gap so an edge can
be referred to the same way a face or vertex can.

Without it, the line-contact workflow has no way to designate the contact edge,
and the two follow-on features (edge containers, edge mesh controls) have no
identity layer to stand on.

## What it does
- Adds an **edge-pick mode** to the surface model viewer (a third mode beside
  Pick Faces / Pick Vertices): left-click an edge to toggle it; the picked edge
  is highlighted and labelled `Edge N` with its `E#` id in the overlay.
- Surfaces each part's edges (as world-space polylines with a parallel `E#` id
  list) on the per-part geometry the viewer already builds — mirroring how
  `vertex_points`/`vertex_pids` are surfaced today.
- Bridges an edge id (`E#`) to a **geometric edge anchor**
  (`{"kind": "edge", "samples": [...]}`) that the resolver maps to the matching
  mesh curve(s) — source-independent and per the `Geometric-Entity-Identification`
  contract.
- Lists edges (with `E#` + location) in the headless entity inventory
  (`app_cli --list-entities`) so a config author can reference one without the
  GUI — alongside the faces/vertices it already lists.
- Lets the user **rename** a picked edge's label (an Edit Edge Selection dialog),
  mirroring faces/vertices — the label that will become the container name when
  F2 exports it. The label is held in the pick list only; nothing is written yet.
- Keeps edge picks in their own selection list, independent of face and vertex
  picks.

## Requirements (behavior)

- **R1 — Edges are pickable.** In the surface model viewer the user can enter an
  edge-pick mode and select an edge by left-clicking it (a left drag still
  rotates the camera). Selecting toggles: clicking a picked edge unpicks it.
  Picks accumulate and each carries an auto label `Edge N`.

- **R2 — Stable edge identity.** Each part's edges are surfaced with a stable
  `E#` id in CAD traversal order, mirroring the `F#`/`V#` schemes. The id is a
  handle for display and for fetching the anchor — **not** a resolution key
  (R3).

- **R3 — Geometric anchor, source-independent.** A referenced `E#` (whether
  picked in the GUI or listed headlessly) yields a geometric edge anchor —
  sample points along the edge — that the resolver resolves to the correct mesh
  curve(s), regardless of which tool produced the geometry. Identity rides on
  geometry, not on `E#` ordering or names
  (`Geometric-Entity-Identification` R1/R3/R9).

- **R4 — Coincident edges are handled.** Two parts meeting along a shared line
  each have a CAD edge there (the cylinder–block contact line is the motivating
  case). Both edges are surfaced and referenceable; the anchor's samples resolve
  to the matching curve on **each** touching body (one curve per body), and the
  two can be told apart by their owning part where a consumer needs just one —
  e.g. the picker selects the edge of the **visible** part under the cursor, so
  hiding a part (R6) narrows the selection. (Per
  `Geometric-Entity-Identification` R5; whether a consumer wants one body's curve
  or all of them is the consumer's choice — F2/F3.)

- **R5 — Loud on failure.** If a referenced edge's anchor cannot be resolved, or
  resolves ambiguously beyond what the anchor settles, it is reported loudly and
  names the offending reference — never silently skipped or mis-applied
  (`Geometric-Entity-Identification` R6, loud-safety-net convention).

- **R6 — Coexists with faces, vertices, and per-part visibility.** Edge picking
  is a separate mode with its own persisted pick list; edge picks never collide
  with face or vertex picks (`E#` vs `F#`/`V#`). Per-part visibility checkboxes
  hide a part's edges in lockstep with its faces, and (because VTK pickers honor
  visibility) a hidden part's edges are not pickable. Camera rotation, view
  presets, reset, and wireframe continue to work in edge mode.

- **R7 — Non-destructive identity layer.** Picking an edge — or editing its
  label — changes nothing in any saved/exported artifact. Producing edge
  **containers** in the mesh output is the separate `Edge-MeshEntityContainer`
  feature; applying mesh **control** along an edge is the separate
  `Edge-Mesh-Controls` feature. This feature delivers selection (with editable
  labels) + a resolvable reference only.

- **R8 — Discoverable headlessly.** For a model driven from a config file (no
  viewer), the system can enumerate the model's edges with enough geometry to
  author a reference — each edge's `E#` and its location, reported in the model's
  own coordinate space — the same inventory that already lists faces and
  vertices (`app_cli --list-entities`). Picking in the 3D view (R1) is the GUI
  equivalent; both reach the same geometric anchor. (Per
  `Geometric-Entity-Identification` R7.)

## User-facing scenarios
- **GUI, line-contact model:** the user builds
  `hertzian_cylinder_on_block_quarter_symmetry`, opens Pick Edges, and clicks the
  contact line on the cylinder (and, if they hide the cylinder, on the block).
  The overlay shows `Edge 1 [E#]`. (Consuming that pick is F2/F3.)
- **Headless, the resolvable contract:** `anchor_for_pick(data, "E#")` returns an
  edge anchor; `GeometricResolver.resolve_edge(anchor["samples"])` returns the
  matching gmsh curve(s) — one per touching body for the coincident contact edge.
- **CLI, no viewer:** the author runs `app_cli <model> --list-entities`, reads
  the contact edge's `E#` and location from the listing, and references it in the
  YAML config — the workflow F3's contact refinement and F2's edge owners use.

## Out of scope
- **Exporting edge meshEntityContainers / owners** — that is
  `Edge-MeshEntityContainer` (F2). This feature stores the picks (and lets the
  user edit their labels), but does not write them to the mesh output, merge
  them into `entity_owners`, or add edge-owner parsing to the CLIs. Rename now,
  export later.
- **Edge mesh controls (local / contact refinement on edges)** — that is
  `Edge-Mesh-Controls` (F3).
- **Picking edges in the volumetric *mesh* viewer** — this is the surface CAD
  geometry viewer; the mesh viewer is display-only (`Per-Part-Mesh-Visibility`).
- Changing element generation, mesh quality, or the geometric resolver itself
  (already edge-capable).

## Decisions
- **Mirror the face picker, not the vertex picker.** An edge is a 1-D cell, so
  the closest analog is the face cell-picker (`vtkCellPicker` over line cells
  with an `edge_index` cell array + `edge_pids` field array), which gives a robust
  click target along the whole curve. The vertex picker's point-glyph approach is
  the wrong fit for a 1-D entity.
- **Reuse the edge geometry already in the model.** Edge polylines come from each
  model's `edgeList[].vertexLocations` — the discretized points
  `converter/_freecad.py` already produced (`edge.discretize`) — transformed to
  world space like vertices. No new tessellation.
- **Identity is geometric.** A referenced `E#` becomes a coordinate-sample anchor
  the resolver matches; `E#` itself is never a resolution key
  (`Geometric-Entity-Identification`).
- **Separate mode, separate list.** Following the Pick-Faces/Pick-Vertices
  decision (`Vertex-MeshEntityContainer`), edge picking is its own menu mode with
  its own persisted `_picked_edges` list; the three lists are merged only by the
  consumers that need them (F2).
- **Discoverability is in scope; consumption is not.** Listing edges in the
  headless inventory belongs with the identity layer (as the manifest did in
  `Geometric-Entity-Identification`), because the CLI/YAML path is how these
  analysis models are driven. Parsing an edge reference *into* an owner or a
  refinement is the consumers' job (F2/F3), not this feature's.

## Success criteria (behavioral)
- The contact-line edge of `hertzian_cylinder_on_block_quarter_symmetry` is
  pickable in the GUI: clicking it highlights the edge and the overlay shows its
  `E#`.
- Headless: a referenced `E#` → edge anchor → resolver yields the correct
  curve(s); on the assembly, the coincident contact edge yields exactly one curve
  per touching body, and a bad/absent reference fails loudly.
- `app_cli --list-entities` lists the model's edges (`E#` + location) next to its
  faces and vertices, so an author can reference the contact edge from a config
  with no viewer.
- Edge, face, and vertex picks are independent and never collide; hiding a part
  excludes its edges from picking.
- Nothing saved/exported changes as a result of picking an edge.
