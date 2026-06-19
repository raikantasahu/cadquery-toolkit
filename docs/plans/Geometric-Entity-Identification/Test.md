# Test Plan: Geometric Entity Identification

Tests verify the behaviors in `Feature.md` (R1–R10 + success criteria). They are
written so the resolution logic is exercised **headlessly** (a STEP + gmsh, no
display); GUI picking is the only manually-verified part.

## Oracle — how we know a resolution is "correct"
Identity is geometric, so the oracle is geometric, and **independent of the
resolver's own machinery**:
- A reference resolves to a mesh entity; that entity's geometry — vertex
  coordinate, edge endpoints/length, or face centroid+area — must match the
  reference's geometry within tolerance.
- Where a ground-truth entity is known by construction (e.g. "the face at z=0",
  "the contact-pole vertex", "the block's fixed bottom"), the resolved entity
  must be that one.
- For owner/container output, the **node/element set** attached to a reference
  must be exactly the set classified on the expected geometric entity (compare
  against the entity's own nodes/elements, not against a hard-coded id) — and the
  expected set includes the entity's **boundary** nodes (a face's bounding
  edge/vertex nodes), matching the container's include-boundary semantics, so the
  baseline is not interior-only.
- The oracle's match tolerance is tight and scale-relative (≈ bbox-diagonal ×
  1e-6), independent of — and tighter than — the resolver's own (possibly
  adaptive) tolerance, so a test "match" is strict.
- **No circularity via the manifest.** When references are authored from the
  manifest (R7), the manifest is first validated as independent ground truth:
  its per-dimension entity counts equal gmsh's, and each reported descriptor
  matches gmsh's own geometry queries (`getValue` / `getCenterOfMass` /
  `getMass`). Only then is it used to author references.

This oracle deliberately does **not** trust entity tags/PIDs, since those are the
thing under test.

## Fixtures
- **F-assembly:** the quarter-symmetry Hertz assembly (sphere octant + block) —
  the multi-part case where the picker's entity order differs from gmsh's
  (vertices reorder; this is the case that fails today).
- **F-curved:** a single curved part (full hemisphere / cylinder_with_holes) —
  curved faces, holes, closely spaced edges.
- **F-twocubes:** two unit cubes touching at a face — coincident interface
  faces/edges/vertices (disambiguation), and a controlled split/merge probe.
- **F-external:** real foreign-source STEP from the NIST PMI set at
  `Models/NIST/NIST-PMI-STEP-Files` (AP242 and AP203). Verified to import cleanly
  into gmsh as single-volume solids at real scale with rich topology, e.g.
  `nist_ctc_01` / `nist_ctc_04` (machined parts, ~117 / ~484 faces),
  `nist_ftc_06` (fastener, ~187 faces). Genuine same-geometry / different-
  provenance pair (verified): `nist_ctc_01` **AP203 with-PMI vs AP203
  geometry-only** — both 139 faces, identical bbox. (NB: AP242 ctc_01 is a
  *different* geometry — 117 faces, different bbox — not a flavor of the AP203
  part, so don't pair across APs.) These have no picker (not app-generated), so
  references come from the manifest (the CLI path).
- **F-scaled:** F-curved (or a NIST part) scaled down and up (e.g. ×0.001 and
  ×1000) — scale robustness.
- **F-multipart:** a clean 3+ part assembly whose parts only touch or are
  separate (e.g. a 3-box stack) — stays 1:1; exercises part-qualifier
  disambiguation and per-part (`P#`) identity beyond the 2-part minimum.
- **F-instanced:** `bolted_single_lap_joint` — the same plate object is placed
  twice (bottom/top), so CADModelData stores one plate *definition* + two
  `childComponents`, while gmsh's flattened STEP has two plate solids. Counted per
  definition it looks like `(48,78,36)` vs gmsh `(58,93,43)`; counted per
  *instance* it is 1:1 `(58,93,43)`. Exercises that the count oracle expands
  instances and that the converter's dedup is lossless. (Earlier mislabeled an
  "interpenetration" non-1:1 case — that was a counting error, not splitting.)

## Test groups

### T0 — 1:1 mapping assumption holds (precondition for R4)
The feature's contract assumes gmsh preserves CAD topology one-to-one. Pin it:
for each app fixture (F-assembly, F-curved, F-twocubes, F-instanced), the meshed
model's boundary-entity counts per dimension equal the CAD topology's —
CADModelData vertex/edge/face counts vs gmsh point/curve/surface counts. The CAD
count is taken **per instance** (expanding `childComponents`, since CADModelData
dedups identical part definitions while gmsh flattens instances). **Pass:** counts
match 1:1; a mismatch fails **loudly**, signalling that gmsh genuinely split or
merged entities and the 1:1 contract no longer holds for that model — a
precondition failure, not a silent drift. F-instanced specifically proves that
once instances are expanded, an instanced assembly *is* 1:1 (the earlier
"interpenetration breaks 1:1" was a definitions-vs-instances miscount).

### T1 — Source independence (R1)
Take `nist_ctc_01` in two files of the same geometry, different provenance —
AP203 with-PMI vs AP203 geometry-only (verified equal face count + bbox). Author
references by computing each anchor directly from one file's geometry (the
harness's own gmsh queries — the independent ground truth the oracle uses, so no
manifest needed) and resolve them against the other file; results must match. Also resolve against
`nist_ctc_04` / `nist_ftc_06` to exercise foreign parts the app never produced.
(The manifest is the *user-facing* way to author the same references —
exercised in T6 and the CLI path.) **Pass:** identical geometric results
regardless of source or STEP flavor.

### T2 — Entity kinds (R2)
For F-assembly and F-curved, reference at least one vertex, edge, face, and part,
and resolve each. Include an edge that shares an endpoint with several other
edges (so an endpoint-only match would be ambiguous) and a curved edge, to
exercise multi-point resolution. **Pass:** each resolves to the entity whose
geometry matches.

### T3 — Stable across the meshing transform (R3) — the keystone regression
On F-assembly, reference the block's contact vertex and a named block face whose
picker-order index differs from its gmsh-order index (the documented vertex
reorder). Resolve and check geometry. **Pass:** resolves to the correct entity
even though index-based resolution would pick the wrong one. **Fail today** —
this test must fail before the feature and pass after.

### T4 — Coincident-entity disambiguation (R5)
On F-assembly (contact pole shared by sphere + block), F-twocubes (shared
interface face/edges/vertices), and F-multipart (an entity on a chosen part
among several), reference an entity on one specific part. **Pass:** resolves to
that part's entity, not the other's, using the owning-part qualifier; a contact
reference (no part qualifier) resolves to both; on F-multipart the chosen part's
`P#` identity resolves to the correct volume.

### T5 — 1:1 self-check & loud deviation (R4, R6)
- **No match:** reference a coordinate where no entity exists → loud, named
  diagnostic; nothing silently attached.
- **Extent mismatch / would-be merge:** produce a mesh entity larger than a
  referenced CAD entity — fuse two coincident solids (or run duplicate-removal)
  so two faces merge into one surface, then reference one original face; or force
  a larger-entity match synthetically → the extent disagreement is reported
  loudly. (Note: plain healing removes *small* faces, it does not merge large
  ones, so a fuse / duplicate-removal / synthetic trigger is needed.)
- **Two references, one entity:** two distinct references resolving to the same
  mesh entity → reported loudly.
- **Part-qualified miss:** a part-qualified reference whose coordinate is not on
  the named part (wrong part, or a point off that part) → loud, not a silent
  fallback to a near entity on a *different* part.
- **Removed entity:** reference an entity that healing/defeaturing would remove →
  loud, not silent.
**Pass:** every case raises a named diagnostic; none silently mis-attaches.

### T6 — Discoverability / manifest (R7)
Generate the entity manifest for F-external; pick entities purely from the
manifest (coordinates/centroids it reports) and resolve them. **Pass:** the
manifest's per-dimension entity counts equal gmsh's and each descriptor matches
gmsh's own geometry query (so it is valid ground truth); it lists every entity
with a usable geometric descriptor in the model's own coordinate space; and
references built from it resolve correctly.

### T7 — Repeatability (R8)
Resolve the same reference set on F-assembly across repeated runs (and, if
available, across gmsh versions). **Pass:** identical resolved geometry every
time.

### T8 — Scale & proximity (R10)
- Resolve references on F-scaled (×0.001, ×1000). **Pass:** correct regardless
  of scale.
- On F-curved or a NIST part (which have many densely packed real-world
  features), reference two closely spaced entities (adjacent small holes /
  fillet edges). **Pass:** each resolves to the correct one, not its neighbour.
- **Near-miss tolerance:** a reference coordinate perturbed slightly (within the
  resolver's tolerance) still resolves to the intended entity; perturbed beyond
  it, resolution fails loudly rather than snapping to a neighbour.

### T9 — Names as optional aid (R9)
Resolve on a STEP that carries entity names and on one that does not (or has
misleading names). **Pass:** correct either way; names never required and never
override a geometric mismatch.

### T10 — Parametric invalidation (Decisions) — DONE
On an app parametric model, make references, change a parameter so the geometry
moves, and re-resolve the stale references. **Pass:** stale references are
flagged/invalidated (loud), not silently resolved to whatever now sits nearby.
Covered by `app/tests/test_t10_parametric_invalidation.py`: a length×1×1 bar
exported at length=2 then re-evaluated at length=3 (the +x face moves a full
unit, ≫ resolver tolerance); stale vertex/edge/face references each raise
`EntityResolutionError`, and re-made references against the new geometry resolve.

### T11 — Consumer end-to-end (success criteria)
Through the actual consumers on F-assembly:
- **Owner/container save** for a **face**, an **edge**, and a **vertex** owner.
  The vertex/edge owner-container path is the *confirmed latent bug*, so verify
  each saved container's node set is exactly the set on the expected entity
  (boundary nodes included — see Oracle), not the wrong entity's.
- **Cap-face extrusion** — the cap resolves to the intended face.
- **Refinement anchor** — local/contact refinement lands on the intended
  vertex/part.

Repeat the owner and refinement cases on F-external via the CLI/config path.
**Pass:** correct attachment for face, edge, and vertex owners on both; the
multi-part case that fails today now passes.

## Priority / acceptance
- **Must-pass core** (the silent-failure class is gone): **T0** (1:1
  precondition), **T3** (keystone ordering regression), **T11** (owner / cap /
  refinement consumers, including the vertex/edge container bug).
- **Broaden coverage:** T1, T2, T4–T10.
- **Status (2026-06-18):** T0–T11 all have headless tests and pass in the
  `cadquery` env (48 passing). T10 was the last to land. Remaining acceptance
  item is the manual GUI checks below.
- The feature is **accepted** when T0–T11 pass headlessly in the `cadquery` env
  and the manual GUI checks pass.

## Manual (GUI) checks
Not headless-automatable; verify by hand:
- Pick faces/vertices in the 3D view, generate + save the mesh, and confirm
  (via the headless oracle on the saved file) the picked entities attached
  correctly.
- The pick→resolve path behaves the same as the equivalent headless reference.

## Harness / how to run
- Headless tests run in the `cadquery` conda env against gmsh and introduce the
  project's first `tests/` package (pytest); none exists today
  (Architecture-Review T2.3). No display, no GUI required.
- Fixtures are built once (app models via the registry + STEP exporter; NIST
  files used in place). The oracle is computed directly from gmsh geometry
  queries, so assertions are against geometry, never stored ids.
- GUI checks are run by hand, then confirmed with the headless oracle on the
  saved mesh file.
- **Perf guard:** resolving references for all faces of the largest NIST part
  (~484 faces) should complete quickly; a gross slowdown signals a missing
  spatial prefilter (the bbox step) and an O(n²) scan.

## What is NOT tested here
- Mesh quality / element generation.
- Conformal/fragment meshing (out of scope per Feature.md).
- The larger per-part/hierarchical control behaviors (separate feature) — only
  that *their entity references* resolve correctly.
