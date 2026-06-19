"""
model_viewer.py - PyVista-based CAD Model Viewer


Usage:
    viewer = ModelViewer()
    viewer.connect('viewer-closed', on_viewer_closed)
    viewer.set_mesh_from_dict(model_data)
    viewer.show_viewer()
"""

import os

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, GLib

import numpy as np
import pyvista as pv
from typing import Any, Dict, List, Optional

from model.tessellation import (
    create_polydata_from_model_data,
    create_polydatas_per_part,
)


# ── Display constants ────────────────────────────────────────────────────────

DEFAULT_COLOR = '#667eea'
VOLUMETRIC_COLOR = '#4fc3f7'
# Viewer scene background. Defaults to a near-black dark grey; override with the
# VIEWER_BACKGROUND_COLOR env var (any pyvista-accepted color name or hex, e.g.
# VIEWER_BACKGROUND_COLOR=white). Read once at import, so set it before launch.
BACKGROUND_COLOR = os.environ.get('VIEWER_BACKGROUND_COLOR', '#1a1a1a')
PICK_HIGHLIGHT_COLOR = '#ffeb3b'


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


def _add_visibility_checkboxes(plotter, part_entries,
                               extra_actors_by_label=None):
    """Add a column of checkbox widgets to toggle each part's visibility.

    Each part actor gets one checkbox; clicking it flips the actor's
    visibility. Labels are added as text actors next to each checkbox.

    ``extra_actors_by_label`` optionally maps a part label to a second actor
    (e.g. the part's vertex point-cloud in vertex-pick mode) that is toggled
    in lockstep with the part actor, so hiding a part also hides — and, since
    VTK pickers honor visibility, un-picks — its vertices.

    PyVista positions widgets in pixel coordinates with origin at the
    lower-left of the render window, so the column grows upward from
    near the bottom. The starting ``y`` is set above the help-text band.
    """
    extra_actors_by_label = extra_actors_by_label or {}
    button_size = 18
    pad = 6
    y = 50
    for label, actor, _mesh in part_entries:
        extra_actor = extra_actors_by_label.get(label)

        def _make_cb(a=actor, extra=extra_actor):
            def cb(state):
                v = 1 if state else 0
                a.SetVisibility(v)
                if extra is not None:
                    extra.SetVisibility(v)
                plotter.render()
            return cb
        plotter.add_checkbox_button_widget(
            _make_cb(),
            value=True,
            position=(10, y),
            size=button_size,
            border_size=2,
            color_on='#8bc34a',
            color_off='#555555',
            background_color='#222222',
        )
        plotter.add_text(
            label,
            position=(10 + button_size + 8, y + 2),
            font_size=9,
            color='white',
            shadow=True,
        )
        y += button_size + pad


def show_pick_viewer(parts, title="Pick Faces", pick_state=None,
                     pick_mode="faces", single=False):
    """Open a PyVista viewer with per-part actors, visibility toggles, and
    face or vertex picking.

    Args:
        parts: List of ``(label, pv.PolyData)`` from
            ``create_polydatas_per_part(..., with_face_index=True)``.
        title: Window title.
        pick_state: Required dict with a ``picks`` list; the caller
            reads ``picks`` (list of ``(pid, label)``) after the window
            closes.
        pick_mode: ``"faces"`` (default) picks CAD faces; ``"vertices"``
            renders each part's topological vertices as a pickable point
            cloud (faces become non-pickable context) and picks those. In
            both modes a left-click toggles the entity under the cursor.

    This is a blocking call — it returns when the viewer window is closed.
    """
    plotter = pv.Plotter(title=title)
    plotter.set_background(BACKGROUND_COLOR)

    # One actor per part so visibility can be toggled independently.
    part_entries: List[tuple] = []
    combined_bounds = None
    for label, mesh in parts:
        actor = plotter.add_mesh(
            mesh,
            color=DEFAULT_COLOR,
            show_edges=False,
            lighting=True,
            smooth_shading=True,
            specular=0.5,
            specular_power=30,
        )
        part_entries.append((label, actor, mesh))
        b = mesh.bounds
        if combined_bounds is None:
            combined_bounds = list(b)
        else:
            combined_bounds[0] = min(combined_bounds[0], b[0])
            combined_bounds[1] = max(combined_bounds[1], b[1])
            combined_bounds[2] = min(combined_bounds[2], b[2])
            combined_bounds[3] = max(combined_bounds[3], b[3])
            combined_bounds[4] = min(combined_bounds[4], b[4])
            combined_bounds[5] = max(combined_bounds[5], b[5])

    bounds = combined_bounds or (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
    center = np.array([
        (bounds[0] + bounds[1]) / 2,
        (bounds[2] + bounds[3]) / 2,
        (bounds[4] + bounds[5]) / 2,
    ])
    size = max(
        bounds[1] - bounds[0],
        bounds[3] - bounds[2],
        bounds[5] - bounds[4],
    )
    distance = size * 2.5

    grid_size = max(200, size * 4)
    grid = pv.Plane(
        center=(center[0], center[1], bounds[4] - size * 0.1),
        direction=(0, 0, 1),
        i_size=grid_size,
        j_size=grid_size,
        i_resolution=20,
        j_resolution=20,
    )
    grid_actor = plotter.add_mesh(
        grid, color='#333333', style='wireframe',
        line_width=1, opacity=0.5,
    )
    grid_actor.PickableOff()  # don't let the floor steal picks

    plotter.enable_3_lights()
    plotter.show_axes()
    plotter.camera_position = [
        (center[0] + distance, center[1] + distance, center[2] + distance),
        tuple(center),
        (0, 0, 1),
    ]

    def _view(direction):
        positions = {
            'front':  ((center[0], center[1] - distance, center[2]), (0, 0, 1)),
            'back':   ((center[0], center[1] + distance, center[2]), (0, 0, 1)),
            'left':   ((center[0] - distance, center[1], center[2]), (0, 0, 1)),
            'right':  ((center[0] + distance, center[1], center[2]), (0, 0, 1)),
            'top':    ((center[0], center[1], center[2] + distance), (0, 1, 0)),
            'bottom': ((center[0], center[1], center[2] - distance), (0, 1, 0)),
        }
        pos, up = positions[direction]
        plotter.camera_position = [pos, tuple(center), up]
        plotter.render()

    plotter.add_key_event('f', lambda: _view('front'))
    plotter.add_key_event('b', lambda: _view('back'))
    plotter.add_key_event('l', lambda: _view('left'))
    plotter.add_key_event('g', lambda: _view('right'))
    plotter.add_key_event('t', lambda: _view('top'))
    plotter.add_key_event('u', lambda: _view('bottom'))

    # In vertex mode, build a pickable point cloud per part (faces become
    # context only) BEFORE the checkboxes, so each checkbox can toggle the
    # part's faces and its vertices together.
    vertex_entries: List[tuple] = []
    vertex_actor_by_label: Dict[str, Any] = {}
    if pick_state is not None and pick_mode == "vertices":
        for label, actor, mesh in part_entries:
            actor.PickableOff()
            vp = mesh.field_data.get("vertex_points")
            vpids = mesh.field_data.get("vertex_pids")
            if vp is None or vpids is None or len(vpids) == 0:
                continue
            points = np.asarray(vp, dtype=np.float64).reshape(-1, 3)
            vtx_actor = plotter.add_points(
                points, color='#ff5252', render_points_as_spheres=True,
                point_size=11,
            )
            vertex_actor_by_label[label] = vtx_actor
            vertex_entries.append(
                (label, vtx_actor, points, [str(p) for p in vpids]),
            )

    _add_visibility_checkboxes(
        plotter, part_entries, extra_actors_by_label=vertex_actor_by_label,
    )

    if pick_state is not None and pick_mode == "vertices":
        _setup_multi_vertex_picking(plotter, vertex_entries, pick_state,
                                    single=single)
    elif pick_state is not None:
        _setup_multi_face_picking(plotter, part_entries, pick_state,
                                  single=single)

    pick_help = "P=Pick vertex" if pick_mode == "vertices" else "P=Pick face"
    plotter.add_text(
        f"Views: F/B/L/G/T/U  R=Reset  {pick_help}  Q=Quit",
        position='lower_left',
        font_size=8,
        color='white',
        shadow=True,
    )

    plotter.show()


def show_pyvista(mesh, title="CAD Viewer", volumetric=False):
    """Open a PyVista plotter with standard CAD viewer styling.

    This is a blocking call — it returns when the viewer window is closed.

    Args:
        mesh: A PyVista PolyData or UnstructuredGrid.
        title: Window title.
        volumetric: If True, use volumetric styling (edges visible).

    For face picking (with per-part hide/show), use ``show_pick_viewer``.
    """
    plotter = pv.Plotter(title=title)
    plotter.set_background(BACKGROUND_COLOR)

    if volumetric:
        actor = plotter.add_mesh(
            mesh,
            color=VOLUMETRIC_COLOR,
            show_edges=True,
            edge_color='#333333',
            opacity=1.0,
            smooth_shading=False,
            lighting=True,
        )
    else:
        actor = plotter.add_mesh(
            mesh,
            color=DEFAULT_COLOR,
            show_edges=False,
            lighting=True,
            smooth_shading=True,
            specular=0.5,
            specular_power=30,
        )

    # Mesh geometry for camera / grid positioning
    bounds = mesh.bounds
    center = np.array([
        (bounds[0] + bounds[1]) / 2,
        (bounds[2] + bounds[3]) / 2,
        (bounds[4] + bounds[5]) / 2,
    ])
    size = max(
        bounds[1] - bounds[0],
        bounds[3] - bounds[2],
        bounds[5] - bounds[4],
    )
    distance = size * 2.5

    # Grid floor
    grid_size = max(200, size * 4)
    grid = pv.Plane(
        center=(center[0], center[1], bounds[4] - size * 0.1),
        direction=(0, 0, 1),
        i_size=grid_size,
        j_size=grid_size,
        i_resolution=20,
        j_resolution=20,
    )
    plotter.add_mesh(grid, color='#333333', style='wireframe',
                     line_width=1, opacity=0.5)

    # Lighting, axes, camera
    plotter.enable_3_lights()
    plotter.show_axes()
    plotter.camera_position = [
        (center[0] + distance, center[1] + distance, center[2] + distance),
        tuple(center),
        (0, 0, 1),
    ]

    # Key bindings
    def _view(direction):
        positions = {
            'front':  ((center[0], center[1] - distance, center[2]), (0, 0, 1)),
            'back':   ((center[0], center[1] + distance, center[2]), (0, 0, 1)),
            'left':   ((center[0] - distance, center[1], center[2]), (0, 0, 1)),
            'right':  ((center[0] + distance, center[1], center[2]), (0, 0, 1)),
            'top':    ((center[0], center[1], center[2] + distance), (0, 1, 0)),
            'bottom': ((center[0], center[1], center[2] - distance), (0, 1, 0)),
        }
        pos, up = positions[direction]
        plotter.camera_position = [pos, tuple(center), up]
        plotter.render()

    wireframe_state = [False]

    def _toggle_wireframe():
        wireframe_state[0] = not wireframe_state[0]
        if wireframe_state[0]:
            actor.GetProperty().SetRepresentationToWireframe()
        else:
            actor.GetProperty().SetRepresentationToSurface()
        plotter.render()

    plotter.add_key_event('f', lambda: _view('front'))
    plotter.add_key_event('b', lambda: _view('back'))
    plotter.add_key_event('l', lambda: _view('left'))
    plotter.add_key_event('g', lambda: _view('right'))
    plotter.add_key_event('t', lambda: _view('top'))
    plotter.add_key_event('u', lambda: _view('bottom'))
    plotter.add_key_event('z', _toggle_wireframe)

    plotter.add_text(
        "Views: F=Front  B=Back  L=Left  G=Right  T=Top  U=Bottom\n"
        "R=Reset  Z=Wireframe  Q=Quit",
        position='lower_left',
        font_size=8,
        color='white',
        shadow=True,
    )

    plotter.show()


class ModelViewer(GObject.Object):
    """
    GTK-compatible widget for 3D model viewing.

    This widget manages a PyVista plotter window and emits signals
    for GTK integration. The 3D view opens in a separate window.

    Signals:
        viewer-opened: Emitted when viewer window opens
        viewer-closed: Emitted when viewer window closes
        mesh-loaded: Emitted when a mesh is successfully loaded
            Args: info (dict) - mesh information
        error: Emitted when an error occurs
            Args: message (str)
    """

    __gtype_name__ = 'ModelViewerWidget'

    __gsignals__ = {
        'viewer-opened': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'viewer-closed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'mesh-loaded': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'error': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        """Initialize the ModelViewerWidget"""
        super().__init__()

        self._mesh = None
        # When the viewer is loaded with pick mode in mind, we also keep
        # a per-part split of the CAD geometry so each part can be shown
        # as its own actor (for hide/show + cell picking via picker.GetActor).
        self._parts: Optional[List[tuple]] = None
        self._is_open = False
        self._is_volumetric = False
        self._last_picks: List[tuple] = []

    # =========================================================================
    # Mesh Loading
    # =========================================================================

    def set_mesh_from_dict(
        self, data: Dict[str, Any], with_face_index: bool = False,
    ) -> bool:
        """
        Load mesh from a CAD_ModelData or MeshData dictionary.

        Auto-detects the schema:
          - MeshData (volumetric): has ``nodes`` and ``fragments`` keys.
            Displayed with volumetric styling (edges visible).
          - CAD_ModelData (surface): everything else — envelope with
            ``models`` or flat with ``faceList``.

        Args:
            data: Dictionary in CAD_ModelData or MeshData format.
            with_face_index: When True (CAD_ModelData only), tag each
                triangle with its parent face PID so the viewer can
                support face picking. Ignored for MeshData.

        Returns:
            True if successful, False otherwise.
        """
        try:
            if 'fragments' in data and 'nodes' in data:
                # Lazy import so model_viewer stays importable even when
                # the mesher package (pyvista/gmsh) isn't loaded yet.
                from mesher.meshdata_reader import meshdata_to_pyvista
                self._mesh = meshdata_to_pyvista(data)
                self._parts = None
                self._is_volumetric = True
            else:
                self._mesh = create_polydata_from_model_data(
                    data, with_face_index=with_face_index,
                )
                # Build the per-part split too when picking is in play, so
                # show_viewer can route to show_pick_viewer with one actor
                # per part for independent hide/show.
                self._parts = (
                    create_polydatas_per_part(data, with_face_index=True)
                    if with_face_index else None
                )
                self._is_volumetric = False
            info = self.get_mesh_info()
            self.emit('mesh-loaded', info)
            return True
        except Exception as e:
            self.emit('error', f"Failed to create mesh: {str(e)}")
            return False

    def set_mesh_from_pyvista(self, mesh) -> bool:
        """
        Load mesh from a PyVista dataset (PolyData or UnstructuredGrid).

        Args:
            mesh: A PyVista PolyData or UnstructuredGrid object.

        Returns:
            True if successful, False otherwise.
        """
        try:
            self._mesh = mesh
            self._parts = None
            self._is_volumetric = isinstance(mesh, pv.UnstructuredGrid)
            info = self.get_mesh_info()
            self.emit('mesh-loaded', info)
            return True
        except Exception as e:
            self.emit('error', f"Failed to set mesh: {str(e)}")
            return False

    # =========================================================================
    # Viewer Display
    # =========================================================================

    def show_viewer(self, title: str = "CAD Model Viewer",
                    pick_faces: bool = False,
                    initial_picks: Optional[List[tuple]] = None,
                    pick_mode: str = "faces",
                    single: bool = False) -> None:
        """
        Open the 3D viewer window.

        This is a blocking call - it will return when the viewer is closed.

        Args:
            title: Window title.
            pick_faces: When True, enable picking on the displayed CAD model.
                After the viewer closes, ``picked_faces``/``picked_vertices``
                holds the user's selection as ``[(persistent_id, label)]``.
            initial_picks: Optional list of ``(persistent_id, label)`` to
                pre-populate; only respected when ``pick_faces`` is True.
            pick_mode: ``"faces"`` (default) or ``"vertices"`` — which entity
                type to pick. Only meaningful when ``pick_faces`` is True.
            single: When True, restrict picking to one entity at a time (a new
                pick replaces the previous). Only meaningful when ``pick_faces``.
        """
        if self._mesh is None and self._parts is None:
            self.emit('error', "No mesh loaded. Call set_mesh_from_dict() first.")
            return

        self._is_open = True
        self.emit('viewer-opened')
        pick_state = (
            {'picks': list(initial_picks or [])} if pick_faces else None
        )

        try:
            if pick_faces and self._parts is not None:
                show_pick_viewer(
                    self._parts, title=title, pick_state=pick_state,
                    pick_mode=pick_mode, single=single,
                )
            else:
                show_pyvista(
                    self._mesh, title=title, volumetric=self._is_volumetric,
                )
        finally:
            self._is_open = False
            if pick_state is not None:
                self._last_picks = list(pick_state['picks'])
            GLib.idle_add(self._emit_closed)

    def _emit_closed(self) -> bool:
        """Emit viewer-closed signal (called via GLib.idle_add)"""
        self.emit('viewer-closed')
        return False  # Don't repeat

    # =========================================================================
    # Properties and Info
    # =========================================================================

    def get_mesh_info(self) -> Dict[str, Any]:
        """
        Get information about the loaded mesh.

        Returns:
            Dictionary with mesh information
        """
        if self._mesh is None:
            return {'loaded': False}

        bounds = self._mesh.bounds
        center = (
            (bounds[0] + bounds[1]) / 2,
            (bounds[2] + bounds[3]) / 2,
            (bounds[4] + bounds[5]) / 2,
        )
        size = max(
            bounds[1] - bounds[0],
            bounds[3] - bounds[2],
            bounds[5] - bounds[4],
        )

        return {
            'loaded': True,
            'n_points': self._mesh.n_points,
            'n_cells': self._mesh.n_cells,
            'bounds': bounds,
            'center': center,
            'size': size,
        }

    @property
    def is_open(self) -> bool:
        """Check if viewer window is currently open"""
        return self._is_open

    @property
    def has_mesh(self) -> bool:
        """Check if a mesh is loaded"""
        return self._mesh is not None

    @property
    def picked_faces(self) -> List[tuple]:
        """Return the most recent picks as ``[(persistent_id, label)]``.

        Empty if the viewer was never run in ``pick_faces=True`` mode. A
        viewer instance runs a single pick mode, so this returns whatever
        was picked (faces in face mode); ``picked_vertices`` is an alias for
        use after a ``pick_mode="vertices"`` run.
        """
        return list(self._last_picks)

    @property
    def picked_vertices(self) -> List[tuple]:
        """Return the most recent picks after a ``pick_mode="vertices"`` run.

        Alias of the same underlying ``_last_picks`` (a viewer instance only
        ever runs one pick mode), named for clarity at the call site.
        """
        return list(self._last_picks)

    def clear(self) -> None:
        """Clear the loaded mesh"""
        self._mesh = None
        self._parts = None
        self._is_volumetric = False
