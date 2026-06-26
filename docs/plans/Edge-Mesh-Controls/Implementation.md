# Implementation Plan: Edge-anchored mesh controls

Status: **shipped** (2026-06-25) — P1 (`mesher/gmsh_mesher.py`), P2
(`app_core`/`app_cli`/`mesh_step_model`), P3 (`dialogs`/`app_gtk`); T1–T7 green
+ manual GUI check.

Implements `Feature.md`; verified by `Test.md`. Three phases mirroring F1:
**P1 mesher core → P2 config CLIs → P3 GUI**. The refinement field machinery is
reused; only the Distance field's source (points → curves) is new.

## Key finding: only the Distance source is new

| Layer | Vertex (existing) | Edge (target) |
|---|---|---|
| Distance field | `Distance` over `PointsList` (resolved vertex tags) | `Distance` over `CurvesList` (+ `Sampling`) ✓ **verified on gmsh 4.15.0** (probed; gmsh validates option names, so these are real) |
| Threshold / Restrict / Min | graded size, restrict-to-volume, min-combine | reused unchanged |
| Resolve the anchor | `resolve_vertex(at)` | `resolve_edge(samples)` ✓ already (resolver) |
| Anchor from a pick | `anchor_for_pick` `V#` → `at` | `E#` → samples ✓ already (F1) |
| `RefinementSpec` | `at` (point) | ❌ needs an edge anchor |
| `_build_refinement_field` | `PointsList` path | ❌ needs a `CurvesList` branch |
| `app_core._build_refinements` | `vertex_pid` → `at` | ❌ `edge_pid` → samples |
| `app_cli` / `meshconfig` | `vertexPid` | ❌ `edgePid` |
| `mesh_step_model._parse_refinements` | `at: [x,y,z]` | ❌ `samples: [[x,y,z],...]` |
| GUI dialog | Add Local/Contact (pick vertex) | ❌ Add Local/Contact Edge (pick edge) |

## Component changes

### P1 — mesher core (`mesher/gmsh_mesher.py`)
- **`RefinementSpec`**: add `edge_samples: Optional[list] = None`. When set, the
  spec is an *edge* refinement (and `at` is unused); keep `at` for the point
  path. (One spec type, two anchor modes — simplest; the field builder branches.)
- **`_build_refinement_field`**: split the anchor step from the shared grading.
  - point anchor (today) → `Distance`/`PointsList` over `resolve_vertex(at)`.
  - **edge anchor (new)** → `Distance`/`CurvesList` over `resolve_edge(edge_samples)`
    with `Sampling` set so the sample spacing ≈ `fine_size` (verified options on
    gmsh 4.15; see Risks — tie `Sampling` to `fine_size`, not `radius`).
    `contact`: all resolved curves. `local`: same curves, then `Restrict` to the
    target volume — derive it from `part_index` or the volume owning the first
    resolved curve (`getAdjacencies(1, curve)` → surfaces → volumes), the curve
    analog of `volumes_of_vertex`.
  - Everything after the Distance field (Threshold SizeMin/Max/DistMax, the
    Restrict, the Min combine in `_apply_refinement_fields`) is unchanged.
  - Loud + **abort**: an edge anchor matching no curve raises `MeshValidationError`
    naming it (mirror the vertex `EntityResolutionError` → `MeshValidationError`),
    so generation fails and **no mesh is produced** — do NOT warn-and-skip (see
    Risks: raise, don't warn).
- Green: **T1**, **T2**, **T3**, **T4**, **T7** (core, all headless via `create_mesh`).

### P2 — config CLIs + core builder
- **`app_core._build_refinements`**: a region may carry `edge_pid` instead of
  `vertex_pid`; resolve it via `anchor_for_pick` (F1 `E#` → edge anchor) and build
  `RefinementSpec(edge_samples=anchor["samples"], ...)`. **Raise** `AppError`
  (abort) if the pid doesn't resolve — mirrors the vertex branch; do NOT
  warn-and-skip like F2's `selection_anchors` (see Risks).
- **`app_cli` / `meshconfig`**: accept `edgePid` in a `refinements` entry
  (alongside `vertexPid`); pass `edge_pid` through. Update the docstring example.
- **`mesh_step_model._parse_refinements`**: accept `samples: [[x,y,z],...]` as an
  alternative to `at` in `localRefinement`/`contactRefinement`, building the edge
  variant (mirror how its `_parse_owners` already takes edge `samples`).
- Green: **T5** (registry CLI), **T6** (foreign STEP).

### P3 — GUI (`dialogs/mesh_settings.py` + `app_gtk.py`)
- Add **Add Local Edge… / Add Contact Edge…** to the Refinement tab, mirroring
  the vertex Add Local/Contact buttons but opening the **edge** picker (F1,
  single-select). The picked `E#` + label feed a refinement region carrying
  `edge_pid`; the region table shows the anchor (e.g. `E5`).
- `app_gtk` dispatches the edge-anchor pick (reuse the F1 edge pick-viewer path)
  and stores the region like the vertex ones.
- Manual GUI check; the region → `RefinementSpec` path is already proven headless
  by P2.

## Codebase touchpoints
- `mesher/gmsh_mesher.py` — `RefinementSpec.edge_samples`; `_build_refinement_field`
  `CurvesList` branch + curve→volume helper.
- `app_core.py` — `_build_refinements` `edge_pid` branch.
- `app_cli.py` / `meshconfig.py` — `edgePid` in refinements.
- `mesh_step_model.py` — `samples` in `_parse_refinements`.
- `dialogs/mesh_settings.py`, `app_gtk.py`, `ui/window.ui` — Add Local/Contact
  Edge buttons + edge-pick dispatch.
- `app/tests/` — `test_edge_refinement.py` (T1–T7).

## Phased delivery
- **P1 — mesher core (pure, headless).** The `CurvesList` field + spec. Green
  T1/T2/T3/T4/T7. This is the capability; both CLIs and the GUI consume it.
- **P2 — config CLIs.** `edgePid` (registry) + edge `samples` (STEP) +
  `app_core` builder. Green T5/T6. Still headless.
- **P3 — GUI.** Add Local/Contact Edge buttons + edge picker; manual check.

Headless-first like F1/F2: P1+P2 + all of T1–T7 land without a display; only P3
needs the GUI.

## Risks / notes
- **`Sampling` density — tie it to `fine_size`, not `radius`.** The `Distance`
  field samples each curve at `Sampling` points and reports the min distance to
  those *samples*; between two samples it over-estimates the distance by ~half the
  sample spacing, which `Threshold` then turns into a coarser size. So sampling
  every `~radius` leaves the curve fine only at the sample points and lumpy
  between — the exact R1/T1 failure. For a band uniformly at `fine_size` along the
  whole line, the **sample spacing must be on the order of `fine_size`**: set
  `Sampling ≈ ceil(curve_length / fine_size)` with a floor (e.g. ≥ 20). Too-coarse
  `Sampling` is the most likely way T1 fails.
- **Local-scope curve→volume.** `resolve_edge` returns all coincident curves;
  for `local`, pick the target volume (`part_index` or first curve's volume) and
  `Restrict` — same shape as the vertex local path, noted out-of-scope in Feature.
- **Verifying "finer" robustly.** Assert on a mesh metric that's stable across
  gmsh versions — element-count increase vs unrefined, plus the spacing of the
  nodes *on* the resolved curve (`getNodes(1, tag)`, ordered by parametric
  coordinate) ≈ `fine_size` at every consecutive gap (the whole-length R1 check) —
  rather than exact element counts or a noisy 3-D near-curve scan.
- **Raise, don't warn — do NOT copy F2's owner pattern.** Edge refinement
  failures must raise and abort (`_build_refinement_field` → `MeshValidationError`,
  `_build_refinements` → `AppError`), exactly like the vertex refinement path.
  Tempting but wrong to harmonize with F2's `selection_anchors` warn-and-continue:
  a dropped owner is recoverable, but a dropped refinement silently coarsens the
  mesh (Feature Decision). T7 guards this — failure produces no mesh / no output.
