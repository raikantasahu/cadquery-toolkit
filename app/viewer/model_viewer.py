"""
model_viewer.py - PyVista-based CAD Model Viewer


Usage:
    viewer = ModelViewer()
    viewer.connect('viewer-closed', on_viewer_closed)
    viewer.set_mesh_from_dict(model_data)
    viewer.show_viewer()
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, GLib

import numpy as np
import pyvista as pv
from typing import Any, Dict, List, Optional


# ── Helpers for reading CAD_ModelData ────────────────────────────────────────


def _ci_get(d: Dict[str, Any], name: str, default: Any = None) -> Any:
    """Case-insensitive dict lookup.

    Lets us read both camelCase (Python writer) and PascalCase (C# writer)
    CAD_ModelData JSON without caring which side produced it.
    """
    if name in d:
        return d[name]
    lower = name.lower()
    for k, v in d.items():
        if k.lower() == lower:
            return v
    return default


def _identity_matrix() -> List[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _matmul4(a: List[float], b: List[float]) -> List[float]:
    """Multiply two row-major 4x4 matrices given as flat 16-element lists."""
    A = np.asarray(a, dtype=np.float64).reshape(4, 4)
    B = np.asarray(b, dtype=np.float64).reshape(4, 4)
    return (A @ B).flatten().tolist()


def _transform_points(points: np.ndarray, matrix: List[float]) -> np.ndarray:
    """Apply a row-major 4x4 affine transform to an (N,3) point array."""
    M = np.asarray(matrix, dtype=np.float64).reshape(4, 4)
    R = M[:3, :3]
    t = M[:3, 3]
    return points @ R.T + t


def _emit_face(
    face: Dict[str, Any],
    transform: List[float],
    all_vertices: List[List[float]],
    all_faces: List[int],
    vertex_offset: List[int],
    cell_face_index: Optional[List[int]] = None,
    face_index: int = -1,
) -> None:
    """Append the triangles of one face to the running PolyData buffers.

    If ``cell_face_index`` is provided, ``face_index`` is appended once
    per emitted triangle so picking can map a clicked cell back to its
    parent CAD face. ``face_index`` references a parallel list of
    persistent IDs maintained by the caller.
    """
    vertex_locations = _ci_get(face, "vertexLocations") or []
    connectivity = _ci_get(face, "connectivity") or []

    if not vertex_locations or not connectivity:
        return

    num_vertices = len(vertex_locations) // 3
    pts = np.asarray(vertex_locations, dtype=np.float64).reshape(num_vertices, 3)
    pts_world = _transform_points(pts, transform)
    all_vertices.extend(pts_world.tolist())

    num_triangles = len(connectivity) // 3
    base = vertex_offset[0]
    for i in range(num_triangles):
        all_faces.extend([
            3,
            base + connectivity[i * 3],
            base + connectivity[i * 3 + 1],
            base + connectivity[i * 3 + 2],
        ])
    if cell_face_index is not None:
        cell_face_index.extend([face_index] * num_triangles)
    vertex_offset[0] += num_vertices


def _walk_envelope(
    models: List[Dict[str, Any]],
    model_index: int,
    parent_transform: List[float],
    all_vertices: List[List[float]],
    all_faces: List[int],
    vertex_offset: List[int],
    visited: set,
    cell_face_index: Optional[List[int]] = None,
    face_pids: Optional[List[str]] = None,
) -> None:
    """Recursively emit faces from one model and its children, in world space.

    `parent_transform` is the world-space placement of this model. Each
    Component holds a child's local-to-parent transform; we compose with the
    parent to obtain the child's world transform.

    If ``cell_face_index``/``face_pids`` are provided, each emitted face
    is appended to ``face_pids`` (verbatim PID string from CAD_ModelData)
    and every triangle stamped with that face's index in ``face_pids``.
    """
    if model_index in visited:
        # True cycle: this model is its own ancestor on the current
        # recursion path. The envelope is acyclic by construction, but
        # guard anyway to avoid infinite recursion on malformed input.
        return
    # Rebind to a new set local to this call so sibling traversals don't
    # inherit each other's "seen" markers — required for shared sub-models
    # (a single PART referenced by multiple Component instances).
    visited = visited | {model_index}

    model = models[model_index]

    for face in _ci_get(model, "faceList") or []:
        face_index = -1
        if face_pids is not None:
            pid = _ci_get(face, "persistentID")
            face_index = len(face_pids)
            face_pids.append(str(pid) if pid is not None else f"_{face_index}")
        _emit_face(
            face, parent_transform, all_vertices, all_faces, vertex_offset,
            cell_face_index=cell_face_index, face_index=face_index,
        )

    for component in _ci_get(model, "childComponents") or []:
        child_index = int(_ci_get(component, "childIndex", 0) or 0)
        if child_index < 0 or child_index >= len(models):
            continue
        child_local = _ci_get(component, "transformToParent") or _identity_matrix()
        child_world = _matmul4(parent_transform, child_local)
        _walk_envelope(
            models,
            child_index,
            child_world,
            all_vertices,
            all_faces,
            vertex_offset,
            visited,
            cell_face_index=cell_face_index,
            face_pids=face_pids,
        )


def create_polydata_from_model_data(
    data: Dict[str, Any], with_face_index: bool = False,
) -> pv.PolyData:
    """Convert a CAD_ModelData dict to PyVista PolyData.

    Accepts either format produced by this project:

    1. **Envelope** (multi-model assembly):
       ``{"rootIndex": int, "models": [...]}``. Each model has its own
       ``faceList`` (in its local frame) and a ``childComponents`` list
       describing nested placements via ``transformToParent``. We walk the
       tree starting at ``rootIndex`` and accumulate all faces in world
       space, applying composed transforms along the way.

    2. **Flat single-model** (legacy / single-PART output):
       a top-level dict with a ``faceList`` directly on it. Faces are
       used as-is (identity transform).

    Both PascalCase and camelCase property names are accepted.

    If ``with_face_index`` is True, the returned PolyData gets a
    ``face_index`` cell-data array (one int per triangle) and a
    ``face_pids`` field-data array (the parallel list of persistent IDs,
    indexed by ``face_index``). Used by the face-picker.

    Raises:
        ValueError: If no valid geometry is found in the data.
    """
    all_vertices: List[List[float]] = []
    all_faces: List[int] = []
    vertex_offset: List[int] = [0]  # boxed so helpers can mutate it

    cell_face_index: Optional[List[int]] = [] if with_face_index else None
    face_pids: Optional[List[str]] = [] if with_face_index else None

    models = _ci_get(data, "models")
    if isinstance(models, list) and models:
        root_index = int(_ci_get(data, "rootIndex", 0) or 0)
        if root_index < 0 or root_index >= len(models):
            raise ValueError(
                f"rootIndex {root_index} out of range (0..{len(models) - 1})"
            )
        _walk_envelope(
            models,
            root_index,
            _identity_matrix(),
            all_vertices,
            all_faces,
            vertex_offset,
            visited=set(),
            cell_face_index=cell_face_index,
            face_pids=face_pids,
        )
    else:
        # Flat single-model fallback.
        identity = _identity_matrix()
        for face in _ci_get(data, "faceList") or []:
            face_index = -1
            if face_pids is not None:
                pid = _ci_get(face, "persistentID")
                face_index = len(face_pids)
                face_pids.append(
                    str(pid) if pid is not None else f"_{face_index}"
                )
            _emit_face(
                face, identity, all_vertices, all_faces, vertex_offset,
                cell_face_index=cell_face_index, face_index=face_index,
            )

    if not all_vertices:
        raise ValueError("No valid geometry found in data")

    vertices = np.array(all_vertices, dtype=np.float64)
    faces = np.array(all_faces, dtype=np.int64)

    mesh = pv.PolyData(vertices, faces)
    mesh.compute_normals(inplace=True)
    if with_face_index and cell_face_index is not None:
        mesh.cell_data["face_index"] = np.asarray(
            cell_face_index, dtype=np.int32,
        )
        mesh.field_data["face_pids"] = np.asarray(face_pids, dtype=object)
    return mesh


def create_polydatas_per_part(
    data: Dict[str, Any], with_face_index: bool = False,
) -> List[tuple]:
    """Build one PolyData per leaf part instance.

    Walks the envelope and emits a separate PolyData every time a model
    with a non-empty ``faceList`` is reached (in world space, with
    composed parent transforms). This lets the viewer add each part as
    its own actor so users can hide/show parts independently.

    If ``with_face_index`` is True, each PolyData carries a ``face_index``
    cell-data array (one int per triangle) and a ``face_pids`` field-data
    array of persistent IDs. PIDs are numbered globally across all parts
    in traversal order (``F0``, ``F1``, …) so they line up with the
    mesher's flat Gmsh-surface-tag enumeration after STEP import.

    Returns a list of ``(label, pv.PolyData)`` pairs in traversal order.
    Labels come from the leaf model's ``componentName``/``modelName``,
    with a ``#N`` suffix when the same name appears more than once.

    Raises:
        ValueError: If no valid geometry is found in the data.
    """
    parts: List[tuple] = []
    label_counts: Dict[str, int] = {}
    global_face_counter = [0]

    def _label_for(model: Dict[str, Any]) -> str:
        name = (
            _ci_get(model, "componentName")
            or _ci_get(model, "modelName")
            or "part"
        )
        name = str(name)
        label_counts[name] = label_counts.get(name, 0) + 1
        n = label_counts[name]
        return name if n == 1 else f"{name} #{n}"

    def _emit_part(model: Dict[str, Any], transform: List[float]) -> None:
        face_list = _ci_get(model, "faceList") or []
        if not face_list:
            return

        all_vertices: List[List[float]] = []
        all_faces: List[int] = []
        vertex_offset: List[int] = [0]
        cell_face_index: Optional[List[int]] = [] if with_face_index else None
        face_pids: Optional[List[str]] = [] if with_face_index else None

        for face in face_list:
            face_index = -1
            if face_pids is not None:
                face_index = len(face_pids)
                face_pids.append(f"F{global_face_counter[0]}")
                global_face_counter[0] += 1
            _emit_face(
                face, transform, all_vertices, all_faces, vertex_offset,
                cell_face_index=cell_face_index, face_index=face_index,
            )

        if not all_vertices:
            return

        vertices = np.array(all_vertices, dtype=np.float64)
        faces = np.array(all_faces, dtype=np.int64)
        mesh = pv.PolyData(vertices, faces)
        mesh.compute_normals(inplace=True)
        if with_face_index and cell_face_index is not None:
            mesh.cell_data["face_index"] = np.asarray(
                cell_face_index, dtype=np.int32,
            )
            mesh.field_data["face_pids"] = np.asarray(face_pids, dtype=object)

        parts.append((_label_for(model), mesh))

    def _walk(models, model_index, transform, visited):
        if model_index in visited:
            return
        visited = visited | {model_index}
        model = models[model_index]
        _emit_part(model, transform)
        for component in _ci_get(model, "childComponents") or []:
            child_index = int(_ci_get(component, "childIndex", 0) or 0)
            if child_index < 0 or child_index >= len(models):
                continue
            child_local = (
                _ci_get(component, "transformToParent") or _identity_matrix()
            )
            child_world = _matmul4(transform, child_local)
            _walk(models, child_index, child_world, visited)

    models = _ci_get(data, "models")
    if isinstance(models, list) and models:
        root_index = int(_ci_get(data, "rootIndex", 0) or 0)
        if root_index < 0 or root_index >= len(models):
            raise ValueError(
                f"rootIndex {root_index} out of range (0..{len(models) - 1})"
            )
        _walk(models, root_index, _identity_matrix(), visited=set())
    else:
        _emit_part(data, _identity_matrix())

    if not parts:
        raise ValueError("No valid geometry found in data")

    return parts


# ── Display constants ────────────────────────────────────────────────────────

DEFAULT_COLOR = '#667eea'
VOLUMETRIC_COLOR = '#4fc3f7'
BACKGROUND_COLOR = '#1a1a1a'
PICK_HIGHLIGHT_COLOR = '#ffeb3b'


def _next_auto_pick_number(picks: List[tuple]) -> int:
    """Pick a counter start so new auto-labels don't collide with existing ones.

    Existing labels of the form ``"Face N"`` (the picker's default) seed
    the counter to max(N)+1; non-matching labels (e.g. user-renamed
    "Top surface") are ignored. Returns 1 when ``picks`` is empty.
    """
    used = []
    for _pid, label in picks:
        parts = str(label).split()
        if len(parts) == 2 and parts[0] == "Face" and parts[1].isdigit():
            used.append(int(parts[1]))
    return (max(used) + 1) if used else 1


def _vtk_interactor(plotter):
    """Return the raw vtkRenderWindowInteractor from a PyVista plotter.

    Newer PyVista wraps the raw vtkRenderWindowInteractor in a
    RenderWindowInteractor helper; older versions expose it directly.
    """
    iren = plotter.iren
    return getattr(iren, 'interactor', iren)


def _setup_multi_face_picking(plotter, part_entries, pick_state):
    """Wire up face picking across multiple part actors.

    Args:
        plotter: The active pv.Plotter.
        part_entries: List of ``(label, actor, mesh)`` for each part
            currently shown. Each ``mesh`` must carry ``face_index``
            cell_data and ``face_pids`` field_data.
        pick_state: Dict with ``picks`` list of ``(pid, label)``.

    User presses 'p' with the cursor over a face to toggle the face under
    the cursor. Only cells of visible actors are picked (VTK's
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
            return ("Face picker: 'p' over a face to pick/unpick.\n"
                    "Use the checkboxes on the left to hide/show parts.\n"
                    "No faces picked yet.")
        lines = ["Picked faces ('p' to toggle):"]
        for pid, label in pick_state['picks']:
            lines.append(f"  {label}  [{pid}]")
        return "\n".join(lines)

    text_actor = plotter.add_text(
        _overlay_text(), position='upper_right', font_size=10,
        color='yellow', shadow=True,
    )

    def _refresh_overlay():
        text_actor.SetInput(_overlay_text())
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

    def _toggle(actor, face_idx: int) -> None:
        info = actor_lookup.get(actor)
        if info is None:
            return
        cell_face_index, face_pids, _mesh = info
        if face_idx < 0 or face_idx >= len(face_pids):
            return
        pid = face_pids[face_idx]
        if pid in pid_to_actors:
            sub_actor, label_name = pid_to_actors.pop(pid)
            plotter.remove_actor(sub_actor)
            plotter.remove_actor(label_name)
            pick_state['picks'] = [
                (p, lbl) for (p, lbl) in pick_state['picks'] if p != pid
            ]
        else:
            label = f"Face {next_pick_n[0]}"
            if not _add_highlight(actor, face_idx, pid, label):
                return
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

    def _on_pick_key():
        x, y = _vtk_interactor(plotter).GetEventPosition()
        picker.Pick(x, y, 0, plotter.renderer)
        cell_id = picker.GetCellId()
        if cell_id < 0:
            return
        actor = picker.GetActor()
        if actor is None or actor not in actor_lookup:
            return
        cell_face_index, _pids, _mesh = actor_lookup[actor]
        _toggle(actor, int(cell_face_index[cell_id]))

    plotter.add_key_event('p', _on_pick_key)


def _add_visibility_checkboxes(plotter, part_entries):
    """Add a column of checkbox widgets to toggle each part's visibility.

    Each part actor gets one checkbox; clicking it flips the actor's
    visibility. Labels are added as text actors next to each checkbox.

    PyVista positions widgets in pixel coordinates with origin at the
    lower-left of the render window, so the column grows upward from
    near the bottom. The starting ``y`` is set above the help-text band.
    """
    button_size = 18
    pad = 6
    y = 50
    for label, actor, _mesh in part_entries:
        def _make_cb(a=actor):
            def cb(state):
                a.SetVisibility(1 if state else 0)
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


def show_pick_viewer(parts, title="Pick Faces", pick_state=None):
    """Open a PyVista viewer with per-part actors, visibility toggles, and
    face picking.

    Args:
        parts: List of ``(label, pv.PolyData)`` from
            ``create_polydatas_per_part(..., with_face_index=True)``.
        title: Window title.
        pick_state: Required dict with a ``picks`` list; the caller
            reads ``picks`` (list of ``(pid, label)``) after the window
            closes.

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

    _add_visibility_checkboxes(plotter, part_entries)
    if pick_state is not None:
        _setup_multi_face_picking(plotter, part_entries, pick_state)

    plotter.add_text(
        "Views: F/B/L/G/T/U  R=Reset  P=Pick face  Q=Quit",
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
                    initial_picks: Optional[List[tuple]] = None) -> None:
        """
        Open the 3D viewer window.

        This is a blocking call - it will return when the viewer is closed.

        Args:
            title: Window title.
            pick_faces: When True, enable face picking on the displayed
                CAD model. After the viewer closes, ``picked_faces``
                holds the user's selection as ``[(persistent_id, label)]``.
            initial_picks: Optional list of ``(persistent_id, label)`` to
                pre-populate; only respected when ``pick_faces`` is True
                and the mesh carries face indices.
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
        """Return the most recent face picks as ``[(persistent_id, label)]``.

        Empty if the viewer was never run in ``pick_faces=True`` mode.
        """
        return list(self._last_picks)

    def clear(self) -> None:
        """Clear the loaded mesh"""
        self._mesh = None
        self._parts = None
        self._is_volumetric = False
