# Feature: Export meshEntityContainers on selected edges

Status: **shipped** (2026-06-25) — single-phase P1; verified per `Test.md`
(T1–T6 green headlessly + the manual GUI save check). F2, a consumer of
`Edge-Identity-and-Picking` (F1): F1 makes edges pickable/labelable, the mesh
export already writes edge containers, and this connects the two.

## Summary
Turn a **picked, labelled edge** into a named `MeshEntityContainer` in the saved
MeshData, exactly as faces and vertices already do. This is the "export later"
half of F1's *rename now, export later*: F1 lets the user select the contact
edge and name it; F2 writes that name into the mesh output as a node/edge set the
FE solver can reference (e.g. the cylinder–block contact line as a named node
set / boundary).

## Why this is needed
F1 stores picked edges and their labels but deliberately writes nothing. For the
line-contact workflow the contact edge must reach the solver as a named set —
otherwise the user can identify the edge in the GUI but can't act on it
downstream. Faces and vertices already export this way (`Vertex-MeshEntityContainer`);
edges are the missing parity.

## Why this is small
The mesh export and resolver are already edge-capable:
- `mesher/export/meshdata.py:_collect_containers` already emits an
  `EntityContainer` for every **owned curve** (dim 1) — `node_ids` (the curve's
  mesh nodes, boundary included) + `edge_ids` — and `_PID_LETTER[1] = "E"`
  covers the legacy PID path.
- `mesher/resolver.py:build_owner_map` already resolves an `edge` anchor
  (samples → curve tag(s)) into the `{(1, tag): owner}` map the collector reads.
- `mesh_step_model.py` (foreign-STEP CLI) already parses `kind: edge` owners
  (by `samples`), so that path **already exports edge containers** end-to-end.

The only gap is the registry/GUI owner seam: picked-edge owners are never handed
to the export. F2 closes exactly that.

## Requirements (behavior)

- **R1 — Edge owner → container.** A picked, labelled edge is written to the
  MeshData as a `MeshEntityContainer` keyed on its label, carrying that edge's
  mesh entities (the curve's nodes, boundary included, plus its edge ids) — the
  same container shape faces/vertices produce.

- **R2 — All three sources.** Works for an edge owner specified via the **GUI**
  picker (`E#`), the **registry CLI** (`app_cli` `owners` by `E#` PID), and a
  **foreign STEP** (`mesh_step_model` `owners` by `samples`). The last already
  works; this feature brings the first two to parity.

- **R3 — Coincident edges → one container per touching body.** The contact line
  is a CAD edge on both bodies. A single picked edge owner resolves (by geometry,
  `Geometric-Entity-Identification` R5) to **every** coincident curve — one per
  touching body — and the export writes **one container per curve**, each
  carrying the owner's label and that body's own contact nodes (the parts mesh
  non-conformally, so each body has distinct nodes along the line). So labelling
  the contact line yields a per-body node set under that name — the natural shape
  for a contact set. Edge owners are **not** part-disambiguated (unlike vertex
  owners), so an owner cannot be scoped to just one body's curve — see Out of
  scope.

- **R4 — Independent and otherwise non-destructive.** Edge owners never collide
  with face/vertex owners (`E#` vs `F#`/`V#`); adding edge containers changes
  nothing about the fragments, nodes, or the face/vertex containers already
  written. The mesh itself is unchanged.

- **R5 — Loud on failure (both modes).** An edge owner that cannot be applied is
  reported loudly and names the reference — never silently dropped. Two modes:
  (a) the anchor resolves to no / an extent-mismatched mesh curve — the resolver
  already raises (`Geometric-Entity-Identification` R6); (b) the reference itself
  yields no anchor — a stale or unknown `E#` after the model changed — which
  today `selection_anchors` *silently skips* (it drops any pick whose
  `anchor_for_pick` returns ``None``, the same for faces/vertices). F2 makes that
  case a loud warning naming the dropped owner, per the loud-safety-net
  convention: a silently missing contact-line container is exactly the
  wrong-analysis-with-no-sign failure that convention guards against. (The fix
  lands in the shared owner loop, so faces/vertices gain the same warning.)

## User-facing scenarios
- **GUI:** the user picks the contact edge, labels it `contact-line`, meshes,
  and saves MeshData — the JSON has a `contact-line` container for each touching
  body (the cylinder's and the block's contact curves), each carrying that body's
  contact-line node ids (R3).
- **CLI (registry):** a YAML `owners: [{kind: edge, pid: E5, label: contact-line}]`
  on `app_cli` produces the same container(s).
- **CLI (foreign STEP):** `owners: [{kind: edge, samples: [...], owner: contact-line}]`
  on `mesh_step_model` — already supported; F2 keeps it working and tested.

## Out of scope
- **Edge mesh controls / refinement** — that is `Edge-Mesh-Controls` (F3).
- **Changing the container schema** — edges reuse the existing `EntityContainer`
  (node_ids + edge_ids); no new fields.
- **Renaming/picking edges** — delivered in F1.
- **Per-body scoping of an edge owner.** An edge owner names all coincident
  curves (every touching body), not one chosen body — `resolve_edge` takes no
  volume filter (vertex owners do, via `part`). Part-scoped edge resolution is a
  `Geometric-Entity-Identification` enhancement, out of scope here; for line
  contact, naming both bodies' contact curves is the desired result anyway.

## Decisions
- **Reuse the existing geometric owner path.** Picked-edge owners flow through
  the same `selection_anchors` → resolver `build_owner_map` → `_collect_containers`
  pipeline faces/vertices use; F2 adds no export or resolver code, only threads
  edge owners into it (the F1 `anchor_for_pick` `E#` branch already yields the
  edge anchor).
- **Container key stays label-derived (unchanged).** `_parse_container_key` takes
  the label's trailing integer, so `contact-line` keys to 0 and an auto-labelled
  `Edge 1` keys to 1 — the same scheme faces/vertices already use. A consequence
  that predates F2: distinct entity types with the same auto-number (an `Edge 1`
  and a `Face 1`) share a `containerKey`; the `owner` label is the human-readable
  name (not globally unique either — a coincident edge yields one container per
  body under the same label, R3). F2 keeps edges consistent with that scheme;
  making container keys unique across entity types is a separate, pre-existing
  concern (it affects faces/vertices today) and is out of scope here — flagged
  for a later look.

## Success criteria (behavioral)
- A picked/labelled edge appears as a container with the right node/edge ids in
  the saved MeshData, from the GUI and from `app_cli`; the foreign-STEP path
  still does.
- Edge, face, and vertex containers coexist as separate containers (distinct
  `owner` labels); adding the edge container leaves the fragments, node count,
  and the existing face/vertex containers unchanged.
- An unresolvable edge owner fails loudly; the mesh and other containers are
  unchanged.
