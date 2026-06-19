# Feature: Geometric Entity Identification

## Summary
Let a user (or a config file) refer to a CAD entity — a vertex, edge, or face —
and have the system reliably find the corresponding entity in the generated
mesh, **regardless of which tool produced the STEP file**. Identification is by
geometry, not by any tool- or app-specific numbering, so a reference means the
same thing whether the STEP came from this application or from any external CAD
system. Throughout, a *reference* describes an entity by its geometry — not by an
index, tag, or name.

## Why this is needed
Mesh controls and results are attached to specific CAD entities: a face named as
a boundary-condition surface, a cap face for extrusion, a vertex anchoring local
refinement, a part assigned an element size. For any of this to be correct, a
referenced entity must map to the *right* entity in the mesh.

Today that mapping is assumed to hold by position — "the Nth face the user
picked is the Nth surface the mesher sees." That assumption is false in general:
the meshing path re-derives the geometry and does not preserve entity ordering,
and an entity reference produced by this app has no defined relationship to a
mesh produced from a STEP written elsewhere. The observable consequence is
**silent wrong results**: a boundary condition or mesh control silently lands on
the wrong face/edge/vertex, or is silently dropped, with no error and no visible
sign — only an incorrect analysis downstream. This feature removes that class of
silent error by making identity intrinsic to the geometry.

## What it does
- Provides a single, consistent way to **identify** a vertex, edge, or face by
  what it *is* geometrically, and to resolve that reference to the matching
  entity(ies) in the meshed model.
- Serves every consumer of entity identity through the same mechanism:
  - picked **owner/container** faces, edges, and vertices (boundary conditions,
    loads, named regions);
  - the **cap face** for extruded meshing;
  - **local / contact refinement** anchors;
  - **per-entity / per-part mesh controls** (future).
- Works the same for an app-generated model and for an arbitrary external STEP.

## Requirements (behavior)

- **R1 — Source independence.** A reference resolves correctly whether the STEP
  was written by this application or by an external tool. The feature relies
  only on the geometry itself, never on conventions the app's exporter happens
  to use.

- **R2 — All entity kinds.** Vertices, edges, faces, and parts/volumes can each
  be referenced and resolved. Vertices, edges, and faces are the hard cases (the
  meshing path can reorder them); parts/volumes are included for completeness
  and are the easy case, since their ordering is preserved.

- **R3 — Stable across the meshing transform.** A reference still resolves to the
  correct entity even though meshing reorders, renumbers, merges, or splits the
  CAD entities. The reference is tied to the entity's geometry, not to a tag or
  position that meshing is free to change.

- **R4 — One-to-one is the contract; deviations are caught, not silently
  accepted.** On a plain import-and-mesh — what this mesher does — gmsh preserves
  the CAD topology one-to-one: each CAD vertex/edge/face/part becomes exactly one
  mesh entity (verified on representative models — a sphere stays one surface; a
  threaded bolt, point-contact assembly, and face-touching/gapped cubes all map
  1:1). The mapping is 1:1 **per instance**. The one subtlety is part
  *instancing*: when the same part object is placed multiple times (e.g. the
  bolted joint's two identical plates), CADModelData stores one part *definition*
  referenced by multiple `childComponents` with per-instance transforms, while
  gmsh's flattened STEP has one solid per instance. A naive count of unique
  definitions is therefore lower than gmsh's instance count — expected, not a
  violation; counting per instance restores 1:1. (Earlier mis-attributed to
  "interpenetration"; it is a definitions-vs-instances counting matter, not
  splitting.) Other splitting/merging arises only from operations this pipeline
  does not perform (OCC small-feature healing, boolean/fragment ops, explicit
  duplicate removal — off or absent by default), so the feature targets the 1:1
  mapping, flags genuine splits loudly (the self-check below + T0), and does not
  build machinery to reconstruct node sets from split or merged entities. It
  does, however, **verify each resolution**: the matched mesh entity's geometry
  (extent/area and location) must agree with the reference. A disagreement —
  including the would-be merge case where one mesh entity covers more than the
  reference, or two references resolving to the same entity — is reported loudly
  (R6), never silently mis-attributed. This self-check costs little, catches
  resolver bugs, and guards the day healing/defeaturing is introduced.

- **R5 — Disambiguation of coincident entities.** Distinct entities that share a
  location can be told apart, by their owning part where needed — two parts
  touching at a contact point each have a vertex there; two parts meeting at a
  shared interface each have a coincident face. Applies to vertices, edges, and
  faces alike.

- **R6 — Loud on failure or ambiguity.** If a reference cannot be resolved, or is
  ambiguous beyond what the feature can settle, it is reported loudly and names
  the offending reference. It is never silently skipped or silently mis-applied.
  This includes a reference to an entity that is no longer present in the mesh
  because meshing or geometry healing/defeaturing removed or absorbed it.

- **R7 — Discoverability.** For an external/headless STEP where the user has no
  viewer, the system can enumerate the model's entities with enough geometric
  description for a config author to reference them — reported in the imported
  model's own coordinate space, so authored references match without the user
  reasoning about the file's units. In the GUI, picking in the 3D view serves
  the same purpose.

- **R8 — Repeatability.** The same reference against the same geometry resolves
  to the same entity every time, and is robust to re-running and to differences
  in the meshing toolchain.

- **R9 — Names are not relied on (geometry only).** STEP files do name
  faces/edges/vertices, but the meshing toolchain does not surface usable
  per-entity names (only a non-discriminating shape label), and recovering the
  real names (via an OCC XDE path) would still attach them to mesh entities by
  geometric correlation. So identification is purely geometric and never depends
  on names. Meaningful STEP names, where present, could later be a human-readable
  display aid — never a resolution key.

- **R10 — Scale- and proximity-aware.** Identification works across a wide range
  of model sizes and feature sizes, and reliably distinguishes distinct entities
  that lie close together (small fillets, closely spaced holes). What counts as
  "the same place" adapts to the model's scale rather than being a fixed
  absolute distance.

## User-facing scenarios

- **GUI, app-generated model:** the user picks faces/vertices in the 3D view to
  name owners, choose a cap face, or anchor refinement; those selections resolve
  to the correct mesh entities when the mesh is generated and saved.

- **CLI, app-generated STEP:** a config references entities (e.g. by geometry, or
  by names when available) and they resolve correctly.

- **CLI, external STEP:** the user lists the model's entities, references the
  ones they want in the config, and they resolve correctly — even though the
  file was never touched by this application.

## Out of scope
- Changing how elements are generated, or mesh quality.
- The larger hierarchical / per-part *element-type/method* controls (separate
  effort); this feature is the identity layer those will build on.
- Defining new mesh-control features themselves; this feature only makes the
  entity references they use correct.
- Tracking an entity's identity *across a change to the geometry itself*. A
  reference is made against a particular geometric state; when a parametric
  model is re-evaluated with different parameters, references are invalidated
  and must be re-made (see Decisions).
- Persisting selections across sessions (see Decisions).
- Conformal / shared-interface meshing. The current pipeline imports and meshes
  each solid non-conformally — geometry is retained one-to-one and touching
  parts get duplicate interface nodes (the right default for contact). Making a
  mesh conformal requires a boolean *fragment* that replaces geometry with new
  entities (new tags, shared non-manifold faces); that is the trigger for the
  split/new-geometry case in R4 and is out of scope here.

## Decisions
- **Parametric re-evaluation — invalidate and re-make.** When an app model's
  parameters change, the geometry moves and existing references are considered
  invalid; the user re-picks. No automatic best-effort re-resolution against the
  new geometry, and no expressing references against named features (for now).
- **Selection persistence — not supported.** A set of references (owners, cap
  face, refinement anchors) lives only for the current session/run; it is not
  saved with the model or config across sessions.
- **Manifest — in scope.** The entity-listing/discovery capability (R7) is part
  of this feature, not a separate utility.

## Success criteria (behavioral)
- A boundary-condition face, cap face, refinement anchor, and per-part reference
  each resolve to the correct mesh entity on a multi-part assembly where entity
  ordering differs between the picker and the mesh — the case that silently
  fails today.
- The same references resolve correctly on an equivalent STEP produced by an
  external tool.
- An unresolvable or ambiguous reference produces a loud, named diagnostic
  rather than a silent wrong attachment.
- Each referenced CAD entity resolves to exactly one mesh entity whose geometry
  matches it; any deviation (no match, ambiguous match, or a matched entity
  whose extent disagrees) is reported loudly rather than silently mis-attributed.
