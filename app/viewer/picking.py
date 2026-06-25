"""Interactive entity picking for the CAD viewers (face / vertex / edge).

Wires left-click picking onto a pyvista Plotter: a left click toggles the
entity under the cursor; a left drag still rotates the camera. One
``_setup_multi_*_picking`` per entity kind, plus the low-level click/interactor
helpers they share. GTK-free (pyvista + vtk + numpy); the window-composition
layer (``viewer.viewers``) calls these.
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


def _setup_multi_face_picking(plotter, part_entries, pick_state, single=False):
    """Wire up face picking across multiple part actors.

    Args:
        plotter: The active pv.Plotter.
        part_entries: List of ``(label, actor, mesh)`` for each part
            currently shown. Each ``mesh`` must carry ``face_index``
            cell_data and ``face_pids`` field_data.
        pick_state: Dict with ``picks`` list of ``(pid, label)``.
        single: When True, only one face may be selected at a time — picking a
            different face replaces the previous selection (for the cap face).
            When False (default), picks accumulate and each toggles.

    User left-clicks a face to toggle the face under the cursor (a left drag
    rotates the camera instead). Only cells of visible actors are picked (VTK's
    vtkCellPicker honors actor visibility), so hiding a part via its
    checkbox effectively excludes it from the pick.
    """
    import vtk

    picker = vtk.vtkCellPicker()
    picker.SetTolerance(0.0005)

    # vtkActor → (cell_face_index ndarray, face_pids list, owning mesh)
    actor_lookup: Dict[Any, tuple] = {}
    for _label, actor, mesh in part_entries:
        cell_face_index = mesh.cell_data.get("face_index")
        face_pids_arr = mesh.field_data.get("face_pids")
        if cell_face_index is None or face_pids_arr is None:
            continue
        actor_lookup[actor] = (
            np.asarray(cell_face_index, dtype=np.int32),
            [str(p) for p in face_pids_arr],
            mesh,
        )

    # Per-pid state: highlight actor + label actor, so toggling off can
    # remove both. Labels are floated at each face's centroid so the user
    # can map "Face 1/2/3" in the overlay back to a spot on the model.
    pid_to_actors: Dict[str, tuple] = {}

    # Monotonic counter for auto-generated "Face N" labels — never reused,
    # so unpicking + re-picking does not produce duplicate labels.
    next_pick_n = [_next_auto_pick_number(pick_state['picks'])]

    def _overlay_text() -> str:
        if not pick_state['picks']:
            if single:
                return ("Face picker: left-click a face to select.\n"
                        "Picking another face replaces the selection.\n"
                        "No face selected yet.")
            return ("Face picker: left-click a face to pick/unpick.\n"
                    "Use the checkboxes on the left to hide/show parts.\n"
                    "No faces picked yet.")
        header = ("Selected face (left-click another to replace):" if single
                  else "Picked faces (left-click to toggle):")
        lines = [header]
        for pid, label in pick_state['picks']:
            lines.append(f"  {label}  [{pid}]")
        return "\n".join(lines)

    _OVERLAY_NAME = 'face_pick_overlay'
    plotter.add_text(
        _overlay_text(), position='upper_right', font_size=10,
        color='yellow', shadow=True, name=_OVERLAY_NAME,
    )

    def _refresh_overlay():
        # Update by re-adding under the same name. add_text(position=<corner>)
        # returns a vtkCornerAnnotation, whose text is set via SetText(corner,
        # ...) — NOT SetInput(...), which only exists on vtkTextActor. Re-adding
        # by name replaces the actor without depending on the corner index or
        # the actor's VTK type across pyvista/VTK versions.
        plotter.add_text(
            _overlay_text(), position='upper_right', font_size=10,
            color='yellow', shadow=True, name=_OVERLAY_NAME,
        )
        plotter.render()

    def _add_highlight(actor, face_idx: int, pid: str, label: str) -> bool:
        cell_face_index, _pids, mesh = actor_lookup[actor]
        cell_ids = np.where(cell_face_index == face_idx)[0]
        if len(cell_ids) == 0:
            return False
        sub = mesh.extract_cells(cell_ids)
        sub_actor = plotter.add_mesh(
            sub, color=PICK_HIGHLIGHT_COLOR, show_edges=False,
            lighting=True, smooth_shading=False, pickable=False,
        )
        # Billboarded label at the face centroid (mean of its vertices)
        # so the overlay's "Face N" can be located on the model itself.
        # Use a name for the label so it can be removed reliably across
        # PyVista versions (add_point_labels return type varies).
        centroid = np.asarray(sub.points, dtype=np.float64).mean(axis=0)
        label_name = f"pick_label_{pid}"
        plotter.add_point_labels(
            [centroid.tolist()],
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
        pid_to_actors[pid] = (sub_actor, label_name)
        return True

    def _remove_pick(pid: str) -> None:
        sub_actor, label_name = pid_to_actors.pop(pid)
        plotter.remove_actor(sub_actor)
        plotter.remove_actor(label_name)
        pick_state['picks'] = [
            (p, lbl) for (p, lbl) in pick_state['picks'] if p != pid
        ]

    def _toggle(actor, face_idx: int) -> None:
        info = actor_lookup.get(actor)
        if info is None:
            return
        _cell_face_index, face_pids, _mesh = info
        if face_idx < 0 or face_idx >= len(face_pids):
            return
        pid = face_pids[face_idx]
        if pid in pid_to_actors:
            _remove_pick(pid)               # click the current pick -> deselect
        else:
            if single:
                # One face at a time: a new pick replaces the previous one.
                for prev in list(pid_to_actors):
                    _remove_pick(prev)
            label = "Face 1" if single else f"Face {next_pick_n[0]}"
            if not _add_highlight(actor, face_idx, pid, label):
                return
            if not single:
                next_pick_n[0] += 1
            pick_state['picks'].append((pid, label))
        _refresh_overlay()

    # Re-highlight any picks the caller passed in (so reopening the picker
    # visually shows what was already selected, with the original labels).
    pid_to_location: Dict[str, tuple] = {}
    for actor, (_cfi, face_pids, _mesh) in actor_lookup.items():
        for idx, pid in enumerate(face_pids):
            pid_to_location[pid] = (actor, idx)
    for pid, label in pick_state['picks']:
        loc = pid_to_location.get(pid)
        if loc is not None:
            actor, idx = loc
            _add_highlight(actor, idx, pid, label)

    def _on_pick_click(x, y):
        picker.Pick(x, y, 0, plotter.renderer)
        cell_id = picker.GetCellId()
        if cell_id < 0:
            return
        actor = picker.GetActor()
        if actor is None or actor not in actor_lookup:
            return
        cell_face_index, _pids, _mesh = actor_lookup[actor]
        _toggle(actor, int(cell_face_index[cell_id]))

    _on_left_click(plotter, _on_pick_click)


def _setup_multi_vertex_picking(plotter, vertex_entries, pick_state,
                                single=False):
    """Wire up vertex picking across multiple part point-cloud actors.

    Mirror of ``_setup_multi_face_picking`` for topological vertices: each
    part contributes a points actor with one VTK point per CAD vertex. The
    user left-clicks a vertex to toggle it (a left drag rotates the camera); a
    vtkPointPicker maps the click to the nearest point id, which indexes the
    parallel ``vertex_pids`` list. Picks accumulate as ``(pid, label)`` in
    ``pick_state['picks']`` with auto labels ``Vertex N``.

    Args:
        plotter: The active pv.Plotter.
        vertex_entries: List of ``(label, actor, points, vertex_pids)`` where
            ``points`` is an (N,3) ndarray and ``vertex_pids`` the parallel
            ``V{n}`` id list.
        pick_state: Dict with a ``picks`` list of ``(pid, label)``.
        single: When True, only one vertex may be selected at a time — picking
            a different vertex replaces the previous selection (for the
            refinement anchor). When False (default), picks accumulate.
    """
    import vtk

    picker = vtk.vtkPointPicker()
    picker.SetTolerance(0.01)

    # vtkActor → (points ndarray (N,3), vertex_pids list)
    actor_lookup: Dict[Any, tuple] = {}
    for _label, actor, points, vpids in vertex_entries:
        actor_lookup[actor] = (np.asarray(points, dtype=np.float64), vpids)

    # Per-pid highlight + label actors, so toggling off can remove both.
    pid_to_actors: Dict[str, tuple] = {}
    next_pick_n = [_next_auto_pick_number(pick_state['picks'], prefix="Vertex")]

    def _overlay_text() -> str:
        if not pick_state['picks']:
            if single:
                return ("Vertex picker: left-click a vertex to select.\n"
                        "Picking another vertex replaces the selection.\n"
                        "No vertex selected yet.")
            return ("Vertex picker: left-click a vertex to pick/unpick.\n"
                    "Use the checkboxes on the left to hide/show parts.\n"
                    "No vertices picked yet.")
        header = ("Selected vertex (left-click another to replace):" if single
                  else "Picked vertices (left-click to toggle):")
        lines = [header]
        for pid, label in pick_state['picks']:
            lines.append(f"  {label}  [{pid}]")
        return "\n".join(lines)

    _OVERLAY_NAME = 'vertex_pick_overlay'
    plotter.add_text(
        _overlay_text(), position='upper_right', font_size=10,
        color='yellow', shadow=True, name=_OVERLAY_NAME,
    )

    def _refresh_overlay():
        # Re-add by name to update — see the note in _setup_multi_face_picking:
        # add_text returns a vtkCornerAnnotation (no SetInput); replacing by
        # name is the version-robust way to refresh the overlay text.
        plotter.add_text(
            _overlay_text(), position='upper_right', font_size=10,
            color='yellow', shadow=True, name=_OVERLAY_NAME,
        )
        plotter.render()

    def _add_highlight(actor, vidx: int, pid: str, label: str) -> bool:
        points, _vpids = actor_lookup[actor]
        if vidx < 0 or vidx >= len(points):
            return False
        loc = points[vidx]
        # A larger highlight sphere sits on the picked vertex; a billboarded
        # label floats at the same spot so the overlay's "Vertex N" can be
        # located on the model. Named so it can be removed reliably.
        sub_actor = plotter.add_points(
            np.asarray([loc], dtype=np.float64),
            color=PICK_HIGHLIGHT_COLOR, render_points_as_spheres=True,
            point_size=20, pickable=False,
        )
        label_name = f"vtx_pick_label_{pid}"
        plotter.add_point_labels(
            [loc.tolist()],
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
        pid_to_actors[pid] = (sub_actor, label_name)
        return True

    def _remove_pick(pid: str) -> None:
        sub_actor, label_name = pid_to_actors.pop(pid)
        plotter.remove_actor(sub_actor)
        plotter.remove_actor(label_name)
        pick_state['picks'] = [
            (p, lbl) for (p, lbl) in pick_state['picks'] if p != pid
        ]

    def _toggle(actor, vidx: int) -> None:
        info = actor_lookup.get(actor)
        if info is None:
            return
        _points, vpids = info
        if vidx < 0 or vidx >= len(vpids):
            return
        pid = vpids[vidx]
        if pid in pid_to_actors:
            _remove_pick(pid)               # click the current pick -> deselect
        else:
            if single:
                # One vertex at a time: a new pick replaces the previous one.
                for prev in list(pid_to_actors):
                    _remove_pick(prev)
            label = "Vertex 1" if single else f"Vertex {next_pick_n[0]}"
            if not _add_highlight(actor, vidx, pid, label):
                return
            if not single:
                next_pick_n[0] += 1
            pick_state['picks'].append((pid, label))
        _refresh_overlay()

    # Re-highlight any picks the caller passed in (reopening shows the
    # existing selection with its original labels).
    pid_to_location: Dict[str, tuple] = {}
    for actor, (_points, vpids) in actor_lookup.items():
        for idx, pid in enumerate(vpids):
            pid_to_location[pid] = (actor, idx)
    for pid, label in pick_state['picks']:
        loc = pid_to_location.get(pid)
        if loc is not None:
            actor, idx = loc
            _add_highlight(actor, idx, pid, label)

    def _on_pick_click(x, y):
        picker.Pick(x, y, 0, plotter.renderer)
        point_id = picker.GetPointId()
        if point_id < 0:
            return
        actor = picker.GetActor()
        if actor is None or actor not in actor_lookup:
            return
        _toggle(actor, int(point_id))

    _on_left_click(plotter, _on_pick_click)


def _setup_multi_edge_picking(plotter, edge_entries, pick_state, single=False):
    """Wire up edge picking across multiple part line actors.

    Mirror of ``_setup_multi_face_picking`` for CAD edges: each part contributes
    a line actor (one polyline cell per edge) carrying ``edge_index`` cell_data
    and ``edge_pids`` field_data. A ``vtkCellPicker`` maps a clicked segment to
    its cell, whose ``edge_index`` indexes the parallel ``edge_pids``. Picks
    accumulate as ``(pid, label)`` in ``pick_state['picks']`` with auto labels
    ``Edge N`` (a left drag rotates the camera instead).

    Args:
        plotter: The active pv.Plotter.
        edge_entries: List of ``(label, actor, line_mesh)`` where ``line_mesh``
            carries ``cell_data["edge_index"]`` + ``field_data["edge_pids"]``
            (from ``edge_lines_polydata``).
        pick_state: Dict with a ``picks`` list of ``(pid, label)``.
        single: When True, only one edge may be selected at a time.
    """
    import vtk

    picker = vtk.vtkCellPicker()
    picker.SetTolerance(0.01)   # looser than faces — edges are thin curves

    # vtkActor → (cell_edge_index ndarray, edge_pids list, owning line mesh)
    actor_lookup: Dict[Any, tuple] = {}
    for _label, actor, mesh in edge_entries:
        cell_edge_index = mesh.cell_data.get("edge_index")
        edge_pids_arr = mesh.field_data.get("edge_pids")
        if cell_edge_index is None or edge_pids_arr is None:
            continue
        actor_lookup[actor] = (
            np.asarray(cell_edge_index, dtype=np.int32),
            [str(p) for p in edge_pids_arr],
            mesh,
        )

    pid_to_actors: Dict[str, tuple] = {}
    next_pick_n = [_next_auto_pick_number(pick_state['picks'], prefix="Edge")]

    def _overlay_text() -> str:
        if not pick_state['picks']:
            if single:
                return ("Edge picker: left-click an edge to select.\n"
                        "Picking another edge replaces the selection.\n"
                        "No edge selected yet.")
            return ("Edge picker: left-click an edge to pick/unpick.\n"
                    "Use the checkboxes on the left to hide/show parts.\n"
                    "No edges picked yet.")
        header = ("Selected edge (left-click another to replace):" if single
                  else "Picked edges (left-click to toggle):")
        lines = [header]
        for pid, label in pick_state['picks']:
            lines.append(f"  {label}  [{pid}]")
        return "\n".join(lines)

    _OVERLAY_NAME = 'edge_pick_overlay'
    plotter.add_text(
        _overlay_text(), position='upper_right', font_size=10,
        color='yellow', shadow=True, name=_OVERLAY_NAME,
    )

    def _refresh_overlay():
        # Re-add by name to update (see _setup_multi_face_picking's note).
        plotter.add_text(
            _overlay_text(), position='upper_right', font_size=10,
            color='yellow', shadow=True, name=_OVERLAY_NAME,
        )
        plotter.render()

    def _add_highlight(actor, edge_idx: int, pid: str, label: str) -> bool:
        cell_edge_index, _pids, mesh = actor_lookup[actor]
        cell_ids = np.where(cell_edge_index == edge_idx)[0]
        if len(cell_ids) == 0:
            return False
        sub = mesh.extract_cells(cell_ids)
        sub_actor = plotter.add_mesh(
            sub, color=PICK_HIGHLIGHT_COLOR, line_width=6,
            render_lines_as_tubes=True, lighting=False, pickable=False,
        )
        # Billboarded label at the edge midpoint so the overlay's "Edge N" can
        # be located on the model. Named for reliable removal across versions.
        centroid = np.asarray(sub.points, dtype=np.float64).mean(axis=0)
        label_name = f"edge_pick_label_{pid}"
        plotter.add_point_labels(
            [centroid.tolist()],
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
        pid_to_actors[pid] = (sub_actor, label_name)
        return True

    def _remove_pick(pid: str) -> None:
        sub_actor, label_name = pid_to_actors.pop(pid)
        plotter.remove_actor(sub_actor)
        plotter.remove_actor(label_name)
        pick_state['picks'] = [
            (p, lbl) for (p, lbl) in pick_state['picks'] if p != pid
        ]

    def _toggle(actor, edge_idx: int) -> None:
        info = actor_lookup.get(actor)
        if info is None:
            return
        _cell_edge_index, edge_pids, _mesh = info
        if edge_idx < 0 or edge_idx >= len(edge_pids):
            return
        pid = edge_pids[edge_idx]
        if pid in pid_to_actors:
            _remove_pick(pid)               # click the current pick -> deselect
        else:
            if single:
                for prev in list(pid_to_actors):
                    _remove_pick(prev)
            label = "Edge 1" if single else f"Edge {next_pick_n[0]}"
            if not _add_highlight(actor, edge_idx, pid, label):
                return
            if not single:
                next_pick_n[0] += 1
            pick_state['picks'].append((pid, label))
        _refresh_overlay()

    # Re-highlight any picks the caller passed in (reopening shows the existing
    # selection with its original labels).
    pid_to_location: Dict[str, tuple] = {}
    for actor, (cell_edge_index, edge_pids, _mesh) in actor_lookup.items():
        for idx, pid in enumerate(edge_pids):
            pid_to_location[pid] = (actor, idx)
    for pid, label in pick_state['picks']:
        loc = pid_to_location.get(pid)
        if loc is not None:
            actor, idx = loc
            _add_highlight(actor, idx, pid, label)

    def _on_pick_click(x, y):
        picker.Pick(x, y, 0, plotter.renderer)
        cell_id = picker.GetCellId()
        if cell_id < 0:
            return
        actor = picker.GetActor()
        if actor is None or actor not in actor_lookup:
            return
        cell_edge_index, _pids, _mesh = actor_lookup[actor]
        if cell_id >= len(cell_edge_index):
            return
        _toggle(actor, int(cell_edge_index[cell_id]))

    _on_left_click(plotter, _on_pick_click)

