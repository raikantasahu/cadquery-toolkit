"""Interactive entity picking for the CAD viewers (face / vertex / edge).

Wires left-click picking onto a pyvista Plotter: a left click toggles the
entity under the cursor; a left drag still rotates the camera. A single
``_setup_picking`` core holds the shared machinery (overlay, toggle, remove,
re-highlight, click wiring); one thin ``_setup_multi_*_picking`` wrapper per
entity kind supplies the three things that genuinely differ — how a click
resolves to an entity index, how the pick is highlighted, and the label wording.
GTK-free (pyvista + vtk + numpy); the window-composition layer
(``viewer.viewers``) calls the wrappers.
"""
from typing import Any, Dict, List

import numpy as np

from .style import PICK_HIGHLIGHT_COLOR


def _next_auto_pick_number(picks: List[tuple], prefix: str = "Face") -> int:
    """Pick a counter start so new auto-labels don't collide with existing ones.

    Existing labels of the form ``"{prefix} N"`` (the picker's default, e.g.
    ``"Face N"`` or ``"Vertex N"``) seed the counter to max(N)+1; non-matching
    labels (e.g. user-renamed "Top surface") are ignored. Returns 1 when
    ``picks`` is empty.
    """
    used = []
    for _pid, label in picks:
        parts = str(label).split()
        if len(parts) == 2 and parts[0] == prefix and parts[1].isdigit():
            used.append(int(parts[1]))
    return (max(used) + 1) if used else 1


def _vtk_interactor(plotter):
    """Return the raw vtkRenderWindowInteractor from a PyVista plotter.

    Newer PyVista wraps the raw vtkRenderWindowInteractor in a
    RenderWindowInteractor helper; older versions expose it directly.
    """
    iren = plotter.iren
    return getattr(iren, 'interactor', iren)


def _on_left_click(plotter, callback, drag_tol=5):
    """Invoke ``callback(x, y)`` on a left *click* that is not a camera drag.

    Picking fires on a left click (press + release at ~the same spot); a left
    *drag* still rotates the camera. We record the press position and, on
    release, only call back when the pointer moved <= ``drag_tol`` pixels — so
    selection and trackball rotation share the left button. Observers never
    abort the event, so VTK's built-in rotate runs unchanged.

    Two pyvista-specific details (a raw vtk ``AddObserver`` here picks nothing):
    register through ``plotter.iren.add_observer`` so the LeftButtonRelease is
    routed onto the interactor STYLE — the raw interactor swallows release, so a
    raw observer never fires; and read the event position from the raw
    interactor, because the release callback's ``caller`` is then the style,
    which has no ``GetEventPosition``.

    Replaces key-triggered picking ('p'), whose keypress collided with VTK's
    built-in char shortcuts (the 'p'/'f' handlers that logged "no current
    renderer on the interactor style").
    """
    iren = plotter.iren
    raw = _vtk_interactor(plotter)
    press_xy = [None]

    def _press(*_):
        press_xy[0] = raw.GetEventPosition()

    def _release(*_):
        start, press_xy[0] = press_xy[0], None
        if start is None:
            return
        x, y = raw.GetEventPosition()
        if abs(x - start[0]) <= drag_tol and abs(y - start[1]) <= drag_tol:
            callback(x, y)

    iren.add_observer('LeftButtonPressEvent', _press)
    iren.add_observer('LeftButtonReleaseEvent', _release)


def _add_pick_label(plotter, location, pid: str, label: str) -> str:
    """Float a billboarded ``label`` at world ``location``; return its actor name
    (named so it can be removed reliably — ``add_point_labels`` return types vary
    across PyVista versions). ``pid`` is globally unique (F#/V#/E#), so the name
    is unique within a pick session."""
    label_name = f"pick_label_{pid}"
    plotter.add_point_labels(
        [list(location)],
        [label],
        font_size=14,
        text_color='black',
        shape='rect',
        shape_color=PICK_HIGHLIGHT_COLOR,
        shape_opacity=0.85,
        show_points=False,
        always_visible=True,
        reset_camera=False,
        name=label_name,
    )
    return label_name


def _setup_picking(plotter, pick_state, single, *, prefix, singular, plural,
                   pids_by_actor, resolve_pick, add_highlight):
    """Shared pick machinery for every entity kind.

    The three pickers differ only in three injected pieces; this core owns the
    rest (overlay text + refresh, the monotonic ``{prefix} N`` counter, toggle /
    deselect / single-replace, removal, re-highlight of caller-supplied picks,
    and the left-click wiring).

    Args:
        pick_state: Dict with a ``picks`` list of ``(pid, label)`` — read/written
            in place; the caller reads it after the window closes.
        single: One entity at a time (a new pick replaces the previous) vs accumulate.
        prefix / singular / plural: label + overlay wording, e.g.
            ``("Face", "face", "faces")`` or ``("Vertex", "vertex", "vertices")``.
        pids_by_actor: ``{actor: [pid, ...]}`` — index -> pid, and the source for
            re-highlighting existing picks.
        resolve_pick: ``(x, y) -> (actor, index)`` for the entity under the
            cursor, or ``(None, None)`` if nothing was hit.
        add_highlight: ``(actor, index, pid, label) -> (highlight_actor,
            label_name)`` that draws the selection, or ``None`` if it can't.
    """
    pid_to_actors: Dict[str, tuple] = {}
    next_pick_n = [_next_auto_pick_number(pick_state['picks'], prefix=prefix)]
    overlay_name = f"{singular}_pick_overlay"

    def _overlay_text() -> str:
        if not pick_state['picks']:
            if single:
                return (f"{prefix} picker: left-click a {singular} to select.\n"
                        f"Picking another {singular} replaces the selection.\n"
                        f"No {singular} selected yet.")
            return (f"{prefix} picker: left-click a {singular} to pick/unpick.\n"
                    "Use the checkboxes on the left to hide/show parts.\n"
                    f"No {plural} picked yet.")
        header = (f"Selected {singular} (left-click another to replace):"
                  if single else f"Picked {plural} (left-click to toggle):")
        lines = [header]
        for pid, label in pick_state['picks']:
            lines.append(f"  {label}  [{pid}]")
        return "\n".join(lines)

    def _draw_overlay():
        # Re-add under the same name to update: add_text(position=<corner>)
        # returns a vtkCornerAnnotation (text set via SetText(corner, ...), not
        # SetInput), so replacing by name is the version-robust refresh.
        plotter.add_text(
            _overlay_text(), position='upper_right', font_size=10,
            color='yellow', shadow=True, name=overlay_name,
        )

    _draw_overlay()

    def _refresh_overlay():
        _draw_overlay()
        plotter.render()

    def _remove_pick(pid: str) -> None:
        sub_actor, label_name = pid_to_actors.pop(pid)
        plotter.remove_actor(sub_actor)
        plotter.remove_actor(label_name)
        pick_state['picks'] = [
            (p, lbl) for (p, lbl) in pick_state['picks'] if p != pid
        ]

    def _toggle(actor, idx: int) -> None:
        pids = pids_by_actor.get(actor)
        if pids is None or idx < 0 or idx >= len(pids):
            return
        pid = pids[idx]
        if pid in pid_to_actors:
            _remove_pick(pid)               # click the current pick -> deselect
            _refresh_overlay()
            return
        if single:
            for prev in list(pid_to_actors):
                _remove_pick(prev)
        label = f"{prefix} 1" if single else f"{prefix} {next_pick_n[0]}"
        created = add_highlight(actor, idx, pid, label)
        if created is None:
            return
        pid_to_actors[pid] = created
        if not single:
            next_pick_n[0] += 1
        pick_state['picks'].append((pid, label))
        _refresh_overlay()

    # Re-highlight any picks the caller passed in (so reopening the picker
    # visually shows what was already selected, with the original labels).
    pid_to_location = {pid: (actor, idx)
                       for actor, pids in pids_by_actor.items()
                       for idx, pid in enumerate(pids)}
    for pid, label in pick_state['picks']:
        loc = pid_to_location.get(pid)
        if loc is not None:
            created = add_highlight(loc[0], loc[1], pid, label)
            if created is not None:
                pid_to_actors[pid] = created

    def _on_pick_click(x, y):
        actor, idx = resolve_pick(x, y)
        if actor is not None:
            _toggle(actor, idx)

    _on_left_click(plotter, _on_pick_click)


def _setup_multi_face_picking(plotter, part_entries, pick_state, single=False):
    """Wire up face picking across multiple part actors.

    Args:
        plotter: The active pv.Plotter.
        part_entries: List of ``(label, actor, mesh)`` for each part currently
            shown. Each ``mesh`` must carry ``face_index`` cell_data and
            ``face_pids`` field_data.
        pick_state: Dict with ``picks`` list of ``(pid, label)``.
        single: When True, only one face may be selected at a time (e.g. the cap
            face); when False (default), picks accumulate and each toggles.

    Only cells of visible actors are picked (``vtkCellPicker`` honors actor
    visibility), so hiding a part via its checkbox excludes it from the pick.
    """
    import vtk

    picker = vtk.vtkCellPicker()
    picker.SetTolerance(0.0005)

    meshes: Dict[Any, tuple] = {}        # actor -> (cell_face_index, mesh)
    pids_by_actor: Dict[Any, list] = {}
    for _label, actor, mesh in part_entries:
        cell_face_index = mesh.cell_data.get("face_index")
        face_pids = mesh.field_data.get("face_pids")
        if cell_face_index is None or face_pids is None:
            continue
        meshes[actor] = (np.asarray(cell_face_index, dtype=np.int32), mesh)
        pids_by_actor[actor] = [str(p) for p in face_pids]

    def resolve(x, y):
        picker.Pick(x, y, 0, plotter.renderer)
        cell_id = picker.GetCellId()
        if cell_id < 0:
            return None, None
        info = meshes.get(picker.GetActor())
        if info is None or cell_id >= len(info[0]):
            return None, None
        return picker.GetActor(), int(info[0][cell_id])

    def add_highlight(actor, idx, pid, label):
        cell_face_index, mesh = meshes[actor]
        cell_ids = np.where(cell_face_index == idx)[0]
        if len(cell_ids) == 0:
            return None
        sub = mesh.extract_cells(cell_ids)
        sub_actor = plotter.add_mesh(
            sub, color=PICK_HIGHLIGHT_COLOR, show_edges=False,
            lighting=True, smooth_shading=False, pickable=False,
        )
        centroid = np.asarray(sub.points, dtype=np.float64).mean(axis=0)
        return sub_actor, _add_pick_label(plotter, centroid, pid, label)

    _setup_picking(
        plotter, pick_state, single, prefix="Face", singular="face",
        plural="faces", pids_by_actor=pids_by_actor, resolve_pick=resolve,
        add_highlight=add_highlight,
    )


def _setup_multi_vertex_picking(plotter, vertex_entries, pick_state,
                                single=False):
    """Wire up vertex picking across multiple part point-cloud actors.

    Each part contributes a points actor with one VTK point per CAD vertex; a
    ``vtkPointPicker`` maps a click to the nearest point id, which indexes the
    parallel ``vertex_pids`` list.

    Args:
        plotter: The active pv.Plotter.
        vertex_entries: List of ``(label, actor, points, vertex_pids)`` where
            ``points`` is an (N,3) ndarray and ``vertex_pids`` the parallel
            ``V{n}`` id list.
        pick_state: Dict with a ``picks`` list of ``(pid, label)``.
        single: When True, only one vertex may be selected at a time (e.g. the
            refinement anchor); when False (default), picks accumulate.
    """
    import vtk

    picker = vtk.vtkPointPicker()
    picker.SetTolerance(0.01)

    points_by_actor: Dict[Any, np.ndarray] = {}
    pids_by_actor: Dict[Any, list] = {}
    for _label, actor, points, vpids in vertex_entries:
        points_by_actor[actor] = np.asarray(points, dtype=np.float64)
        pids_by_actor[actor] = vpids

    def resolve(x, y):
        picker.Pick(x, y, 0, plotter.renderer)
        point_id = picker.GetPointId()
        if point_id < 0 or picker.GetActor() not in points_by_actor:
            return None, None
        return picker.GetActor(), int(point_id)

    def add_highlight(actor, idx, pid, label):
        points = points_by_actor[actor]
        if idx < 0 or idx >= len(points):
            return None
        loc = points[idx]
        sub_actor = plotter.add_points(
            np.asarray([loc], dtype=np.float64),
            color=PICK_HIGHLIGHT_COLOR, render_points_as_spheres=True,
            point_size=20, pickable=False,
        )
        return sub_actor, _add_pick_label(plotter, loc.tolist(), pid, label)

    _setup_picking(
        plotter, pick_state, single, prefix="Vertex", singular="vertex",
        plural="vertices", pids_by_actor=pids_by_actor, resolve_pick=resolve,
        add_highlight=add_highlight,
    )


def _setup_multi_edge_picking(plotter, edge_entries, pick_state, single=False):
    """Wire up edge picking across multiple part line actors.

    Each part contributes a line actor (one polyline cell per edge) carrying
    ``edge_index`` cell_data and ``edge_pids`` field_data (from
    ``edge_lines_polydata``). A ``vtkCellPicker`` maps a clicked segment to its
    cell, whose ``edge_index`` indexes the parallel ``edge_pids``.

    Args:
        plotter: The active pv.Plotter.
        edge_entries: List of ``(label, actor, line_mesh)``.
        pick_state: Dict with a ``picks`` list of ``(pid, label)``.
        single: When True, only one edge may be selected at a time.
    """
    import vtk

    picker = vtk.vtkCellPicker()
    picker.SetTolerance(0.01)   # looser than faces — edges are thin curves

    meshes: Dict[Any, tuple] = {}        # actor -> (cell_edge_index, line_mesh)
    pids_by_actor: Dict[Any, list] = {}
    for _label, actor, mesh in edge_entries:
        cell_edge_index = mesh.cell_data.get("edge_index")
        edge_pids = mesh.field_data.get("edge_pids")
        if cell_edge_index is None or edge_pids is None:
            continue
        meshes[actor] = (np.asarray(cell_edge_index, dtype=np.int32), mesh)
        pids_by_actor[actor] = [str(p) for p in edge_pids]

    def resolve(x, y):
        picker.Pick(x, y, 0, plotter.renderer)
        cell_id = picker.GetCellId()
        if cell_id < 0:
            return None, None
        info = meshes.get(picker.GetActor())
        if info is None or cell_id >= len(info[0]):
            return None, None
        return picker.GetActor(), int(info[0][cell_id])

    def add_highlight(actor, idx, pid, label):
        cell_edge_index, mesh = meshes[actor]
        cell_ids = np.where(cell_edge_index == idx)[0]
        if len(cell_ids) == 0:
            return None
        sub = mesh.extract_cells(cell_ids)
        sub_actor = plotter.add_mesh(
            sub, color=PICK_HIGHLIGHT_COLOR, line_width=6,
            render_lines_as_tubes=True, lighting=False, pickable=False,
        )
        centroid = np.asarray(sub.points, dtype=np.float64).mean(axis=0)
        return sub_actor, _add_pick_label(plotter, centroid, pid, label)

    _setup_picking(
        plotter, pick_state, single, prefix="Edge", singular="edge",
        plural="edges", pids_by_actor=pids_by_actor, resolve_pick=resolve,
        add_highlight=add_highlight,
    )
