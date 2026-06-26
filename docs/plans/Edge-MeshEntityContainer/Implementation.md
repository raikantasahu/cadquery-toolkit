# Implementation Plan: Export meshEntityContainers on selected edges

Status: **shipped** (2026-06-25) — P1 landed in `app_core`/`app_gtk`/`app_cli`;
`test_edge_container.py` (T1–T6) green in the `cadquery` env + manual GUI save
check.

Implements `Feature.md`; verified by `Test.md`. Single-phase: thread picked-edge
owners through the registry/GUI seam into the already-edge-capable export.

## Key finding: only the owner seam is missing

| Layer | Faces / Vertices (existing) | Edges (target) |
|---|---|---|
| Container writer | `_collect_containers` emits owned vertex/face containers | owned **curve** container ✓ already (`meshdata.py` dim-1 branch; `_PID_LETTER[1]="E"`) |
| Owner resolution | `build_owner_map` (vertex/face anchors) | `edge` anchor (samples → curve tag) ✓ already (`resolver.py`) |
| Pick → anchor | `anchor_for_pick` V/F | `E#` → edge anchor ✓ already (F1) |
| Foreign-STEP CLI owners | `_parse_owners` vertex/face/part | `edge` by `samples` ✓ already (`mesh_step_model.py`) |
| **Registry owner state** | `AppCore._face_owners` / `_vertex_owners` + `selection_anchors` | ❌ **missing — gap** |
| **GUI save merge** | `set_face_owners` / `set_vertex_owners` in `_on_menu_save_mesh` | ❌ **missing — gap** |
| **Registry CLI owners** | `app_cli._apply_owners` face/vertex PIDs | ❌ **missing — gap** |

The bottom three rows are the whole feature.

## Component changes

### 1. `app_core.py` — edge owner state
- Add `self._edge_owners: list = []` beside `_face_owners`/`_vertex_owners`
  (and clear it where those are cleared, on model change).
- Add `set_edge_owners(items)` mirroring the face/vertex setters.
- In `selection_anchors`, build selections from
  `self._face_owners + self._vertex_owners + self._edge_owners`. The F1
  `anchor_for_pick` `E#` branch already returns the edge anchor; the resolver's
  `build_owner_map` already maps it to `{(1, tag): label}`, which
  `_collect_containers` already writes. No export/resolver change.
- **Loud on an unresolved pick (R5 mode b).** Today the loop silently skips a
  pick whose `anchor_for_pick` returns ``None`` (stale/unknown PID). Change it to
  `logger.warning(...)` naming the dropped owner, then continue (no crash). This
  is in the shared loop, so faces/vertices get the warning too. `app_core` has no
  module logger yet — add `import logging` + `logger = logging.getLogger(__name__)`.

### 2. `app_gtk.py` — hand picked edges to the core on save
- In `_on_menu_save_mesh`, alongside the face/vertex calls, add
  `self._core.set_edge_owners(self._picked_edges)`. (`_picked_edges` already
  exists from F1; this is the F1 "stop short of the merge" line being completed.)

### 3. `app_cli.py` — edge owners by PID
- In `_apply_owners`, accept `kind == "edge"` (an `E#` `pid`), collect into an
  `edge_owners` list, and `core.set_edge_owners(edge_owners)`. Update the
  `kind must be face|vertex` error to include `edge`, and the module docstring's
  `owners` example.

### No change
- `mesher/export/meshdata.py`, `mesher/resolver.py` — already edge-capable.
- `mesh_step_model.py` — already parses edge owners; covered by a regression
  test (Test T5), not a code change.

## Codebase touchpoints
- `app_core.py` — `_edge_owners`, `set_edge_owners`, `selection_anchors` += edges,
  reset.
- `app_gtk.py` — `set_edge_owners(self._picked_edges)` in `_on_menu_save_mesh`.
- `app_cli.py` — `_apply_owners` edge branch + docstring.
- `app/tests/` — `test_edge_container.py` (T1–T6).

## Phased delivery
- **P1 (whole feature).** §1–§3 + tests. Green: **T1** (registry CLI end-to-end),
  **T2** (GUI bridge headless), **T3** (contact edge → per-body containers),
  **T4** (independence), **T5** (foreign STEP regression), **T6** (loud on an
  unresolved owner). Manual GUI check on save. One PR — ~30 lines across three
  files (the R5 warn + an `app_core` logger nudge it past the original ~25) plus
  tests.

### Build order & verification
- **Land §1 + §3 + all tests first; they're fully headless.** Every test
  (T1–T6) runs without a display: T1/T5 drive the CLIs by subprocess, and
  T2/T3/T4/T6 exercise `AppCore`/the mesher in-process (T2 is the GUI's save path
  minus the window — `set_edge_owners` → `selection_anchors` → save). So the
  whole feature except one line is verifiable in the `cadquery` env with no GUI.
- **§2 is the only manual piece** — the single `set_edge_owners(self._picked_edges)`
  call in `_on_menu_save_mesh`; confirmed by the manual GUI check (pick → label →
  save → container in the JSON). Add it last.
- **Warn, don't error — even in the CLI.** R5 mode (b) is a *warning* that drops
  the owner and continues, in both the GUI and `app_cli` (it routes through the
  same `selection_anchors`); `app_cli` does **not** hard-error on a bad `E#`.
  This matches faces/vertices and is deliberate: the warn is the loud *downstream
  net*, while the root cause for the GUI (stale picks after a model change) is
  already handled by F1's `_invalidate_selections` clearing picks. Hard-erroring a
  bad CLI PID is a separate, broader choice, not taken here.

## Risks / notes
- **Container key from label.** `_parse_container_key` takes the trailing integer
  of the label; an edge labelled `contact-line` has no trailing int → key 0, same
  as faces/vertices today. Not edge-specific; out of scope to change here.
- **Owner-merge site.** The face/vertex owners are set in `_on_menu_save_mesh`
  (not a `_build_entity_owners` helper); add the edge call there, next to them.
- **Per-body containers serialize fine, but share (owner, key).** A coincident
  edge owner yields one container per body (R3), all with the same `owner` and
  the same label-derived `containerKey`. The JSON exporter emits
  `meshEntityContainers` as a *list* (`meshdata_json_exporter` list-comprehends
  `data.containers`), so all per-body containers survive — no dedup/overwrite.
  Implication for downstream: the C# reader must not key a map on `owner` or
  `containerKey` alone, or it will collapse the two contact-line sets. Not a
  blocker for F2 (we write correct JSON); flagged for the consumer. T3 asserts
  the per-body *count* so a future dedup regression is caught.
- **Finding the contact edge in tests.** There is no "the contact-edge PID" to
  hardcode — the tests discover it geometrically: the `E#` whose
  `anchor_for_pick` samples all lie on `x = 0, z = -cylinder_radius`, reusing the
  F1 approach (`test_edge_resolve.py`). T1/T3 compute it from
  `create_polydatas_per_part`, exactly as `app_cli` will see it.
