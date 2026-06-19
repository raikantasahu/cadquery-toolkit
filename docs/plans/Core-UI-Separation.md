# Core / UI Separation (Architecture-Review T2.1)

Status: **complete** — all phases 0–4 shipped (9d16f0e, 226faa6+04f1a2a+1ff3e5b,
293b678, d6e97d8, 4c5d314); T2.1 and T1.3 closed. The GTK-free `app_core.py` +
thin `app_gtk.py`/`app_cli.py` split is in place and headlessly tested
(`test_app_core.py`, `test_app_cli.py`, `test_model_layering.py`). Only the
non-automatable GUI smoke test remains, as planned.

## Motivation
`cad_app.py` is a `Gtk.Window` that is *also* the controller and the domain
layer. Symptoms:
- **Untestable** — none of the model-build / mesh / save / selection logic can be
  exercised without a display; the only coverage is manual GUI smoke tests.
- **Duplication** — model→CADModelData conversion is inlined ~4× across menu
  handlers; spec building and selection→anchor logic live inside event handlers.
- **Fragile startup (T1.3)** — a missing dependency (cadquery/freecad/vtk)
  anywhere on the deep import chain (converter/exporter/models all import
  cadquery) crashes at module load before the friendly dialog can run. The
  attempted fix — making a GTK window importable headlessly — is treating a
  symptom. The real cause is that domain logic is trapped behind GTK.

Target: a **GTK-free `app_core.py`** holding all domain/controller logic, with
**`app_gtk.py`** and **`app_cli.py`** as thin wrappers. Core and CLI never import
GTK; the GTK shell's dependency handling becomes trivial, and T1.3 dissolves.

## Target architecture
```
            app_core.py   (GTK-free: model build, convert, select, mesh, save)
            /          \
   app_gtk.py          app_cli.py
   (window, widgets,   (argparse: registry model
    picking, dialogs)   -> mesh -> save)
```
- **app_core.py** depends on: converter, exporter, mesher, models, and the
  GTK-free helpers in `model/tessellation.py` (`create_polydatas_per_part`,
  `anchor_for_pick`, `enumerate_part_labels`). **No `gi`/Gtk import.** Pulls in
  pyvista/numpy via those helpers — GTK-free and headless-safe (no rendering,
  just PolyData), as the test suite already relies on.
- **app_gtk.py** is today's `cad_app.py` minus the extracted logic: window,
  widgets (`ModelBuilder`, `ModelViewer`), menus, the 3D picking interaction,
  dialogs, and event handlers that translate UI → core calls and core results →
  UI updates.
- **app_cli.py** is a thin argparse wrapper: pick a registry model by name +
  params, run a mesh config, save. Coexists with `mesh_step_model.py` (external
  STEP → mesh) on the shared core (see CLI section).

## Hidden coupling (verified) — must be untangled first
- **`viewer/model_viewer.py` imports `gi`** (it defines the `GObject`-based
  `ModelViewer`), yet the three helpers the core needs —
  `enumerate_part_labels`, `create_polydatas_per_part`, `anchor_for_pick` — are
  GTK-free functions living *in that same module*. Importing them drags in GTK.
  **Prerequisite (Phase 0):** move those functions into a new GTK-free module
  **`model/tessellation.py`** (they derive renderable/queryable geometry from
  CADModelData) and update every import site directly (`cad_app`, `app/tests/*`,
  and `model_viewer` itself). No re-export shim — every caller is in this repo.
  Only then can the core import them GTK-free.
- **Keep `tessellation.py` OUT of `model/__init__.py`.** `model/` is a
  dependency-light schema package (zero pyvista/numpy today); the helpers pull in
  numpy + pyvista. Importing them as `from model.tessellation import …` isolates
  that dep, so `from model import CADModelData` (used by converter/exporters)
  stays pyvista-free. A layering-guard test (Phase 0) asserts importing the schema
  does **not** import pyvista/vtk, so this can't silently regress.
- No launchers/scripts reference `cad_app` (verified: only `cad_app.py` itself +
  one test docstring), so the Phase-3 rename is a clean rename + update the one
  docstring — no shim needed.

## AppCore API (GTK-free controller)
Works with plain cq objects + config dicts + PID/label data — never widgets.
```
class AppCore:
    # model lifecycle — two entry points to the same stored state
    def build_model(self, name, params, kind) -> None       # CLI: registry lookup + inspect signature
    def set_model(self, cq_model, name,                     # GUI: ModelBuilder already built it
                  parameters=None, param_signature=None) -> None
    def model_data(self) -> dict                            # cached CADModelData.to_dict()
    def clear(self) -> None                                 # drop model, selections, mesh

    # selection state (PIDs + labels; picking itself stays in the shell)
    def set_face_owners(self, items: list[tuple[str,str]]) -> None
    def set_vertex_owners(self, items: list[tuple[str,str]]) -> None
    def set_cap_face(self, pid: str | None) -> None
    def set_refinements(self, regions: list[dict]) -> None
    def selection_anchors(self) -> tuple[list, dict]        # (selections, entity_owners)

    # geometry helpers (already GTK-free today)
    def face_anchor(self, pid) -> dict | None
    def vertex_anchor(self, pid) -> tuple | None            # (coord, part_index)

    # mesh + outputs
    def mesh(self, config: dict) -> dict                    # build specs + create_mesh -> stats
    def save_mesh(self, path: str, fmt: str) -> None        # routes selections through resolver
    def export_model(self, path: str, fmt: str) -> None
    def mesh_stats(self) -> dict
    def finalize(self) -> None
```
Notes that shape the boundary:
- **Two build paths, one state.** `part_to_modeldata` needs the build
  `parameters` + `param_signature` (for the ParameterList); the GUI has them on
  `ModelBuilder`, so `set_model` carries them. The CLI has no widget, so
  `build_model(name, params, kind)` does the registry lookup and derives the
  signature via `inspect.signature`. Both end with the core holding
  `(model, name, parameters, param_signature)`; `model_data()` dispatches on
  part vs assembly.
- **Errors raise, wrappers present.** The core never shows a dialog or prints —
  it raises typed exceptions (`MeshValidationError`, `EntityResolutionError`,
  `ValueError`). `app_gtk` catches → `_show_error` dialog; `app_cli` catches →
  stderr + nonzero exit. This is the seam that lets the same core serve both.
- **gmsh-session lifecycle is the core's.** `mesh()` opens a session held by
  `_current_mesh` (`GmshMesher`, not finalized until save/replace); `finalize()`
  closes it. The GUI calls it on new-mesh/destroy; the CLI must call it (a
  context-manager wrapper is welcome). Re-meshing finalizes the prior session.

State owned by the core (today scattered on the window): current
`(model, name, parameters, param_signature)` + cached model_data,
`_picked_faces` / `_picked_vertices` / `_cap_face` / `_refinements`,
`_current_mesh` / `_current_mesh_stats`. **Not** core: `_mesh_settings` (last-used
*dialog* values) stays in `app_gtk` — it's UI defaults, not domain state.

## Move map (from the current `cad_app.py`)
**To `app_core.py` (GTK-free):**
- `_current_model_data` (:472) — model→CADModelData. **First confirm the 4
  inlined conversions (`:276,372,481,793`) are behaviorally identical** (same
  part/assembly dispatch, same params/signature wiring) before collapsing them
  into one core method; if any diverged, that divergence is a latent bug to
  resolve, not preserve.
- `_resolve_vertex_anchor` (:528), `_face_anchor` (:792), `_build_owner_inputs`
  (:797) — selection → geometric anchors/selections.
- mesh-spec building inside `_on_menu_create_mesh` (:594) — extrusion +
  refinement specs from a config dict; the `create_mesh` call.
- save/export bodies inside `_on_menu_save_mesh` (:755), `_on_menu_export` (:557).
- mesh stats computation inside `_on_menu_show_stats` (:827).
- `_finalize_current_mesh` (:874) and the mesh/selection state fields.

**Stays in `app_gtk.py` (GTK):**
- window/menu/widget setup (`__init__`, `_setup_css`, `_create_menu_bar`,
  `_create_widgets`, `_wire_builder`, tab handling), dependency dialog.
- picking interaction (`_open_pick_viewer`, `_pick_single_cap_face`,
  `_pick_single_vertex`, pick-closed/finish handlers) — produces PIDs the core
  consumes.
- dialogs (mesh settings, file choosers, edit-selection, info/error, stats
  display), menu sensitivity, all `_on_menu_*` / `_on_*` event handlers — now
  thin: extract UI inputs → call core → render core results.

## CLI design (`app_cli.py`, alongside `mesh_step_model.py`)
- **app_cli**: `app_cli <model-name> [--param k=v ...] --config mesh.yaml -o out`
  → `core.set_model(registry[name](**params))` → `core.mesh(cfg)` →
  `core.save_mesh(out, fmt)`. Registry-model input.
- **mesh_step_model**: unchanged — external-STEP input. Stays its own entry.
- **Shared core**: both CLIs and the GUI build the same mesh specs and owner
  selections. Opportunity (not required): lift the YAML `owners`/refinement/
  extrusion parsing (`_parse_owners`, `_parse_refinements` in mesh_step_model)
  into a shared config→spec helper the core exposes, so all three agree. Track
  as a follow-up, not a blocker.

## Test strategy
The core becomes unit-testable in the existing `app/tests/` harness (headless,
cadquery env), no display:
- model build (registry) → `model_data()` shape/counts.
- `selection_anchors()` produces resolver selections that attach correctly
  (reuse the T11 oracle on the saved file).
- `mesh(config)` returns expected stats; `save_mesh` round-trips owners.
- `app_cli` end-to-end (subprocess), mirroring `test_t11_cli_owners`.
The GTK shell keeps a manual smoke test only; its handlers are thin enough that
the risk lives in the (now tested) core.

## Migration phases (incremental; GUI stays working each step)
0. **Untangle the GTK-free helpers** — ✅ **DONE (commit 9d16f0e, 26 passed).**
   Moved the GTK-free closure out of `viewer/model_viewer.py` (which imports
   `gi`) into a GTK-free **`model/tessellation.py`** (NOT exported from
   `model/__init__.py`); layering-guard test added (`from model import
   CADModelData` stays pyvista-free).
   *Deviations from the original sketch, for the record:* (a) the move was the
   full closure — also `create_polydata_from_model_data` and the private helpers
   (`_ci_get`, `_emit_face`, `_walk_envelope`, transform utils), not just the
   three named functions; (b) more import sites than listed —
   `cad_app`/`app/tests/*`/`model_viewer` **plus** `visualize.py`,
   `build_assembly.py`, `verify_phase2.py`, and dropping
   `create_polydata_from_model_data` from `viewer`'s public API. Existing T0/T11
   tests stayed green → behavior preserved.
1. **Extract `AppCore`** — ✅ **DONE (commits 226faa6 + 04f1a2a; 1ff3e5b folds
   the view/pick paths onto `core.model_data`, finishing T2.1).** With the
   move-map logic; `cad_app.py` delegates to it (window keeps handlers, but they
   call core). Add core unit tests (model build, `selection_anchors`, `mesh`,
   `save_mesh` — reuse the `fixtures` harness + the T11 owner oracle;
   `test_app_core.py`). GUI smoke test after.
2. **Add `app_cli.py`** — ✅ **DONE (commit 293b678; `test_app_cli.py`).** On the
   core (registry model → mesh → save) + CLI test (subprocess, mirroring
   `test_t11_cli_owners`).
3. **Rename `cad_app.py` → `app_gtk.py`** — ✅ **DONE (commit d6e97d8, closes
   T1.3).** Thin shell; nothing references the old name, so just rename and fix
   the one test docstring — no shim. Drop the now-dead `HAS_CADQUERY` window
   check; `app_gtk.main()` does a small guarded probe + dialog (T1.3) — no
   deep-chain import-safety needed.
4. **(Optional)** lift shared config→spec parsing so mesh_step_model + app_cli +
   GUI share it. — ✅ **DONE (commit 4c5d314), but deliberately partial.** Lifted
   only the *basics*: the `str→MeshType` map (now public `MESH_TYPES`, exported
   from `mesher`) + element-type/size/sag validation, into
   `meshconfig.parse_mesh_basics` (shared by `app_cli` + `mesh_step_model`, with
   direct unit tests). **Owner/refinement/cap parsing stays per-CLI by design** —
   it genuinely diverges (registry `F#/V#` PIDs vs foreign-STEP coordinates), so
   `_parse_owners`/`_parse_refinements` remaining in `mesh_step_model.py` is
   intentional, not residual. Did **not** introduce the unified typed
   `MeshConfig` (that is T2.2, done separately in 9ffdd20).

## How T1.3 dissolves
Once core/CLI are GTK-free and the GTK shell is the only thing importing `gi`,
the "guard cadquery so the friendly dialog runs" problem is local and small:
`app_gtk.main()` does a guarded probe and shows the dialog; the heavy modules it
imports are reached only after the probe. No deep-chain import-safety needed.

## Risks / out of scope
- **Risk:** the GUI is not headlessly testable, so Phase 1/3 rely on the manual
  smoke test for the shell wiring. Mitigate by making handlers truly thin (no
  logic) so the tested core carries correctness.
- **Risk (Phase 0):** moving the three helpers must update every current import
  site (no shim) — the existing T0/T11 tests (which call them) are the regression
  net; a missed site fails at import.
- **Accepted:** the core (and thus `app_cli`) pulls in pyvista/vtk via
  `create_polydatas_per_part`. It's already a project dep and runs headless; a
  later refinement could compute face anchors straight from CADModelData
  (vertex/face lists) to drop that dep, but not now.
- **Out of scope:** unifying mesh_step_model into app_cli (chosen: coexist);
  the unified `MeshConfig` model (T2.2) — separate item, though Phase 4 nudges
  toward it.
