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
) -> None:
    """Append the triangles of one face to the running PolyData buffers."""
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
    vertex_offset[0] += num_vertices


def _walk_envelope(
    models: List[Dict[str, Any]],
    model_index: int,
    parent_transform: List[float],
    all_vertices: List[List[float]],
    all_faces: List[int],
    vertex_offset: List[int],
    visited: set,
) -> None:
    """Recursively emit faces from one model and its children, in world space.

    `parent_transform` is the world-space placement of this model. Each
    Component holds a child's local-to-parent transform; we compose with the
    parent to obtain the child's world transform.
    """
    if model_index in visited:
        # Defensive: a properly written envelope is acyclic, but the C#
        # format allows shared sub-models, so don't infinite-loop on cycles.
        return
    visited.add(model_index)

    model = models[model_index]

    for face in _ci_get(model, "faceList") or []:
        _emit_face(face, parent_transform, all_vertices, all_faces, vertex_offset)

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
        )


def create_polydata_from_model_data(data: Dict[str, Any]) -> pv.PolyData:
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

    Raises:
        ValueError: If no valid geometry is found in the data.
    """
    all_vertices: List[List[float]] = []
    all_faces: List[int] = []
    vertex_offset: List[int] = [0]  # boxed so helpers can mutate it

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
        )
    else:
        # Flat single-model fallback.
        identity = _identity_matrix()
        for face in _ci_get(data, "faceList") or []:
            _emit_face(face, identity, all_vertices, all_faces, vertex_offset)

    if not all_vertices:
        raise ValueError("No valid geometry found in data")

    vertices = np.array(all_vertices, dtype=np.float64)
    faces = np.array(all_faces, dtype=np.int64)

    mesh = pv.PolyData(vertices, faces)
    mesh.compute_normals(inplace=True)
    return mesh


# ── Display constants ────────────────────────────────────────────────────────

DEFAULT_COLOR = '#667eea'
VOLUMETRIC_COLOR = '#4fc3f7'
BACKGROUND_COLOR = '#1a1a1a'


def show_pyvista(mesh, title="CAD Viewer", volumetric=False):
    """Open a PyVista plotter with standard CAD viewer styling.

    This is a blocking call — it returns when the viewer window is closed.

    Args:
        mesh: A PyVista PolyData or UnstructuredGrid.
        title: Window title.
        volumetric: If True, use volumetric styling (edges visible).
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
        self._is_open = False
        self._is_volumetric = False

    # =========================================================================
    # Mesh Loading
    # =========================================================================

    def set_mesh_from_dict(self, data: Dict[str, Any]) -> bool:
        """
        Load mesh from a CAD_ModelData or MeshData dictionary.

        Auto-detects the schema:
          - MeshData (volumetric): has ``nodes`` and ``fragments`` keys.
            Displayed with volumetric styling (edges visible).
          - CAD_ModelData (surface): everything else — envelope with
            ``models`` or flat with ``faceList``.

        Args:
            data: Dictionary in CAD_ModelData or MeshData format.

        Returns:
            True if successful, False otherwise.
        """
        try:
            if 'fragments' in data and 'nodes' in data:
                # Lazy import so model_viewer stays importable even when
                # the mesher package (pyvista/gmsh) isn't loaded yet.
                from mesher.meshdata_reader import meshdata_to_pyvista
                self._mesh = meshdata_to_pyvista(data)
                self._is_volumetric = True
            else:
                self._mesh = create_polydata_from_model_data(data)
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

    def show_viewer(self, title: str = "CAD Model Viewer") -> None:
        """
        Open the 3D viewer window.

        This is a blocking call - it will return when the viewer is closed.

        Args:
            title: Window title
        """
        if self._mesh is None:
            self.emit('error', "No mesh loaded. Call set_mesh_from_dict() first.")
            return

        self._is_open = True
        self.emit('viewer-opened')

        try:
            show_pyvista(self._mesh, title=title, volumetric=self._is_volumetric)
        finally:
            self._is_open = False
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

    def clear(self) -> None:
        """Clear the loaded mesh"""
        self._mesh = None
        self._is_volumetric = False
