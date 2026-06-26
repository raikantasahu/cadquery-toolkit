# Feature: Edge-anchored mesh controls (refine near an edge)

Status: **shipped** (2026-06-25) — P1 (mesher-core `CurvesList` field) → P2
(CLIs) → P3 (GUI Add Local/Contact Edge), verified per `Test.md` (T1–T7 headless
+ manual GUI). F3, the original motivating ask. Builds on
`Edge-Identity-and-Picking` (F1); independent of `Edge-MeshEntityContainer` (F2).

## Summary
Let a CAD **edge** anchor a local/contact mesh refinement, so the element size
ramps from a fine size *at the edge* up to the global size by a radius away —
the **curve** analog of the existing **vertex** (point) refinement. This is what
the whole edge initiative was for: a finer mesh along the **contact line** of the
cylinder-on-block model, which is an edge, not a point.

## Why this is needed
The mesher already refines around a picked **vertex** (a gmsh `Distance` field
over `PointsList`). Line contact concentrates stress along a *line*; refining
from a single point under-resolves the rest of the contact line, and refining the
whole region wastes elements. Distance-**from-the-edge** puts the fine elements
exactly where the contact gradient is — along the curve — which is the correct
control for a Hertzian line-contact solve. F1 made the contact edge selectable
and F2 made it nameable; F3 makes it *drive the mesh*.

## Why it builds cleanly on what exists
- The refinement field machinery (`Threshold` grading, `Restrict` to a volume,
  the `Min` combine, coexistence with `relativeSagTolerance`) is entity-kind
  agnostic — only the **Distance field's source** differs (points vs curves).
- gmsh's `Distance` field already supports `CurvesList` (+ `Sampling`) right
  beside the `PointsList` the code uses today.
- The edge resolves through F1's anchor (`anchor_for_pick` `E#` → samples) and
  the resolver's `resolve_edge(samples)` → curve tag(s) — the same path F2 uses.

## Requirements (behavior)

- **R1 — Refine from the whole edge.** An edge anchors a refinement whose fine
  band follows the **entire length** of the curve: element size is `fine_size`
  everywhere along the edge and ramps to the global `element_size` by `radius`
  away (distance measured from the curve, uniformly along it — not from a single
  point). This whole-length uniformity is the reason to refine from a curve
  rather than a point: a point refinement crowds elements at one spot and leaves
  the rest of the contact line coarse. Same `fine_size`/`radius` grading as the
  vertex refinement; the difference is the distance source. (The implementation
  must sample the curve densely enough that the band is uniform, not lumpy — the
  acceptance test for this requirement.)

- **R2 — Contact and local scope.**
  - `scope="contact"` refines **every** body along a coincident edge — the
    contact line on both the cylinder and the block — by driving the field from
    all curves the edge resolves to (per `Geometric-Entity-Identification` R5).
    This is the motivating case.
  - `scope="local"` refines **one** body, by restricting the field to that body's
    volume (the same `Restrict` the vertex path uses).

- **R3 — All three sources.** An edge refinement can be specified via the **GUI**
  (pick an edge — F1 — and add a local/contact edge refinement), the **registry
  CLI** (`app_cli` refinement by `edgePid`), and a **foreign STEP**
  (`mesh_step_model` refinement by edge `samples`).

- **R4 — Composes, non-destructively.** Edge refinements combine with vertex
  refinements and `relativeSagTolerance` through the existing `Min` field (the
  smallest size wins), and change nothing else about the mesh away from the
  refined region. Tet/recombined-hex path only (refinements already don't apply
  to the extruded-hex path).

- **R5 — Loud on failure.** An edge refinement whose anchor resolves to no curve
  (or a local one with an out-of-range part) fails loudly with a named
  `MeshValidationError`, never a silently coarse mesh
  (`Geometric-Entity-Identification` R6; the vertex path already raises this way).

## User-facing scenarios
- **GUI:** the user picks the contact line, adds a **contact** edge refinement
  (`fine_size` 0.3, `radius` 2), meshes — the elements crowd along the whole
  contact line on both bodies.
- **CLI (registry):** `refinements: [{scope: contact, edgePid: E5, fineSize: 0.3,
  radius: 2.0}]` on `app_cli`.
- **CLI (foreign STEP):** `mesh.contactRefinement: {samples: [...], fineSize: 0.3,
  radius: 2.0}` on `mesh_step_model`.

## Out of scope
- **Per-body scoping subtlety for local edges.** `resolve_edge` has no volume
  filter (like F2), so a `local` edge refinement selects its body by restricting
  the field to a chosen `part`/volume, not by resolving a single body's curve.
  Adding part-scoped edge resolution is a `Geometric-Entity-Identification`
  enhancement, out of scope.
- **Contact lines that aren't CAD edges.** A contact line interior to a face
  (an un-cut full-body model) has no edge to anchor; refining it needs edge
  imprinting or an arbitrary-curve field — out of scope (see Decisions). F3
  targets the symmetry-reduced models where the cut makes the line an edge.
- **New field types / anisotropy / boundary-layer meshing** — only the existing
  `Distance`+`Threshold`(+`Restrict`) grading, sourced from a curve.
- **Edge picking / naming** — delivered by F1/F2.
- **Extruded-hex refinement** — already unsupported for that path; unchanged.

## Decisions
- **The contact line must be a CAD edge — which the symmetry cut provides.** F3
  refines along an *existing* CAD edge. In the quarter-symmetry model the contact
  line genuinely is one: it lies on the `x = 0` symmetry cut, where the cylinder's
  curved face meets its `x = 0` face and the block's top meets its `x = 0` face
  (F1/F2 resolved exactly these two coincident contact edges). This is not an
  accident of *this* feature — it's why a symmetry-reduced contact model is the
  right setup: the cut realizes the contact line as a meshable edge. For a
  geometry where the contact line falls in the *interior* of a face (a full,
  un-cut cylinder on a full block), there is no edge to anchor to and F3 does not
  apply — that would need edge imprinting or an arbitrary-curve field (see Out of
  scope). So F3 serves symmetry-reduced contact models, the common FE case.
- **Curve analog, shared machinery.** Add an edge anchor to `RefinementSpec` and
  a `CurvesList` branch to `_build_refinement_field`; everything after the
  Distance field (Threshold, Restrict, Min, the sag-tolerance coexistence) is
  reused unchanged.
- **Edge identified geometrically.** The edge rides on F1's sample anchor and the
  resolver's `resolve_edge`; `E#` is never a resolution key — same contract as
  F2's edge owners.
- **Contact = all coincident curves; local = Restrict to a volume.** Contact
  scope sources the field from every curve the edge resolves to (both bodies);
  local scope sources the same curve(s) but restricts the field to the chosen
  body's volume.
- **Refinement failures abort — they do not warn-and-continue (unlike F2
  owners).** An edge refinement that cannot resolve *raises* and aborts the mesh
  (R5), matching the existing vertex refinement path — **not** F2's warn-and-drop
  for owners. The asymmetry is deliberate: a dropped owner merely omits a named
  set (recoverable — the solver notices the set is missing), but a silently
  dropped refinement yields a mesh that is too coarse for the analysis with *no
  visible sign* — the precise wrong-result-with-no-error failure the
  loud-safety-net convention exists to prevent. So refinements fail hard.

## Success criteria (behavioral)
- Meshing the cylinder-on-block with a contact edge refinement on the contact
  line produces elements near that line at ~`fine_size` **along its whole length**
  (not just at the ends), grading to `element_size` by `radius` away, on **both**
  bodies — and more total elements than the same mesh without the refinement.
- The same refinement is expressible from the GUI, `app_cli` (`edgePid`), and
  `mesh_step_model` (`samples`).
- It composes with a vertex refinement and `relativeSagTolerance` (min size
  wins), and an unresolvable edge refinement fails loudly.
