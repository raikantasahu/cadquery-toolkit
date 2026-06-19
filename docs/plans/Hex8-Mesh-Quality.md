# Feature: Better hex8 meshes (extruded hex from a cap face)

Status: **SHIPPED 2026-06-15** (commits 0db6a97, e3fbd31, 7d3639c, 9148b9c,
1d8058d). Delivered: HEX8 inverted-element validity gate; extruded hex8 from a
user-picked cap face (explicit per-layer build landing on the auto-detected
opposite face); GUI in-dialog cap-face picker + reusable `pick_entities`;
MeshData boundary + F/E/V entity-container export for extruded meshes; Mesh
Settings persistence. The original "2D quad algorithms" idea was disproven and
the untangle approach dropped — see the decision trail below.

## CLOSED 2026-06-19 — nothing pending
Confirmed complete; no implementation work remains. The items below are
**optional enhancements / edge cases**, not pending tasks:
- 1–5 (slanted opposite faces, stray-triangle→wedge re-test, per-node perf,
  non-axis-aligned cap, extruded hex20/27) are deliberate limitations / "do only
  if a real model needs it"; verified still-current in code (`_extrusion_topology`
  requires a parallel opposite face; `generate()` rejects extrusion+non-hex8).
- 6–7 (hierarchical controls, multi-part extrusion) are a separate effort tracked
  in `Hierarchical-Mesh-Controls.md`.
- GUI smoke tests 8 & 10 are satisfied: the extruded-hex cap-face Pick flow was
  exercised in the GUI (left-click cap pick → mesh, 2026-06-19); vertex picking is
  covered headlessly and its plan is closed (`Vertex-MeshEntityContainer.md`). 9
  (Mesh Settings persistence) is an independent GUI nicety, not part of this feature.

**Code-location note (Architecture-Review T2.4, commit 9d00d75):** the extrusion
engine described throughout this doc moved out of `GmshMesher` (`gmsh_mesher.py`)
into `app/mesher/extruded_hex.py::ExtrudedHexBuilder`. The methods named below —
`_generate_extruded` (now a thin delegate on `GmshMesher`), `_extrusion_topology`,
`_build_extruded_mesh`, `_clear_non_cap_mesh`, `_cap_tag`, `_apply_cap_sag_field` —
live there now. The earlier `_generate_swept` / `_build_swept_volume` /
`_extrusion_target` / `_build_extruded_volume` names are superseded prototype steps.

## DEFERRED / OPEN ITEMS (accurate as of 2026-06-15)
Extruded-hex refinements (feature is shipped; these are optional/edge-case):
1. Slanted (non-parallel) opposite faces — currently parallel-only. Needs
   "faces-away-along-d" detection + projected-area congruence
   (`cap_area ≈ opp_area·|m·d|`); per-node projection already handles geometry.
2. Stray-triangle→wedge branch in the keep-the-solid build — not separately
   re-exercised (cap recombines to all-quad → all-hex is the norm/verified).
3. Per-node `getNode` perf (#5) — documented in-code with the batched fix; only
   matters past ~10k cap nodes.
4. Non-axis-aligned cap normal — math handles it, never exercised.
5. Extruded hex20/hex27 — extrusion is hex8-only today (dialog greys the section
   for other types; generate() rejects extrusion+non-hex8). Extension: build the
   clean structured hex8 mesh, then raise to order 2 (`setOrder(2)`) — trivially
   valid on flat caps/straight edges, NEEDS verification on curved parts (hole
   circle / cylinder wall) where mid-side nodes land on the curve. Note:
   order-raising wrecked the *subdivision* hex mesh (~19k inverted) but that was
   a distorted mesh; a structured extruded mesh should raise cleanly — prototype
   before trusting.

Separate larger effort — see `Hierarchical-Mesh-Controls.md`:
6. Hierarchical/cascading mesh controls for assemblies.
7. Multi-part extrusion ("several parts each extruded").

GUI re-tests pending a display (logic verified, GTK not driveable headless):
8. Extruded-hex layering + in-dialog "Pick…" flow.
9. Mesh Settings persistence (restore same-model / reset on model change).
10. Vertex-picking smoke test (`Vertex-MeshEntityContainer.md`).

## FINAL DESIGN (implemented)
`GmshMesher.generate` calls `_assert_hex_valid(mesh_type)` after `generate(3)`:
for **HEX8/HEX20/HEX27**, counts inverted elements (minSICN < 0) and raises
`MeshValidationError` if any exist. `mesh_step_model.py` catches it →
`parser.error` (clean CLI failure); the GUI's existing try/except shows a
"Mesh Error" dialog. Tet meshes are unaffected.

Gate covers all three hex orders because sag tolerance was verified to clear
inversions for each (HEX20 7→0, HEX27 1→0 at sag 0.02/0.01) — same
curvature-resolution cause and same fix, so the "increase resolution" message
is correct for all of them.

Rationale (user-driven): an inverted element is a correctness defect, not a
quality gradient — invalid meshes must not ship. And the ROOT CAUSE is
curvature under-resolution, not something a smoother should paper over.

### Key evidence: sag tolerance fixes inversions at the source
RAW subdivision hex8 (NO untangle) on `out.step`, varying sag tolerance:
| sag | elems | inverted | min |
|---|---|---|---|
| None  | 23092 | **1** | -0.010 |
| 0.02  | 35368 | **0** | +0.048 |
| 0.01  | 52232 | **0** | +0.090 |
| 0.005 | 77308 | **0** | +0.086 |

Even the loosest sag tolerance eliminated the inversion — confirming it's a
curvature-resolution artifact. So the gate's message tells the user to raise
resolution (relativeSagTolerance / smaller elementSize), which fixes the cause.

### DROPPED: untangle pass (`UntangleMeshGeometry`)
Earlier prototype ran untangle on HEX8 (1→0 inverted, all-hex preserved). It
"worked" but is best-effort and masks under-resolution — rejected by the user
on principle (can't guarantee validity; hides a WIP state). Not committed.
(Also confirmed: untangle WRECKS second-order — on HEX20 inverted ~19k/23k.)

### DECOUPLED: hex20/hex27 second-order quality is a SEPARATE bug (user, 2026-06-15)
Two distinct issues, not to be conflated:

1. **gmsh `setOrder(2)` blowup (NOT in our pipeline).** Prototyping the "untangle
   first-order, then raise order" idea: order1 untangled = clean (0 inverted), but
   `gmsh.model.mesh.setOrder(2)` on it → **14427/23092 inverted** (min -0.994).
   Same geometry generated *directly* at order 2 gives only 7 inverted → the 2000×
   difference is a defect in gmsh's post-hoc order-raising for recombined hexes.
   **We do NOT call `setOrder` in production** (`_configure_mesh` sets
   `Mesh.ElementOrder=2` before `generate`), so this never affects shipped output.
   Side observation only; nothing to fix on our end.

2. **Real follow-up bug: direct order-2 leaves 7 inverted (pre-existing).** Our
   actual HEX20/HEX27 path (`Mesh.ElementOrder=2` before generate) leaves ~7
   inverted elements on the test assembly. `UntangleMeshGeometry` can't fix these
   (straight-edge only — wrecks second-order). Correct tool is a **high-order**
   optimizer (`optimize("HighOrderElastic")` / `Mesh.HighOrderOptimize`); it's slow
   (killed a run after ~12 min CPU on 23k elems) so needs its own time-budgeted
   experiment. **Tracked as a separate task, decoupled from the hex8 untangle.**

---
## (Prototype findings that led here)

## RESULTS of prototyping (2026-06-15, conda env active, gmsh 4.15.0)
Test geometry: `app/out.step` = a 3-volume assembly (37 surfaces, many 5-corner
faces), size=5.0. Quality metric: gmsh `minSICN` (∈[-1,1]; <0 = inverted = unusable).

| Strategy | Result |
|---|---|
| **Subdivision (current)** | 100% all-hex, 23092 elems. min=**-0.010 (1 inverted)**, mean 0.520 |
| 2D-quad algo 8/9 + full-quad recombine (=3) | **FAILS**: "Full-quad recombination not ready for periodic surfaces" |
| 2D-quad algo 11 + full-quad recombine (=3) | **0% hex — all tets** (3D recombine never engages) |
| 2D-quad algo 8/11 + blossom recombine (=1) | **0% hex — all tets** |
| Transfinite (structured) | **FAILS**: surfaces have 5 corners (not mappable w/o manual decomposition) |

**Conclusion:** on arbitrary/assembly CAD, gmsh's 2D-quad + 3D-recombine path does
NOT yield hexes — it falls back to tets or errors. Subdivision remains the only
reliable all-hex route. The plan's premise (swap 2D algorithm → better all-hex)
does not hold for this geometry.

### What DID work: untangling the subdivision mesh
Post-mesh `gmsh.model.mesh.optimize(...)` on the subdivision hex mesh:

| Optimizer | min | mean | inverted |
|---|---|---|---|
| baseline | -0.010 | 0.520 | 1 |
| + `Relocate3D` | -0.571 | 0.530 | **12 (worse!)** |
| + **`UntangleMeshGeometry`** | **+0.081** | 0.483 | **0** |

`UntangleMeshGeometry` removes the inverted element (the only fatal-for-FEA defect),
turns min Jacobian positive, preserves all-hex topology — small mean cost. This is
the real, deliverable win. `Mesh.Optimize=1` (pre-gen) is a no-op for recombined hex.

### Revised direction (proposed)
1. **Untangle pass** after subdivision recombine for HEX8/20/27 — small, safe, fixes
   inverted elements. Primary recommendation.
2. **Transfinite/extrude** only for simple single-part parametric models we control
   (single box/plate w/ 4-corner faces) — limited; never for assemblies.
Original "quad-recombine flag" is dropped (empirically dead).

---
## (Original plan below — premise now disproven, kept for context)

## Goal
Generate higher-quality hex meshes. **PRIMARY INTENT (do not lose again):** produce
structured hexes by **meshing a face with quads and sweeping/extruding them through
the thickness** (gmsh `extrude(..., recombine=True, numElements=[n])`). This is the
real target — structured, provably-valid hexes for prismatic parts (box, plate,
cylinder).

### PROTOTYPE PROVEN (2026-06-15) — box, gmsh geometry hand-built
Quad cap (transfinite 4×8) → `extrude(numElements=[12], recombine=True)` on a
10×20×30 box vs the current subdivision pipeline, both at size 2.5:
| | swept | subdivision |
|---|---|---|
| elements | **384** (4×8×12) | 8080 (21×) |
| minSICN min/mean | **+1.000 / 1.000** | +0.213 / 0.561 |
Perfect structured hexes, 21× fewer elements. Mechanism confirmed.

### Integration approach DECIDED + PROVEN (2026-06-15)
**Cap face is a MESHER INPUT** (user decision) — the mesher does NOT pick it.
The cap is a surface PID (same `F{n}` scheme as the face picker): picked in the
GUI or given in mesh config (CLI). Auto-detection (old Option A) is rejected.

Proven mechanism on the IMPORTED box STEP:
import solid → find the specified cap face → `occ.remove` the volume (keep faces)
→ `occ.extrude([(2,cap)], normal*thickness, numElements=[nz], recombine=True)`
→ structured hexes. Result: 480 hex8, **min +0.737 / mean 0.904, 0 inverted**.

Cap-meshing method is the quality knob:
- transfinite cap (mappable rectangle) → perfect 1.000 structured grid
- quad-algorithm cap (holed / non-mappable, e.g. plate_with_hole) → ~0.9
Both >> subdivision (0.561).

### Sag tolerance DOES apply to swept hex — for GEOMETRIC FIDELITY (corrected 2026-06-15)
(Earlier note wrongly dropped it. Sag tolerance is not only about inversions; it
governs how closely the mesh follows curved edges. Swept hexes can't invert from a
coarse hole, but the hole becomes a coarse polygon deviating from the true circle —
bad geometry + FEA stress concentrations.)

Mechanism that FAILED: global `MeshSizeFromCurvature` (subdivision-era) coarsens the
flat cap in the extrude path. Mechanism that WORKS: a LOCAL Distance+Threshold field
on the cap's curved edges, SizeMin = sag-limited size (2πR / n_per_circle), SizeMax =
elementSize. Verified on the plate hole (R=5): base elementSize=5 → 7 segments (sag
≈0.50mm); threshold field (sag 0.01) → 21 segments (sag ≈0.056mm), min quality
0.115→0.314.

**Swept-hex controls = `capFace` + `elementSize` (flat in-plane) + `numLayers`
(thickness) + `relativeSagTolerance` (curved cap-edge fidelity, applied LOCALLY).**
Tuning detail: keep the field's flat size = elementSize (don't disable
MeshSizeExtendFromBoundary the way the quick test did, which over-coarsened flats).

### Review fixes (2026-06-15, uncommitted) — opposite-face landing (#2)
Replaced the centroid-thickness heuristic with **opposite-face detection +
per-node projection**: `_extrusion_target` finds the parallel opposite face
(planar, normal ∥ d, farthest along d; equal-area congruence check), and
`_build_extruded_volume` projects each cap node along d onto that face's plane
so the far layer lands EXACTLY on it (clean integer z-planes, not a guessed
thickness). Either cap pickable; non-prismatic picks (e.g. the hole wall)
rejected with a clear message. Verified on plate F4/F2 (uniform layers,
inverted=0) and F6 (rejected).

DEFERRED to the entity-container phase (user calls, 2026-06-15):
- **Slanted (non-parallel) opposite faces** — currently parallel-only (noted in
  `_extrusion_target`). Would need: detect by "faces away along d", projected-area
  congruence (`cap_area ≈ tgt_area·|m·d|`), per-node travel (projection already does).
- **Boundary node ↔ edge/vertex association** — along-d projection already LANDS
  cap-boundary nodes on the opposite boundary edges/vertices (side faces ruled
  along d), but they aren't TAGGED to those edges/vertices. That tagging is the
  same work as emitting MeshEntityContainers for the extruded mesh (#1 below).

Review issues #3/#4/#6 FIXED (2026-06-15):
- #3 non-planar cap rejected ("cap face must be planar… got 'Cylinder'").
- #4 wedge fallback VERIFIED (all-triangle cap → valid wedge6, uniform layers,
  0 inverted). Normal use recombines to all-quad → all-hex; wedges only if a
  stray triangle survives.
- #6 generate() rejects extrusion with non-hex8 mesh_type.
#5 per-node getNode perf: measured ~25 us/node, linear (100→2.5ms, 1000→25ms,
40k→0.65s, 200k→3s). Negligible for typical caps; DEFERRED with an in-code PERF
note in `_build_extruded_volume` documenting the threshold (~10k nodes) and the
batched fix (`getNodes(2, cap, includeBoundary=True)`, ~100x at scale).
#1 container export for extruded meshes — DONE (2026-06-15, uncommitted).
Rearchitected the extruded path to KEEP the original solid and assign the
layered mesh, fully classified, onto its entities (so collect() reads it):
- `_extrusion_topology` resolves vol/opp/d/q/m + cap↔opposite correspondence
  (corr_edge: cap edge→side face+opp edge; corr_vert: cap vertex→side edge+opp
  vertex) from the solid's boundary topology.
- `_generate_extruded` meshes the cap on the solid, `_clear_non_cap_mesh` empties
  the rest, `_build_extruded_mesh` sweeps the cap mesh into n layers with
  hierarchical classification (face-interior→volume/opp face; edge→side
  face/opp edge; vertex→side edge/opp vertex), emitting hex/wedge columns,
  side quad strips, opp/side edge lines.
- collect() now emits boundary faces/edges + F/E/V containers keyed to PIDs.
Verified end-to-end: generate()→save_as_meshdata_xml gives 5 containers
(cap/opp/side faces, opp edge, corner vertex). Conformal (0 coincident nodes),
0 inverted. Also resolves point-2 (boundary nodes associated to opp edges/vertices).
Fixed defect: a closed cap edge's (e.g. hole circle) SEAM VERTEX was omitted
(getBoundary of a closed edge returns no vertices), so its node was misclassified
onto the opposite face (cap 4770 vs opp 4771). Fix: take the cap's RECURSIVE
boundary for cap_verts in both `_extrusion_topology` and `_clear_non_cap_mesh`.
Now cap==opp face node counts (symmetric), conformal, valid. Generalizes to any
closed cap edge (holes, full-disk outer boundary, pipe annuli).
Remaining: stray-triangle→wedge branch in the new build mirrors the verified
logic but not separately exercised (cap is recombined → all-quad).

### BUGFIX (2026-06-15, uncommitted) — non-uniform layers + GUI workflow
GUI testing found two issues:
1. **Correctness**: numLayers=5 gave 5 layers in some areas, 4 in others.
   Root cause: `occ.extrude(numElements=[n])` is only a SOFT hint — gmsh's 3D
   mesher ignores it (made one volume, hex-meshed it non-uniformly: 4 full layers
   + sliver). `geo.extrude` can't operate on an OCC face (returns empty). Fix:
   **mesh the cap in 2D, then build the hex layers EXPLICITLY** (`_build_swept_volume`):
   read cap quads → orientation sign-test (flip winding for +Jacobian) → layered
   nodes + hex8 (tri→wedge6) → addDiscreteEntity + addNodes/addElementsByType.
   Verified: uniform layers (every layer equal count), 0 inverted, numLayers exact
   (3→3, 5→5), sag still refines. pyvista extraction works on the discrete volume.
   KNOWN LIMIT: discrete volume has no boundary surface entities, so MeshData
   export (collect) yields hexes but no boundary faces/edges/entity-containers.
2. **GUI workflow**: cap face now picked from the mesh dialog itself via a "Pick…"
   button (close→pick→reopen with settings preserved via `initial`), not pre-picked.

### BUILT — swept-hex via compound `extrusion` config (2026-06-15, uncommitted)
`ExtrusionSpec(cap_face, num_layers)` dataclass + `GmshMesher.generate(extrusion=)`
→ `_generate_swept`: locate cap (PID `F{n}`→tag n+1) → inward normal + thickness
(2× cap-to-centroid) → drop volume → quad-mesh cap (algo 11) with local
Distance+Threshold sag field on curved edges → `occ.extrude(numElements=[layers],
recombine=True)` → validity gate. CLI parses a `mesh.extrusion:` block.
Config:
```yaml
mesh:
  elementType: hex8
  elementSize: 5.0
  relativeSagTolerance: 0.01
  extrusion: { capFace: F4, numLayers: 3 }
```
Verified on plate_with_hole-300x100 (cap F4): direct + CLI both all-hex, 0 inverted,
mean 0.934; sag lifted near-hole min 0.115→0.609. CLI wrote 10206 hex8.

(Historical note — GUI wiring and holed-cap end-to-end are now DONE; see the
DEFERRED/OPEN ITEMS list at the top for what actually remains. Multi-part is in
docs/plans/Hierarchical-Mesh-Controls.md.)

### Remaining design for the real feature
- Input plumbing: cap face PID → gmsh surface tag (`tag = PID_index + 1`),
  reusing the picker. New GUI "Pick Cap Face" / config `capFace: F_k`.
- Thickness + direction: sweep along cap outward-normal (into solid) by distance
  to opposite face; `nz = round(thickness / elementSize)`.
- Cap quad strategy: transfinite when mappable, else algo-11 quad.
- Swept mesh still passes the validity gate (0 inverted here).
- Prismatic assumption: if user picks a cap on a non-prismatic solid the extrude
  won't match; rejected by `_extrusion_topology` (planar cap + parallel congruent
  opposite face required).
- (Holed cap end-to-end is now DONE; non-axis-aligned normal still untested — see
  the DEFERRED/OPEN ITEMS list at the top.)

What got built so far is a *correctness floor* for the existing subdivision method
(reject inverted hexes — see below), which is complementary but separate from the
swept-quad method above. The swept-hex feature still needs prototyping + design:
identify cap face + thickness direction (or build the extrusion in gmsh from the 2D
profile) rather than meshing the opaque imported STEP solid.

## Findings from investigation (2026-06-13/14)
- **Current HEX8 path is the problem** — `app/mesher/gmsh_mesher.py:491-496` sets:
  ```python
  Mesh.RecombineAll = 1
  Mesh.Recombine3DAll = 1
  Mesh.Recombine3DLevel = 2
  Mesh.SubdivisionAlgorithm = 2   # tet mesh -> split each tet into 4 hexes
  ```
  `SubdivisionAlgorithm=2` builds a tet mesh then splits each tet into 4 hexes →
  guaranteed all-hex but many distorted/irregular elements. This is the catch-all
  fallback, not a quality method.
- **The mesher sets NO 2D-algorithm knobs** — `grep` for `Mesh.Algorithm` /
  `RecombinationAlgorithm` / `BoundaryLayer` in `gmsh_mesher.py` = nothing. So it's on
  gmsh defaults for surface meshing.
- gmsh DOES support mapped/structured meshing (transfinite + recombine) and extrusion,
  but has **no robust general unstructured all-hex mesher** and no auto hex-block
  decomposition. See sibling note context.

## Quality routes (best → fallback)
1. **Clean quad surface → extrude + recombine → hex8** (best for prismatic parts:
   plates, cylinder). `gmsh.model.geo.extrude(..., recombine=True)` with layers.
2. **Transfinite** for single-block mappable solids (boxes). Holes break single-block
   mappability → need partitioning.
3. **Subdivision (current)** only as the arbitrary-geometry fallback.

## 2D quad algorithm knobs to prototype (the immediate task)
Surface-meshing options that produce boundary-aligned, layered, full-quad faces:
- `Mesh.Algorithm`: **8** (Frontal-Delaunay for Quads), **9** (Packing of
  Parallelograms — boundary-following rows), **11** (Quasi-Structured Quad, gmsh ≥4.8,
  near-structured full quad — try first).
- `Mesh.RecombineAll = 1`
- `Mesh.RecombinationAlgorithm = 3` (Blossom full-quad; 1 = blossom)
- Optional: `BoundaryLayer` field for literal edge-anchored quad layers (CFD-style band;
  doesn't fill+merge a whole face by itself).

Minimal experiment:
```python
gmsh.option.setNumber("Mesh.Algorithm", 11)
gmsh.option.setNumber("Mesh.RecombineAll", 1)
gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 3)
```

## Plan (to flesh out on resume)
1. Add a config flag to `GmshMesher` (and the YAML mesh config / `mesh_step_model.py`)
   selecting the hex8 strategy, e.g. `hex8Strategy: subdivision | quad-recombine |
   extrude` (default = current `subdivision` so nothing regresses).
2. Implement `quad-recombine`: set `Mesh.Algorithm` (param, default 11) +
   `RecombinationAlgorithm=3` + `RecombineAll`/`Recombine3DAll`; drop SubdivisionAlgorithm.
3. (Stretch) `extrude` strategy for prismatic parts — mesh the 2D profile with quads,
   extrude along thickness with `recombine=True`.
4. Compare element quality (gmsh quality stats / min scaled Jacobian, element count) on
   `box-10x20x30` and `cylinder-with-holes` between strategies; capture numbers here.

## Verification (conda-env rule)
- The `cadquery` conda env runs the heavy stack (gmsh 4.15.0). The user enabled it this
  session; with it active, run `mesh_step_model.py <step> <cfg>` and inspect output +
  gmsh quality. Otherwise ask the user to run.
- Test inputs on disk: `app/out.step`, `app/mesh_config.yaml`,
  `app/mesh_config-for-cylinder-with-holes.yaml`.

## Open questions for the user (resume)
- Which parts matter most for hex (plates? cylinder? all)?
- OK to keep `subdivision` as default and gate new strategies behind the flag?
