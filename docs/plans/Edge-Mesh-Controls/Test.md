# Test Plan: Edge-anchored mesh controls

Tests verify `Feature.md` (R1–R5), **headlessly** in the `cadquery` env: build a
model, apply an edge refinement, mesh, and assert the element sizing near the
edge from the generated mesh. The GUI add-refinement click path is the only
manual part.

## Oracle — how we know the edge refinement "worked"
Checked against the generated mesh, not the field bookkeeping:
- **Finer along the whole curve (the R1 measure).** Take the 1-D mesh nodes gmsh
  classifies *on* the resolved contact curve (`getNodes(1, curve_tag)`), order
  them by their parametric coordinate on the curve, and check the consecutive
  spacing is ≈ `fine_size` at **every** gap — a direct, version-stable measure of
  whole-length uniformity (a lumpy/under-sampled field shows gaps ≫ `fine_size`
  between its samples and fails). This beats a 3-D nearest-neighbour scan of
  "near-curve" nodes, which is noisy and doesn't pin uniformity along the length.
- **Graded away.** Elements more than `radius` from the line stay ≈ `element_size`.
- **More elements.** The same mesh with the refinement has materially more
  elements than without it (the field forced subdivision along the line).
- **Both bodies (contact scope).** Near-curve refinement appears on the
  cylinder's *and* the block's nodes (the coincident contact line drives both).
- **Localized (local scope).** A `local` edge refinement refines only the chosen
  body; the other body's element sizes are unchanged from the unrefined mesh.

## Fixtures
- **F-quarter:** `hertzian_cylinder_on_block_quarter_symmetry` — the contact-line
  edge is the primary anchor (R1/R2). It is a CAD edge *only because* the `x=0`
  symmetry cut realizes the contact line as one (Feature Decisions) — which is
  what makes this the right fixture. Discover its `E#` geometrically (samples on
  `x=0, z=-cylinder_radius`), reusing the F1/F2 approach.
- **F-box:** `box-10x20x30` — a single straight edge, simplest R1 + the local
  (single-body) case.

## Test groups

### T1 — Core: edge refinement makes a finer mesh along the curve (keystone)
Build the `RefinementSpec` edge variant directly (no CLI/GUI), mesh F-quarter
with a `contact` edge refinement on the contact line, and compare to the same
mesh without it: (a) more elements; (b) the nodes *on* the resolved contact
curve (`getNodes(1, tag)`, ordered by parametric coordinate) are spaced ≈
`fine_size` at every consecutive gap — R1 whole-length uniformity, not just at
the ends; (c) elements farther than `radius` ≈ `element_size`. **Pass:** all
hold; the field is sourced from `CurvesList` (the resolved contact curves), not
points.

### T2 — Contact scope hits both bodies (R2)
On F-quarter the contact edge resolves to both bodies' coincident contact curves;
the nodes on **each** body's contact curve (`getNodes(1, tag)`, the per-body
metric) are spaced ≈ `fine_size` along the full length. **Pass:** both bodies'
contact curves refined the whole way along.

### T3 — Local scope refines one body (R2)
A `local` edge refinement on F-quarter's contact edge, restricted to one body via
`part_index`, refines only that body: the targeted body's contact-curve nodes
(`getNodes(1, tag)`) are spaced ≈ `fine_size`, while the **other** body's
coincident contact curve stays ≈ `element_size` (unchanged from the unrefined
mesh). This pins the local-on-a-coincident-edge behavior — `resolve_edge` returns
both curves, but the `Restrict` confines the field to the chosen volume. **Pass:**
target body refined along the line; non-target body unchanged.

### T4 — Composition + non-destructive (R4)
An edge refinement plus a vertex refinement plus `relativeSagTolerance` together
yield the per-region minimum size (the `Min` field); the edge refinement doesn't
disturb sizing away from its radius. **Pass:** min-size-wins where regions
overlap; far-field unchanged.

### T5 — Registry CLI by edgePid (R3)
`app_cli` with `refinements: [{scope: contact, edgePid: E#, fineSize, radius}]`
produces the finer mesh (assert element-count increase + a finer near-curve
region). **Pass:** the run succeeds and the mesh is refined along the line.

### T6 — Foreign STEP by samples (R3)
`mesh_step_model` `mesh.contactRefinement: {samples: [...], fineSize, radius}`
produces the finer mesh on the exported STEP. **Pass:** refined along the line.

### T7 — Failure aborts the mesh (R5; refinement raises, unlike F2 owners)
An edge refinement whose anchor resolves to no curve (bad samples / unknown
`edgePid`) **aborts** mesh generation — it does not warn-and-continue. Core: a
named `MeshValidationError` is raised and **no mesh is stored** (`has_mesh()`
stays false / nothing to save). CLI: a **non-zero exit** and **no output file
written**. This is the deliberate contrast with F2 (a bad *owner* warns and the
mesh still saves; a bad *refinement* must produce no mesh at all — never a
silently coarse one). **Pass:** named error, mesh aborted, no output produced.

## Manual (GUI) check
Pick the contact line, add a contact edge refinement, mesh, and view — elements
crowd along the whole contact line on both bodies.

## Priority / acceptance
- **Must-pass core:** **T1** (the keystone — finer near the curve) and **T7**
  (loud failure).
- **Broaden:** T2, T3, T4, T5, T6.
- Accepted when T1–T7 pass headlessly in the `cadquery` env and the manual GUI
  check passes.
- **Status (2026-06-25): ACCEPTED.** T1–T7 green (`test_edge_refinement.py`);
  core/CLI/vertex-refinement regression unaffected; manual GUI check passed
  (Add Local/Contact Edge → fine band along the whole contact line on both
  bodies, vertex refinement still works, edge rows round-trip).

## What is NOT tested here
- Mesh quality/validity beyond the sizing change (the hex-validity gate etc. are
  unchanged and tested elsewhere).
- The vertex refinement path (unchanged; covered by existing refinement tests).
- Edge picking/identity/containers (F1/F2).
