# Feature: Per-part visibility in the volumetric mesh viewer

Status: **shipped** (2026-06-20) — delivered in `Implementation.md` phases
P1–P3; all requirements below met (see `Test.md` T0–T5 + manual GUI checks).

## Summary
When the volumetric mesh on display is the mesh of an **assembly** (more than
one part), let the user **hide and unhide each part's mesh independently** in the
viewer — so they can see inside the assembly, isolate one part, or inspect a
contact region. When the displayed mesh is of a single **part**, no such control
appears; the mesh shows exactly as it does today.

This extends to the volumetric mesh the per-part hide/show the **surface** CAD
viewer already offers (its face/vertex picker renders one actor per part with a
visibility checkbox column). The volumetric viewer currently renders the whole
mesh as one opaque body with no part identity.

## Why this is needed
An assembly mesh drawn as a single solid is hard to inspect: interior parts,
mating interfaces, and the element quality of an individual part are hidden
behind the outer surfaces. Today the only way to look at one part's mesh is to
mesh that part alone. Per-part visibility lets the user peel the assembly apart
visually — hide the housing to see the bolt mesh inside, hide everything but one
plate to check its elements — without re-meshing.

A single-part mesh has nothing to peel apart, so the control would be noise;
the feature is deliberately **absent** for a part.

## What it does
- Adds a **per-part visibility control** (one toggle per part) to the volumetric
  mesh viewer, shown **only** when the mesh has more than one part.
- Toggling a part hides/shows that part's mesh fragment immediately, leaving the
  other parts and the scene (camera, axes, floor) untouched.
- Each toggle is labelled with the part's identity, so the user knows which part
  they are hiding.
- Works whether the mesh was **just generated** in the app or **loaded** from a
  saved mesh file.

## Requirements (behavior)

- **R1 — Assembly-only control.** The per-part visibility control appears when,
  and only when, the displayed mesh has **more than one part**. For a
  single-part mesh the viewer shows no visibility control and looks exactly as it
  does today. "More than one part" is the user-meaningful test — a mesh of an
  assembly of N parts offers N toggles; a mesh of one part offers none.

- **R2 — Independent, immediate toggle.** Each part can be hidden and shown
  independently of the others, and the change is reflected in the view
  immediately. Hiding one part never changes the visibility of another.

- **R3 — Identifiable parts.** Each toggle carries the part's identity (its
  name where known, otherwise a stable positional label such as `Part 1`), so
  the user can tell which part a toggle controls. Part order shown to the user is
  stable across runs of the same mesh.

- **R4 — Completeness and no double-counting.** Every element of the mesh belongs
  to exactly one part, and the parts together account for the whole mesh — with
  all parts shown, the view is identical to today's single-body view (nothing
  missing, nothing drawn twice). This is the parts-partition-the-mesh contract.

- **R5 — Both mesh sources.** The control behaves the same whether the mesh came
  from generating one in the app (the live path) or from opening a saved mesh
  file (the loaded path).

- **R6 — All visible by default.** When the viewer opens, every part is visible.

- **R7 — View-only, non-destructive.** Hiding a part affects only what is drawn.
  It does not alter the mesh, the part it belongs to, or anything written when
  the mesh is later saved/exported. Closing and reopening the viewer resets to
  all-visible.

- **R8 — Hiding all parts is allowed.** The user may hide every part; the scene's
  orientation aids (axes, floor, camera) remain so the view stays usable, and
  unhiding restores the parts.

- **R9 — Coexists with existing viewer interactions.** Camera rotation, the view
  presets (front/top/iso/…), reset, and wireframe toggle continue to work with
  parts hidden, and behave on the still-visible parts as expected.

## User-facing scenarios
- **Assembly mesh, GUI:** the user generates a mesh for a multi-part assembly,
  opens the mesh viewer, and sees a toggle per part. They hide the outer parts to
  inspect an interior part's mesh, then unhide them.
- **Single-part mesh, GUI:** the user meshes a single part and opens the viewer —
  no visibility control is shown; the mesh displays as before.
- **Loaded assembly mesh file:** the user opens a previously saved assembly mesh
  and gets the same per-part toggles.

## Out of scope
- **Picking / selecting** mesh entities per part (the surface viewer's picker is
  separate; this feature is visibility only).
- **Editing** the mesh, or changing what is saved/exported — visibility is a
  view state only.
- **Per-part mesh controls** (element size/type per part) — that is the
  `Part-Specific-Mesh-Controls.md` track; this feature only governs display.
- Re-meshing or per-part re-meshing.
- Changing the surface CAD viewer (it already has per-part hide/show).

## Decisions
- **A "part" = one solid body in the mesh** (one gmsh volume / one fragment
  owner). An assembly of N bodies yields N parts; a single solid is one part.
  This matches how the mesh is already segmented for saving (one fragment per
  body) and how the surface viewer already splits per part.
- **Label source.** Prefer the part's known name (the assembly child / source
  part name the app already enumerates); fall back to a positional `Part {n}`
  when no name is available (e.g. an imported STEP before names are carried).
- **Single source of the assembly-vs-part signal.** The viewer decides whether to
  show the control from the **mesh it is handed** (how many parts it carries), not
  from a separate "is assembly" flag — so the same rule holds for the live and
  loaded paths and there is one place it can be wrong.

## Success criteria (behavioral)
- A multi-part assembly mesh opens with one working visibility toggle per part;
  hiding/showing a part updates the view immediately and independently.
- A single-part mesh opens with no visibility control and is visually identical
  to today.
- With all parts visible the view matches the current single-body rendering
  (the parts exactly partition the mesh — verified by element-count parity).
- The same behavior holds for a freshly generated mesh and for a loaded mesh
  file.
- Hiding a part changes nothing about a subsequently saved/exported mesh.
