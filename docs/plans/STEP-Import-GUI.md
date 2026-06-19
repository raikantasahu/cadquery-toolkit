# Import External STEP in the GUI

## Motivation
External STEP-in is the app's **target use** (a caller hands a STEP, expects a
good mesh — see project memory). Today only the *CLI* (`mesh_step_model`) meshes
a foreign STEP; the GUI can only mesh registry-built models. This feature lets
the GUI **import a STEP file and view / pick / mesh / save / export it exactly
like a built model**, closing the gap between the GUI and the real target.

## Key finding: the core is already ready
Verified (Explore pass):
- `AppCore` is **param-agnostic end to end** — `set_model(model, name)` defaults
  `parameters`/`param_signature` to None; `model_data` → `part_to_modeldata(...,
  parameters=None, param_signature=None)` → `build_parameter_dicts(None)` → `[]`.
  `mesh`, anchors, `save_mesh`, `export_model` never require parameters.
- `importer.step_importer.read(path)` already returns a `cq.Assembly` (assembly-
  structured STEP) or `cq.Workplane` (single shape) — never a bare Shape.
- The geometric resolver is source-agnostic (that work was *for* foreign STEP).

So this is **mostly GUI wiring** — no core/converter changes. (Correction from
implementation: the *importer* did need one robustness fix — `step_importer.read`
hardened to fall back to a flat shape import on any assembly-read failure, after
a foreign STEP tripped `cq.Assembly.importStep`. See Phase 1.)

## The blockers (all in `app_gtk.py`, because "model" comes from a ModelBuilder)
1. `model_builder` property + `_sync_menu_sensitivity` gate every action on the
   active tab being a `ModelBuilder` with a selection → menus stay disabled for a
   non-builder source.
2. `_sync_core_model()` rebuilds from the active builder on **every** action and
   overwrites the core — it would clobber a one-shot `core.set_model(imported)`.
   (The single biggest blocker.)
3. Naming for export/save comes from `get_selected_model_name()`.
4. Pick/owner/refinement invalidation is wired only to ModelBuilder signals.
5. Status updates are tied to builders.

## Design — a `ModelSource` the window talks to polymorphically
Make the window operate on an **active model source**, not specifically a
ModelBuilder. Both the existing builder and a new STEP panel implement the same
small surface, so the menu/sync/sensitivity code stops special-casing.

**ModelSource is a duck-typed contract, NOT a base class.** Both sources are
GTK widgets (`Gtk.Box`); a formal ABC/Protocol base would collide with GObject's
metaclass (a known PyGObject constraint). So "ModelSource" is just the documented
method/signal surface below, and `active_source` is identified by
`isinstance(page, (ModelBuilder, StepImportPanel))` (or a small marker attribute).

**ModelSource surface** (already mostly what ModelBuilder exposes):
- `get_current_model()`, `get_selected_model_name()`,
  `get_current_build_params()`, `get_current_build_signature()`
- `build_model() -> bool` (registry: build; STEP: True iff a file is loaded)
- `has_model() -> bool` (registry: a selection exists; STEP: a file is loaded)
  — **new**; today sensitivity uses `get_selected_model_name() is not None`.
- `request_view() -> None` — **needed**: the View *menu* calls
  `active_source.request_view()` (ModelBuilder has it at :391); StepImportPanel
  must implement it (build no-op → emit `view-requested`).
- `last_status_message` attribute — **needed**: `_on_tab_switched` restores it
  when a tab becomes active (ModelBuilder has it at :73).
- signals: `view-requested(model)`, `status-changed(str)`, and an **invalidation
  signal**. Do NOT refactor ModelBuilder's existing `params-changed` /
  `model-type-changed`; instead the window gets one `_invalidate_selections()`
  slot, and `_wire_source` connects each source's change signal(s) to it
  (ModelBuilder: params-changed + model-type-changed; StepImportPanel: a single
  signal emitted on import). Less churn than unifying ModelBuilder's signals.

**`StepImportPanel(Gtk.Box)` — new third tab "Imported STEP":**
- an **Import STEP…** button → `Gtk.FileChooser` (.step/.stp) →
  `model = step_importer.read(path)`; store `(model, Path(path).stem)`; emit
  `model-changed` + `status-changed`; enable a **View** button (mirrors
  ModelBuilder's View → `view-requested`).
- a label showing the loaded filename (or "No file imported").
- `has_model()` = a model is loaded; `build_model()` = `model is not None`;
  `get_current_model()` = the cached model; params/signature = None;
  `get_selected_model_name()` = the stem.
- import failure → loud error dialog + status (no silent failure).

**`app_gtk` changes (resolve the 5 blockers):**
1. `model_builder` → `active_source` (active tab if it's a ModelSource:
   ModelBuilder **or** StepImportPanel); `_sync_menu_sensitivity` uses
   `active_source.has_model()`. Rename touches every `self.model_builder` call
   site (sync, export, save, view, sensitivity) — update them all directly (no
   compat alias).
2. `_sync_core_model` uses `active_source` — for the STEP tab it re-sets the
   cached imported model each action (idempotent; the cache recomputes). No
   clobber, because the active source *is* the STEP panel.
   *Optional perf — DONE (commit f7c304d):* `AppCore.set_model` short-circuits (skips cache
   invalidation) when the model object identity, name, params, and signature are
   unchanged. The STEP panel returns a stable model object, so this avoids
   re-converting the imported model on every menu action; registry builders
   rebuild a fresh object each time, so their behavior is unchanged. Covered by
   `test_app_core.py::test_set_model_short_circuits_on_unchanged_reset`.
3. naming via `get_selected_model_name()` (the stem) — already used.
4. STEP import → the shared `_invalidate_selections()` slot, which **both**
   clears picks/owners/refinements **and** refreshes menu sensitivity — so menus
   *enable* once a file is loaded (`has_model()` flips True). Without the
   sensitivity refresh the menus would stay disabled after import.
5. STEP panel emits `status-changed` like a builder.
6. **Tab switch keeps the imported model loaded** — `_on_tab_switched` finalizes
   the mesh and clears picks (as today), but the panel retains its model, exactly
   as the builders retain their selection across tab switches.

## Phases (incremental; GUI stays working each step) — ALL DONE ✅
0. ✅ **DONE (commit 8ee8589).** Generalize to ModelSource — `has_model()` on
   ModelBuilder; `model_builder` property → `active_source`; route
   `_sync_core_model`/sensitivity through it; extract `_invalidate_selections`.
   Pure refactor; GUI smoke passed.
1. ✅ **DONE (commit 600fe5b).** `StepImportPanel` + third "Imported STEP" tab —
   import → view/pick/mesh/save/export through the existing core path; loud import
   errors. **Plus a finding that overturned the "no importer changes" claim:**
   foreign STEP trips `cq.Assembly.importStep` with non-ValueError errors
   (`KeyError: ''` on NIST AP242's empty product label), so `step_importer.read`
   was hardened to fall back to the flat import on ANY assembly-read failure
   (loud). Headless data-path test (`tests/test_step_import.py`); GUI smoke
   passed. Button later aligned to the builder tabs (20c55fd) and the
   construction deduped into `make_view_model_button` (b3b086e).
2. ✅ **DONE (commit 3aaedd6).** Polish — remember last import directory
   (session); dim italic empty-state hint (`_apply_state_label`);
   "Importing <file>…" feedback before the blocking read (restored on failure).
   GUI smoke passed.

**Feature complete:** the GUI imports an external STEP (3rd tab) and
views/picks/meshes/saves/exports it exactly like a built model. Suite 47 passed.

## Tests
- **Headless (data path):** read a **vendored NIST STEP** (already in
  `app/tests/models/`, a real external file) via `step_importer.read` →
  `AppCore.set_model(model, stem)` → `model_data` → `create_polydatas_per_part`
  yields F#/V# PIDs → `set_face_owners`/`set_vertex_owners` → `mesh` →
  `save_mesh`; assert the owner containers attach (reuse the T11 oracle). This is
  the whole feature minus the GTK chooser. Note: the imported model gets F#/V#
  PIDs from its own CADModelData (same converter path), so pick→anchor→gmsh
  resolution works exactly as for registry models; it meshes via the same
  cq→STEP→gmsh path (here STEP→cq→STEP→gmsh — geometric resolver makes the extra
  round-trip a non-issue). This test specifically **locks the param-less
  `part_to_modeldata(parameters=None)` path** — new for the GUI, since registry
  parts always carried params.
- **GTK glue** (panel, chooser, tab wiring): manual smoke test only (no headless
  GTK), kept thin over the tested core — same posture as the rest of `app_gtk`.

## Out of scope / known limitations
- Re-export/round-trip changes (none needed).
- Multiple simultaneous imports (one model per import; re-import replaces).
- Assembly-tree editing of an imported STEP.
- **Nested-assembly STEP:** `assembly_to_modeldata` supports only one level and
  raises `NotImplementedError` on nested sub-assemblies (`converter.py:192`). A
  multi-level assembly STEP therefore fails when `model_data()` runs — surfaced
  loudly via the existing `_current_model_data()` "Conversion Error" dialog, not
  silently. Same pre-existing converter limitation as registry assemblies; out of
  scope to lift here, but the GUI must show it clearly (P1/P2 error handling).

## Decisions (confirmed)
1. **Placement:** a **third tab "Imported STEP"** alongside Parts/Assemblies
   (tab-as-source model).
2. **ModelSource abstraction:** ModelBuilder + StepImportPanel are interchangeable
   model sources; the window talks to the active source (no imported-mode flags).
3. **Re-import:** one model at a time — re-import **replaces** it and **clears**
   existing face/vertex picks, owners, and refinements (like a parameter change).
