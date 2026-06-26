# Test Plan: Export meshEntityContainers on selected edges

Tests verify `Feature.md` (R1–R5). The export is exercised **headlessly** end to
end — build a registry model, attach an edge owner, mesh, save MeshData JSON,
and assert the container — in the `cadquery` conda env. The GUI pick→save click
path is the only manually-verified part.

## Oracle — how we know an edge container is "correct"
- The saved MeshData has at least one container whose `owner` is the edge's label
  — **one per touching body** for a coincident edge (R3), each with its own
  `containerKey` = the label's trailing integer (`_parse_container_key`).
- Each such container's `nodeIds` are non-empty and equal the mesh nodes gmsh
  reports for its resolved curve (`getNodes(1, tag, includeBoundary=True)`) —
  checked against the curve(s) the edge's samples resolve to, not against the
  writer's bookkeeping.
- Face/vertex containers and the fragments/nodes are unchanged by adding it.

## Fixtures
- **F-quarter:** `hertzian_cylinder_on_block_quarter_symmetry` — the contact-line
  edge is the primary owner under test (R1/R3); coincident on both bodies.
- **F-box:** `box-10x20x30` — a single straight edge owner (simplest R1).
- Reuse the F1 fixtures/PID discovery (`create_polydatas_per_part` → `E#`).

## Test groups

### T1 — Registry CLI: edge owner → container (end-to-end, the keystone)
Compute a real `E#` for F-quarter's contact edge (via `create_polydatas_per_part`,
as `app_cli` will see it), write a YAML config with
`owners: [{kind: edge, pid: E#, label: contact-line}]`, run `app_cli ... -o out.json`,
and assert the MeshData JSON has a `contact-line` container with non-empty
`nodeIds`. Mirrors `test_app_cli.py::test_pid_owners_on_assembly` with an edge.
**Pass:** the edge container is present and populated; the run succeeds.

### T2 — GUI bridge (headless): set_edge_owners → container
`AppCore.set_edge_owners([(E#, label)])` then `selection_anchors()` includes the
edge selection; meshing + MeshData save produces the labelled edge container.
Asserts the picked-`E#` → `selection_anchors` → resolver → container path without
a display (the GUI calls exactly this on save). **Pass:** container present;
`set_edge_owners` is cleared/independent of face/vertex owners.

### T3 — Contact edge resolves and exports (R3)
On F-quarter the contact-line edge owner resolves to **both** coincident curves
(one per body) and yields **one container per body**, all under the owner's
label; each container's `nodeIds` match gmsh's nodes for its curve. **Pass:** two
contact-line containers, each the correct per-body node set.

### T4 — Independence (R4)
A config with one face, one vertex, and one edge owner yields three containers
with distinct `owner` labels; the fragments and node count are identical to the
same mesh saved without owners (owners add only containers). **Pass:** all three
present, mesh body unchanged. Assert on the `owner` labels, not `containerKey` —
keys are label-derived and may coincide across entity types (see Feature
Decisions).

### T5 — Foreign STEP still works
`mesh_step_model` with `owners: [{kind: edge, samples: [...], owner: ...}]`
produces the edge container (regression guard — this path already worked before
F2). **Pass:** container present.

### T6 — Loud on an unresolved owner (R5)
An owner naming a stale/unknown edge PID (an `E#` not on the current model) makes
`selection_anchors` emit a **loud warning naming the dropped owner** and does not
crash the save; the owner simply produces no container (R5 mode b —
`anchor_for_pick` returns ``None``). Asserted via captured logs (caplog) on the
AppCore save path. Mode (a) — a geometric anchor matching no curve — is the
resolver's loud `EntityResolutionError`, already covered by GEI tests. **Pass:**
warning emitted naming the owner; save succeeds; no container for the bad owner.

## Manual (GUI) check
Pick the contact edge, label it, mesh, save MeshData → the JSON has the labelled
edge container. (Greyed-out/empty cases covered by F1.)

## Priority / acceptance
- **Must-pass core:** **T1** (the registry end-to-end) and **T4** (independence /
  non-destructive).
- **Broaden:** T2, T3, T5, T6.
- Accepted when T1–T6 pass headlessly in the `cadquery` env and the manual GUI
  check passes.
- **Status (2026-06-25): ACCEPTED.** T1–T6 green in the `cadquery` env
  (`test_edge_container.py`); regression set (core/CLI/owners/edge-identity)
  unaffected by the shared `selection_anchors` loud-warn; manual GUI save check
  passed.

## What is NOT tested here
- Edge mesh controls (F3).
- The container schema / writer internals (covered by `Vertex-MeshEntityContainer`
  and the meshdata exporter tests); here we test that an edge *owner* reaches it.
- Mesh generation/quality (unchanged).
