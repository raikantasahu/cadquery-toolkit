# Architecture Review (2026-06-19)

> **Status: COMPLETE (2026-06-19).** Audit conducted 2026-06-17; closed out
> 2026-06-19. Every finding below is resolved or an
> intentional won't-fix. Tier 1: T1.1 (Geometric-Entity-Identification), T1.2
> (`2ec31d0`), T1.3 (`d6e97d8`). Tier 2: T2.1 (Core-UI-Separation), T2.2
> (`9ffdd20`), T2.3 (test suite), T2.4 (`9d00d75` — `ExtrudedHexBuilder` +
> `collect()` split). Tier 3: silent failures + logging (`406516c`), duplication
> (`a91bdb1`, `5d7b89f`), dep-flag inconsistency (CLI `HAS_GMSH` check + exception
> type normalized to `ImportError`). The temp-STEP round-trip is a deliberate
> design choice (kept), not a defect — see that item.

Read-only audit of `app/`. Lower layers (`converter`, `mesher`, `exporter`,
`importer`) are cleanly factored with a typed domain model and isolated FreeCAD
dependency. Issues cluster around (1) entity identity, (2) gmsh session
lifecycle, (3) app-layer structure/testability. Severities: HIGH/MED/LOW.
Several Tier-3 items violate the "loud safety nets, never silent" rule.

## Tier 1 — latent correctness bugs (silent)

### T1.1 No single source of truth for entity identity (HIGH)
`V#/E#/F#/P#` are independently reconstructed in ~4 places by different
traversals of different geometry, assumed positionally equal:
- converter: FreeCAD/OCCT order over a BREP export, vertex coord-hash dedup —
  `converter/_freecad.py:150-294`.
- viewer: re-mints global `F{n}`/`V{n}` for the picker —
  `viewer/model_viewer.py:372,401`.
- mesher: `gmsh tag - 1` over a separate STEP export — `meshdata.py:181-322`,
  `gmsh_mesher.py:679` (`_surface_tag_for_pid`).

Consequences:
- **Confirmed owner-container bug:** picked vertex/edge `V#/E#` (viewer order) →
  `entity_owners["V#"]` (`cad_app.py:788`) → resolved as gmsh `tag-1`
  (`meshdata.py:292,305`). Orders differ on assemblies → container attaches to
  the WRONG gmsh entity or is silently dropped (`.get()->None`). Faces match
  only by luck.
- **capFace `F#` -> `tag=n+1`** trusted, existence-checked only, never verified
  it's the right face (`gmsh_mesher.py:673-683`).
- Root cause: two separate OCCT exports (BREP for converter, STEP for mesher) +
  a third viewer numbering.

Direction: anchor identity to geometry and route everything through one
resolver — **planned in `Geometric-Entity-Identification/`** (Feature / Test /
Implementation). Key points:
- HARD CONSTRAINT: the mesher must mesh STEP from ANY source, so it can rely
  only on imported geometry — geometry is the only cross-source identity; the
  `F#/V#/P#`==tag-1 scheme is an app convention that must not leak into the core.
- Borrows the proven recipe from `retaincad.py` (Comet→ANSA, same problem):
  multi-point sampling (edges = endpoints+mid+samples, projected via
  `getClosestPoint`), faces resolved as the common face of their identified
  edges, bbox prefilter (`getEntitiesInBoundingBox`) + adaptive tolerance,
  many-to-many maps, names as optional accelerator, build-once + (optional)
  persist the `source_key -> [gmsh tags]` map. gmsh primitives verified
  2026-06-17.
- Reuse converter PIDs in the viewer (kill the 3rd numbering); route `collect`
  and `_surface_tag_for_pid` through the resolver; loud guard on no-match.
  Refinement's coordinate path (`RefinementSpec`/`_points_near`) is the seed.

### T1.2 Gmsh session leaks on the error path (HIGH) — FIXED 2026-06-17
`generate()` `gmsh.initialize()`d but did not finalize on error; the GUI's
`except Exception` (`cad_app.py`) returned without `finalize()`, leaking an
initialized session + half-built model on every `MeshValidationError`. Fixed by
having `generate()` own try/finalize-on-error/re-raise.

### T1.3 Unguarded top-level `import cadquery` (MED)
`cad_app.py:17` imports cadquery unguarded, above the `HAS_CADQUERY` dialog
check — a missing dep crashes on import before the friendly error can run.

## Tier 2 — structural (intertwined; high maintainability impact)

### T2.1 Gtk.Window is also the controller/domain layer (HIGH)
`cad_app.py` embeds GTK-free logic: `_resolve_vertex_anchor` (`:526`),
`_build_entity_owners` (`:776`), spec building (`:661`), and model→CADModelData
conversion duplicated 4× (`:276,372,481,793`). Untestable without a display.
Direction: extract a GTK-free `MeshController`/`ModelService`.

### T2.2 No unified mesh-config model -> GUI/CLI duplication (HIGH)
Config exists as dialog dict (with UI flags), YAML dict, and partial dataclasses,
hand-marshalled at every boundary. Validation authored twice; mesh-type map
triplicated (`mesh_step_model.py:45`, `gmsh_mesher.py:158`,
`mesh_settings.py:84`). Direction: one `MeshConfig` value object +
`build/validate` shared by both frontends.

### T2.3 No tests anywhere (HIGH)
No `tests/`, no framework. Highest-risk logic (identity handling, validation)
uncovered and structurally untestable while inside window methods. T2.1/T2.2
are the enablers.

### T2.4 collect()/generate() over-responsible (MED)
`meshdata.collect()` mixes 5 concerns incl. a normal-repair algorithm
(`meshdata.py:228-285`); `GmshMesher` bundles a ~270-line extrusion engine.
Extract collaborators (`ExtrudedHexBuilder`; split `collect`).

## Tier 3 — smaller

- **Silent failures (loud-safety-net violations):** registry import failure →
  `print()` only, model vanishes from GUI dropdown (`_registry.py:81`);
  sag-field `except Exception: kappa=0` (`gmsh_mesher.py:~822`); FreeCAD
  triangulation failure → print + empty face (`_freecad.py:252`); pid resolve
  miss → silent `.get()->None` (`meshdata.py:293,306,323`).
- **Dep-flag inconsistency (MED) — FIXED:** the CLI now checks `HAS_GMSH`
  (`mesh_step_model.py`, `app_core.py`, `app_gtk.py`); and the missing-dependency
  guards all raise `ImportError` — the gmsh guard (`GmshMesher.__init__`) was
  `RuntimeError`, now matched to the converter's cadquery/FreeCAD `ImportError`s.
- **Duplication (MED):** 3 envelope-walkers + `_ci_get` across model/viewer;
  fabricated volume→face topology, every solid claims all faces
  (`_freecad.py:288`).
- **No logging strategy (MED):** `logging` used in one file only; `print`
  elsewhere.
- **Temp-STEP round-trip (LOW) — WON'T FIX (intentional):** create→export→merge
  →unlink. Kept by design: routing app-built models through the same STEP→gmsh
  path as foreign STEP gives the mesher ONE source-agnostic flow (external
  STEP-in is the target use case). The entity reordering it causes is a non-issue
  under geometric resolution (T1.1).

## Suggested sequencing
1. T1.2 gmsh finalize-on-error (small, done).
2. T1.1 identity map — the structural keystone; closes the owner-container bug
   and the capFace risk and removes all `n±1` arithmetic.
3. T2.2/T2.1/T2.3 together — `MeshConfig` + GTK-free service + first tests.
4. Tier 3 loud-safety-net fixes alongside.
