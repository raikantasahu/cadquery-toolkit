# Implementation Plan: Geometric Entity Identification

Implements `Feature.md`; verified by `Test.md`. Addresses Architecture-Review
T1.1 (consolidates the earlier standalone resolver design).

## Architecture — a source-agnostic resolver in the mesher core

```
  GUI adapter (cad_app)            CLI adapter (mesh_step_model)
   picks -> geometric anchors       config refs / manifest -> geometric anchors
                 \                          /
                  v                        v
            GeometricResolver  (mesher core, source-agnostic)
              anchor -> gmsh entity tag(s);  build tag<->owner map
                                  |
        meshdata.collect / cap face / refinement consume the map
```

The core may use **only** the imported gmsh geometry (tags + coordinates) — never
CADModelData, app PIDs, or exporter conventions (Feature R1). Adapters translate
their world into geometric anchors and feed the core.

## Core component: `GeometricResolver` (new module `app/mesher/resolver.py`)
Built from the current gmsh model after `GmshMesher._import_geometry()`.

```
class GeometricResolver:
    def __init__(self, tol=None):                 # tol defaults to bbox-diag * k
    def resolve_vertex(self, xyz, volume=None) -> list[int]        # point tags
    def resolve_edge(self, samples) -> list[int]                   # curve tags
    def resolve_face(self, centroid, area=None, edge_anchors=None,
                     facet_samples=None) -> list[int]              # surf tags
    def describe_entities(self) -> list[dict]      # manifest (R7)
    def build_owner_map(self, selections) -> dict[tuple, str]  # (dim,tag) -> owner
```
`edge_anchors` is a list of per-bounding-edge sample lists (so a face can be
resolved from its edges, step 4b). The per-kind self-check (step 6): a **vertex**
checks coordinate distance only; an **edge** checks endpoints + length; a
**face** checks centroid + area.
`selections` = `[(anchor, owner_name, required), ...]`. The resolver is the
**single source of truth**: it returns the `(dim,tag) -> owner` map (gmsh tags
are per-dimension — a surface and a curve can share a number) and the inverse,
and every consumer routes through it — removing all `n±1` / `tag-1` arithmetic.
Two refinements borrowed from retaincad:
- **required vs optional** (per selection): a *required* reference that fails to
  resolve aborts loudly; an *optional* one warns and is skipped. (retaincad's
  `is_required_`.)
- **dedup by resolved-tag-set:** `build_owner_map` keys containers by the sorted
  set of resolved gmsh tags, so two references that resolve to the *same* set of
  entities share one container instead of duplicating it.

## Runtime: identify, then apply (two phases, from retaincad)
1. **Identify** — build the `anchor -> [gmsh tags]` map by geometry once after
   import; optionally load an already-resolved map (persistence) and skip
   anything already identified, so re-runs are incremental and deterministic.
2. **Apply** — emit artifacts *through* the map: owner containers (node sets for
   edge/vertex owners, face/element sets for face owners — our existing
   `MeshEntityContainers`), the cap-face choice, and refinement/size fields;
   dedup containers by the resolved-tag-set key.

Tags are stable from import through `generate(3)` (meshing classifies onto the
same geometric entities), so the map built post-import is still valid at
collect; a container's node/element set is whatever is classified on each
resolved `(dim,tag)` **after** meshing.

## Geometric anchors & keys (per entity kind)
An *anchor* is the geometric content of a Feature.md *reference* — the two terms
denote the same thing (Feature uses "reference", the implementation "anchor").
- **Vertex:** coordinate `(x,y,z)`; optional owning-`volume` to disambiguate
  coincident vertices (Feature R5).
- **Edge:** endpoints + midpoint + a few sampled points along it.
- **Face:** centroid + area + bounding-edge anchors + a few facet samples.

## Resolution recipe (gmsh primitives verified 2026-06-17 on imported OCC)
- prefilter: `getEntitiesInBoundingBox` (returns the whole coincident set);
  projection: `getClosestPoint`; keys: `occ.getCenterOfMass`, `occ.getMass`;
  topology: `getBoundary`, `getAdjacencies`; sampling: `getParametrizationBounds`
  + `getValue`.
Resolve in dependency order **vertices → edges → faces** (the face method
derives from already-identified edges; retaincad uses exactly this order).
1. Prefilter candidates by the anchor's bbox, expanding ×2 until ≥1.
2. Vertex: candidate points within tol of the coord; if several (coincident),
   keep all or filter by `volume`.
3. Edge: project each sample onto candidate curves (`getClosestPoint`); keep
   curves all samples land on within tol (multi-sample → tolerant of an edge the
   mesher split into several).
4. Face — try in order (geometry only; names are not used, see Manifest):
   a. **edges:** surface(s) common to the face's resolved boundary edges
      (`getBoundary`/`getAdjacencies` intersection);
   b. **facet points:** surfaces near the facet samples, converging when their
      summed area is within ~10% of the reference area.
5. Adaptive tolerance: bisect within a bracket (retaincad uses ≈ `tol/256` …
   `tol*256`, ≤10 tries) — for faces, drive the bisection by the area ratio
   (too much area ⇒ tighten, too little ⇒ loosen); for vertices, shrink if too
   many candidates, grow if none.
6. **Self-check + loud guard (Feature R4/R6):** the matched entity's extent
   (area/length, within ~10%) and location must agree with the anchor; no match,
   ambiguity, extent mismatch, or a *required* miss -> raise/log loudly naming
   the anchor. Never the silent `entity_owners.get()->None` that `collect` does
   today.

## Manifest (Feature R7)
`describe_entities()` returns, per gmsh entity: dim, tag, centroid, measure
(area/length), bbox — in the model's own coordinate space. **No name** (see
below). CLI gets `--list-entities`; the GUI gets it visually via the picker.

**STEP names reality check (2026-06-17, refined):** STEP *does* name faces,
edges, and vertices — every `ADVANCED_FACE`/`EDGE_CURVE`/`VERTEX_POINT` in the
NIST file has a non-empty name (faces like `'1581|2095354149'`, edges/vertices
small ints). BUT (1) those names are the authoring CAD system's internal IDs,
source-specific and not portable; and (2) **gmsh's STEP importer drops them** —
`getEntityName` returns only an OCC shape-tree label (`"Shapes/SOLID"`, same for
all faces), not the `ADVANCED_FACE` name. Reading the real per-entity names
needs an OCC XDE / `STEPCAFControl` import path, which gmsh does not use. So the
manifest omits name entirely and the resolver has **no name path** — resolution
is geometry-only (Feature R9). Note that even *with* an XDE/CAF import there is
no name-based shortcut: gmsh has no API to ingest OCC names, so you would read
names via XDE, then still attach each to its gmsh entity by **geometric**
correlation (or fragile import order) and `setEntityName`. Names would thus be a
human-readable *label riding on geometric identity*, never an independent key.
**Geometry is authoritative.**

## Codebase touchpoints (current -> target)
- `mesher/gmsh_mesher.py`
  - `_points_near` / `_build_refinement_field`: the **seed** — already
    coordinate-anchored. Fold `_points_near` into `GeometricResolver.resolve_vertex`
    and have refinement consume the resolver.
  - `_surface_tag_for_pid` (cap face): replace `tag = n+1` with a geometric
    resolve (or a lookup in the resolver's map).
  - `GmshMesher`: own a `GeometricResolver` built after `_import_geometry()`.
- `mesher/export/meshdata.py` (`collect`)
  - **Signature change:** today `collect(..., entity_owners={pid: owner})` and it
    derives `pid = f"V{tag-1}"` etc. to look ownership up — the broken coupling.
    Target: `collect(..., owner_by_tag={(dim,tag): owner})` from
    `build_owner_map`; each `EntityContainer` (output `meshEntityContainers`) is
    emitted by consulting that geometry-resolved map. The `V/E/F/P{tag-1}` string
    is fine as a **self-contained output label** for an entity; it must no longer
    be used to *look up ownership*.
- `cad_app.py` (GUI adapter)
  - `_resolve_vertex_anchor` already turns a picked vertex into `(coord, part)` —
    the template. Generalize: a picked **face** anchor is computed from its
    triangles (the picker's PolyData already carries them) — area-weighted
    centroid, summed area, and a few facet samples; a picked **edge** anchor is
    its endpoints + midpoint + a few samples from its tessellation. All in world
    space.
  - `_build_entity_owners`: produce `[(anchor, owner, required)]` selections, not
    a `F#/V#`-keyed dict.
- `viewer/model_viewer.py` (`create_polydatas_per_part`)
  - Stop minting global `F{n}/V{n}` for the bridge; the GUI passes the picked
    entity's **geometry** to the resolver, so the third numbering is no longer a
    contract. (Reusing converter PIDs is an alternative, but passing geometry is
    cleaner and source-consistent.)
- `mesh_step_model.py` (CLI adapter)
  - Config references entities by geometric anchor (`at: [x,y,z]`, centroid for
    faces) — extend the existing `owners` / `capFace` / refinement parsing; keep
    a gmsh-tag escape hatch; add `--list-entities`.
- **Wiring (who builds the map):** the save helpers
  (`save_mesh_meshdata_json/xml`) take `selections` (`[(anchor, owner,
  required)]`) instead of `entity_owners`. The mesher — which owns the
  post-import resolver — calls `build_owner_map(selections)` and passes
  `owner_by_tag` to `collect`. Adapters build `selections`; **no caller ever
  hands the mesher a PID.**

## Phased delivery (each phase = one PR; tests it must turn green)
- **P0 — Harness + red baseline.** Create the repo's first `tests/` (pytest,
  headless, `cadquery` env). Build fixtures (app exports via registry+STEP
  exporter; NIST in place). Land **T0** (1:1 precondition) green, and **T3/T11**
  as *characterization* tests that fail on today's code. Concrete red repro: on
  F-assembly pick the block's contact vertex (picker `V4`) as a vertex owner,
  save, and assert the saved container's node lands at the **wrong** coordinate
  today (gmsh `V4` = (0,0,-40), not the picked (0,0,-10)) — flips to correct
  after P3.
- **P1 — Resolver core.** `GeometricResolver` (vertex/edge/face + adaptive tol +
  bbox prefilter + self-check/loud guard). Turns green:
  **T2, T4, T5, T8, T9**, and the **core of T1** (anchors computed directly from
  gmsh and resolved across NIST flavors — the manifest-authored / CLI half is
  P2). Pure core, no consumer wiring yet.
- **P2 — Manifest + CLI.** `describe_entities` + `--list-entities` + geometric
  config refs. Turns green: **T6**, and the manifest/CLI half of **T1**.
- **P3 — Route consumers (closes the bug).** Build the `(dim,tag)<->owner` map
  once after import; route `collect` owners + `_surface_tag_for_pid` + refinement
  through the resolver. Turns green: **T3, T11** (the must-pass core), **T7**.
- **P4 — GUI adapter + viewer.** Picks -> geometric anchors; drop the third
  numbering's role in the bridge. GUI manual checks (confirmed via the headless
  oracle on the saved file). **T10** (parametric invalidation) — DONE
  (`test_t10_parametric_invalidation.py`).
- **P5 — Optional/later.** Persist the map for re-runs; per-part controls consume
  the resolver (ties to `Part-Specific-Mesh-Controls.md`).
  - *Dropped from this feature:* the STEP/XDE name accelerator (Feature R9) was
    tried and removed — resolution is geometry-only (commits 05a41bd, 696b1bf).
  - *Moved out:* `growth_rate` is a refinement mesh-control parameter, not an
    identity concern — by the Feature's own "Out of scope" it belongs to the
    mesh-control track (`Part-Specific-Mesh-Controls.md` / the refinement size
    field in `gmsh_mesher._build_refinement_field`), not here.

Acceptance (per Test.md): T0–T11 green headlessly + manual GUI checks; must-pass
core (T0, T3, T11) by end of P3.

## Implementation risks / decisions to settle while building
- **Faces-from-edges ambiguity:** when a face's boundary edges are shared such
  that the common-face intersection isn't unique, fall back to centroid+area+
  facet samples; prove on an adversarial face (Test note).
- **Tolerance defaults:** retaincad's starting points to tune — bbox-relative
  base `tol`, bisection bracket ≈ `tol/256 … tol*256`, ≤10 tries, and a ~10%
  area-ratio acceptance band for faces. The resolver's adaptive tolerance is
  looser than the test oracle's (which stays tight, see Test.md).
- **Perf:** the bbox prefilter must keep resolution sub-quadratic on big NIST
  parts (~484 faces) — Test perf guard watches this.
- **Part order:** `volume` disambiguation assumes assembly order == gmsh volume
  order (verified stable). Keep that assumption explicit; T0/T4 guard it.
- **Periodic/degenerate faces** (cylinders, sphere poles): confirm centroid/area
  + samples resolve them; F-curved covers.

## Out of scope (per Feature.md)
Mesh quality; conformal/fragment meshing; defining new mesh-control features;
the hierarchical per-part element-type controls (this is their identity layer).
