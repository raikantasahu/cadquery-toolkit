# Feature: Export meshEntityContainers on select Vertices

Status: **closed** (shipped 2026-06-13, commit cdbadc7). CLI surface verified
end-to-end; interactive picker code-complete and unit-verified headlessly. The
former "only open item" — a GUI smoke test to confirm the picked-`V{n}` ↔
mesher-`V{tag-1}` alignment — is **superseded**: the Geometric-Entity-Identification
feature replaced that fragile tag alignment with geometric resolution (a picked
`V#` becomes a coordinate anchor the resolver maps to the correct mesh vertex),
and the headless `test_t11_gui_bridge.py` now exercises the full picked-vertex →
anchor → resolve path — including coincident contact-vertex disambiguation on an
assembly, the hardest case. Only the non-automatable hand click-through remains,
in the same manual-GUI-checks bucket as every other GUI feature here.

> **Note (post-2026-06-13 drift):** this doc predates the core/UI split and the
> entity-identification work. `cad_app.py` is now **`app_gtk.py`** (renamed in
> d6e97d8), and the "Inherited assumption" below was retired by the geometric
> resolver. The original plan text is kept verbatim for reference.

## Implementation summary (done)
- `viewer/model_viewer.py`: `create_polydatas_per_part` now also stashes each part's
  topological vertices as `field_data["vertex_points"]` (N×3 flat) + `["vertex_pids"]`
  (global `V{n}`, via `global_vertex_counter`). New `_setup_multi_vertex_picking`
  (vtkPointPicker, `'p'`), `show_pick_viewer(..., pick_mode=)`, `show_viewer(pick_mode=)`,
  `picked_vertices` property, `_next_auto_pick_number(prefix=)`.
- `cad_app.py`: shared `_open_pick_viewer` + `_finish_pick_viewer`; `_on_menu_pick_vertices`,
  `_on_pick_vertices_viewer_closed`, `_on_menu_edit_vertex_selection`; `self._picked_vertices`
  (cleared with faces); `_build_entity_owners` merges both; sensitivity for the 2 new items.
- `dialogs/face_selection.py`: added `title=` param (back-compat default).
- `ui/window.ui`: added `menu_pick_vertices` + `menu_edit_vertex_selection`.
- `meshdata.py` / CLI: unchanged (already emit V containers).

### Verified
- CLI XML+JSON: vertex containers correct (see §1).
- Headless: `create_polydatas_per_part` attaches `V0..V7` contiguous + box-corner points;
  `cad_app` imports, all new handlers present; UI parses, new menu ids resolve;
  all modules `py_compile`.

### Inherited assumption — RETIRED
- ~~Picked `V{n}` (converter VertexList order) must match the mesher's `V{tag-1}`
  (gmsh dim-0 tag order)~~ — this tag-alignment assumption was the latent bug the
  Geometric-Entity-Identification feature fixed. Picked vertices now resolve
  **geometrically** (coordinate anchor → resolver), so there is no `V{tag-1}`
  coupling to confirm. Validated headlessly by `test_t11_gui_bridge.py` and
  `test_red_baseline.py`.

### Resolved
- Part visibility checkboxes now toggle a part's faces AND its vertex points in
  lockstep (`_add_visibility_checkboxes(..., extra_actors_by_label=)`); since VTK
  pickers honor visibility, hiding a part also excludes its vertices from picking.

---

Original plan below (for reference).

Goal (user's words): add the ability to export `meshEntityContainers` on
**select Vertices**. Decisions made: **both** surfaces (interactive picker +
config/CLI), and vertex IDs **mirror the existing face PID scheme**.

---

## Key finding: most of the stack already supports vertices

| Layer | Faces (existing) | Vertices (target) |
|---|---|---|
| FreeCAD extractor PIDs | `F{index}` (`app/converter/_freecad.py:274`) | `V{index}` ✓ already (`_freecad.py:157`) |
| Model dict | `FaceList[].persistentID` | `VertexList[].persistentID` + `Location` ✓ present (`converter/converter.py:109`) |
| `collect()` → `MeshEntityContainer` | keys on `F{tag-1}` (`meshdata.py:240`) | keys on `V{tag-1}` ✓ **already implemented** (`meshdata.py:212-223`) |
| Config/CLI YAML `owners` | passes through | passes through ✓ already (`mesh_step_model.py:82,134`) |
| Interactive picker | `vtkCellPicker` on triangles, `'p'` toggles → `_picked_faces` | ❌ **missing — the only real gap** |
| `cad_app._build_entity_owners` | `owners.update(_picked_faces)` (`cad_app.py:552`) | works for any `V*` pid ✓ no change |

PID ↔ gmsh-tag correspondence: extractor assigns 0-based `V{index}`;
`collect()` assumes gmsh vertex tag = `index + 1` (`V{tag-1}`). This is the
**same assumption faces already rely on** — mirroring it introduces no new risk.

`MeshEntityContainer` shape (`app/mesher/export/meshdata.py:69-76`): a vertex
container carries only `node_ids` (no edge/face ids). JSON form
(`meshdata_json_exporter.py`): `{"owner":"Vertex 1001","containerKey":1001,"nodeIds":[1]}`.

---

## Plan

### 1. Config/CLI surface — ✅ VERIFIED (2026-06-13, conda env active)
- `mesh_step_model.py:82` forwards `owners` verbatim to `collect()` — no type filtering.
- End-to-end run `out.step` + `mesh_config.yaml` (V0–V7):
  - XML: 8 `<MeshEntityContainer owner="Vertex …" numNodes="1" nodeIds="…"/>`,
    each exactly 1 unique corner node; edge(12)/face(6) containers unaffected.
  - JSON (`format: json`): 8 `{"owner":"Vertex 1001","containerKey":1001,"nodeIds":[1]}`.
- Conclusion: config/CLI surface is **done**; no code change needed. Only the
  interactive picker (section 2) remains.

### Design decision: SEPARATE MODES, `'p'` for both (user choice 2026-06-13)
Two distinct menu actions — "Pick Faces" and "Pick Vertices". Each opens the viewer
with **only that entity type pickable**, so `'p'` unambiguously toggles whichever
entity the current mode targets. (Rejected alternative: one shared session with
`p`=face / `v`=vertex.) Implication: a `pick_mode` is threaded through the viewer;
faces and vertices keep **separate persisted pick lists** that both feed
`entity_owners` (F/V keys never collide).

### 2. Interactive picker — `app/viewer/model_viewer.py` (the bulk of the work)
Mirror the face machinery (`_setup_multi_face_picking:458`, `show_pick_viewer:640`,
`create_polydatas_per_part:307`, `set_mesh_from_dict:911`):
- In `create_polydatas_per_part._emit_part`, also collect each part's `VertexList`
  into transformed points + a parallel global `V{n}` pid list (new
  `global_vertex_counter`, mirroring `global_face_counter`). Stash on the part mesh
  as `field_data["vertex_points"]` (N×3) and `field_data["vertex_pids"]` so the
  `(label, mesh)` tuple shape is unchanged. **Source = topological `VertexList`
  (corner verts), NOT tessellation points.**
- Generalize `show_pick_viewer` / `show_viewer` with a `pick_mode` of
  `"faces"` | `"vertices"`. In vertex mode: build a sphere-glyph actor per part from
  `vertex_points` (pickable), make the face actors **non-pickable**, and wire
  `_setup_multi_vertex_picking` (mirror of the face fn) on key **`'p'`**.
- `_setup_multi_vertex_picking`: `vtkCellPicker` on the glyph actors (or
  `vtkPointPicker`); `'p'` toggles the vertex under the cursor, highlights its glyph,
  floats a `Vertex N` label. Add a `Vertex`-prefix variant of
  `_next_auto_pick_number:440`; parametrize `_overlay_text:500` wording by mode.
- `picked_faces` property stays; add a parallel `picked_vertices` property reading a
  `pick_mode`-specific `_last_picks`.

### 3. App wiring — `app/cad_app.py`
- Add a **"Pick Vertices"** menu action mirroring "Pick Faces"
  (`_on_menu_pick_faces` ~340-363, `_on_pick_viewer_closed:365`), opening the viewer
  with `pick_mode="vertices"`; status/help text says `'p'` over a vertex.
- Add `self._picked_vertices` parallel to `_picked_faces:62` (clear at the same
  points: 233, 675, 681). `_build_entity_owners:542` merges **both**:
  `owners.update(self._picked_faces); owners.update(self._picked_vertices)`.
- Generalize "N faces selected" messaging per mode.

### 4. Edit-selection dialog — `app/dialogs/face_selection.py` — REQUIRED (user 2026-06-13)
User wants to rename picked **vertices** after picking, exactly like faces.
- The dialog is already generic over `[(pid,label)]`; only the title `"Edit Face
  Selection"` is face-specific. Generalize `edit_face_selection(parent, picks,
  title="Edit Face Selection")` (back-compat default) — update the one import in
  `cad_app.py`.
- Add an **"Edit Vertex Selection"** menu action mirroring `_on_menu_edit_face_selection:381`,
  operating on `self._picked_vertices` with `title="Edit Vertex Selection"`; gate its
  sensitivity on having vertex picks (mirror `_sync_menu_sensitivity` / `has_picks:656`).

### No change
- `app/mesher/export/meshdata.py` `collect()` — already emits V containers (verified).

## Risks
- Glyph pick accuracy (small points) — render as sphere glyphs + cell/point picker
  with tolerance, reusing the face cell-picker pattern.
- Getting per-part/assembly transforms right for vertex point placement.

## Verification (conda-env rule: do NOT run gmsh/pyvista/cadquery from default shell)
- Syntax checks only on my side.
- Config path: run the STEP→meshdata CLI with a `V*` owner in YAML; confirm a
  `Vertex` container with `nodeIds` appears in the output JSON.
- Interactive: pick a vertex → export meshdata JSON → confirm the `Vertex …`
  container is present.
