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
from typing import Optional, Dict, Any

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

    # Default styling
    DEFAULT_COLOR = '#667eea'
    VOLUMETRIC_COLOR = '#4fc3f7'
    BACKGROUND_COLOR = '#1a1a1a'

    def __init__(self):
        """Initialize the ModelViewerWidget"""
        super().__init__()

        self._plotter: Optional[pv.Plotter] = None
        self._mesh: Optional[pv.PolyData] = None
        self._actor = None

        # Mesh properties
        self._mesh_center = np.array([0.0, 0.0, 0.0])
        self._mesh_size = 1.0

        # State
        self._wireframe_enabled = False
        self._is_open = False
        self._is_volumetric = False

    # =========================================================================
    # Mesh Loading
    # =========================================================================

    def set_mesh_from_exporter(self, exporter) -> bool:
        """
        Load mesh from a FreeCADExporter instance.

        Args:
            exporter: FreeCADExporter with exported model data

        Returns:
            True if successful, False otherwise
        """
        try:
            model_data = exporter.export()
            return self.set_mesh_from_dict(model_data)
        except Exception as e:
            self.emit('error', f"Failed to load from exporter: {str(e)}")
            return False

    def set_mesh_from_dict(self, data: Dict[str, Any]) -> bool:
        """
        Load mesh from CAD_ModelData dictionary.

        Args:
            data: Dictionary in CAD_ModelData format

        Returns:
            True if successful, False otherwise
        """
        try:
            self._create_mesh_from_dict(data)
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

            bounds = mesh.bounds
            self._mesh_center = np.array([
                (bounds[0] + bounds[1]) / 2,
                (bounds[2] + bounds[3]) / 2,
                (bounds[4] + bounds[5]) / 2
            ])
            self._mesh_size = max(
                bounds[1] - bounds[0],
                bounds[3] - bounds[2],
                bounds[5] - bounds[4]
            )

            info = self.get_mesh_info()
            self.emit('mesh-loaded', info)
            return True
        except Exception as e:
            self.emit('error', f"Failed to set mesh: {str(e)}")
            return False

    def _create_mesh_from_dict(self, data: Dict[str, Any]) -> None:
        """Create PyVista mesh from CAD_ModelData dictionary"""
        all_vertices = []
        all_faces = []
        vertex_offset = 0

        face_list = data.get('faceList', [])

        for face in face_list:
            vertex_locations = face.get('vertexLocations', [])
            connectivity = face.get('connectivity', [])

            if not vertex_locations or not connectivity:
                continue

            num_vertices = len(vertex_locations) // 3

            for i in range(num_vertices):
                all_vertices.append([
                    vertex_locations[i * 3],
                    vertex_locations[i * 3 + 1],
                    vertex_locations[i * 3 + 2]
                ])

            num_triangles = len(connectivity) // 3
            for i in range(num_triangles):
                all_faces.extend([
                    3,
                    vertex_offset + connectivity[i * 3],
                    vertex_offset + connectivity[i * 3 + 1],
                    vertex_offset + connectivity[i * 3 + 2]
                ])

            vertex_offset += num_vertices

        if not all_vertices:
            raise ValueError("No valid geometry found in data")

        vertices = np.array(all_vertices, dtype=np.float64)
        faces = np.array(all_faces, dtype=np.int64)

        self._mesh = pv.PolyData(vertices, faces)
        self._mesh.compute_normals(inplace=True)

        # Calculate mesh properties
        bounds = self._mesh.bounds
        self._mesh_center = np.array([
            (bounds[0] + bounds[1]) / 2,
            (bounds[2] + bounds[3]) / 2,
            (bounds[4] + bounds[5]) / 2
        ])
        self._mesh_size = max(
            bounds[1] - bounds[0],
            bounds[3] - bounds[2],
            bounds[5] - bounds[4]
        )

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
            self._plotter = pv.Plotter(title=title)
            self._plotter.set_background(self.BACKGROUND_COLOR)

            # Add mesh
            if self._is_volumetric:
                self._actor = self._plotter.add_mesh(
                    self._mesh,
                    color=self.VOLUMETRIC_COLOR,
                    show_edges=True,
                    edge_color='#333333',
                    opacity=1.0,
                    smooth_shading=False,
                    lighting=True,
                )
            else:
                self._actor = self._plotter.add_mesh(
                    self._mesh,
                    color=self.DEFAULT_COLOR,
                    show_edges=False,
                    lighting=True,
                    smooth_shading=True,
                    specular=0.5,
                    specular_power=30
                )

            # Add grid floor
            self._add_grid()

            # Set up lighting and camera
            self._plotter.enable_3_lights()
            self.reset_camera()
            self._plotter.show_axes()

            # Set up key bindings
            self._setup_key_bindings()

            # Add shortcuts overlay
            self._add_shortcuts_overlay()

            # Show (blocking)
            self._plotter.show()

        finally:
            self._is_open = False
            self._plotter = None
            self._actor = None

            # Emit closed signal on GTK main thread
            GLib.idle_add(self._emit_closed)

    def _emit_closed(self) -> bool:
        """Emit viewer-closed signal (called via GLib.idle_add)"""
        self.emit('viewer-closed')
        return False  # Don't repeat

    def _add_grid(self) -> None:
        """Add floor grid to the scene"""
        if self._mesh is None or self._plotter is None:
            return

        grid_size = max(200, self._mesh_size * 4)
        bounds = self._mesh.bounds
        z_min = bounds[4]

        grid = pv.Plane(
            center=(self._mesh_center[0], self._mesh_center[1], z_min - self._mesh_size * 0.1),
            direction=(0, 0, 1),
            i_size=grid_size,
            j_size=grid_size,
            i_resolution=20,
            j_resolution=20
        )

        self._plotter.add_mesh(
            grid,
            color='#333333',
            style='wireframe',
            line_width=1,
            opacity=0.5
        )

    def _setup_key_bindings(self) -> None:
        """Set up keyboard shortcuts (using letters to avoid VTK conflicts)"""
        if self._plotter is None:
            return

        # View shortcuts: F=front, B=back, L=left, G=riGht, T=top, U=under
        # R=reset (VTK built-in), Z=wireframe, Q=quit (VTK built-in)
        self._plotter.add_key_event('f', lambda: self.view_from('front'))
        self._plotter.add_key_event('b', lambda: self.view_from('back'))
        self._plotter.add_key_event('l', lambda: self.view_from('left'))
        self._plotter.add_key_event('g', lambda: self.view_from('right'))
        self._plotter.add_key_event('t', lambda: self.view_from('top'))
        self._plotter.add_key_event('u', lambda: self.view_from('bottom'))
        self._plotter.add_key_event('z', lambda: self.toggle_wireframe())

    def _add_shortcuts_overlay(self) -> None:
        """Add keyboard shortcuts overlay to the viewer"""
        if self._plotter is None:
            return

        shortcuts_text = (
            "Views: F=Front  B=Back  L=Left  G=Right  T=Top  U=Bottom\n"
            "R=Reset  Z=Wireframe  Q=Quit"
        )

        self._plotter.add_text(
            shortcuts_text,
            position='lower_left',
            font_size=8,
            color='white',
            shadow=True
        )

    # =========================================================================
    # Camera Controls
    # =========================================================================

    def reset_camera(self) -> None:
        """Reset camera to isometric view"""
        if self._plotter is None:
            return

        distance = self._mesh_size * 2.5
        self._plotter.camera_position = [
            (self._mesh_center[0] + distance,
             self._mesh_center[1] + distance,
             self._mesh_center[2] + distance),
            tuple(self._mesh_center),
            (0, 0, 1)
        ]

    def view_from(self, direction: str) -> None:
        """
        Set camera to a preset view direction.

        Args:
            direction: One of 'front', 'back', 'left', 'right', 'top', 'bottom'
        """
        if self._plotter is None:
            return

        distance = self._mesh_size * 2.5
        c = self._mesh_center

        positions = {
            'front': ((c[0], c[1] - distance, c[2]), (0, 0, 1)),
            'back': ((c[0], c[1] + distance, c[2]), (0, 0, 1)),
            'left': ((c[0] - distance, c[1], c[2]), (0, 0, 1)),
            'right': ((c[0] + distance, c[1], c[2]), (0, 0, 1)),
            'top': ((c[0], c[1], c[2] + distance), (0, 1, 0)),
            'bottom': ((c[0], c[1], c[2] - distance), (0, 1, 0)),
        }

        if direction in positions:
            pos, up = positions[direction]
            self._plotter.camera_position = [pos, tuple(c), up]
            self._plotter.render()

    # =========================================================================
    # Display Toggles
    # =========================================================================

    def toggle_wireframe(self) -> bool:
        """
        Toggle wireframe display mode.

        Returns:
            Current wireframe state after toggle
        """
        if self._plotter is None or self._actor is None:
            return self._wireframe_enabled

        self._wireframe_enabled = not self._wireframe_enabled

        if self._wireframe_enabled:
            self._actor.GetProperty().SetRepresentationToWireframe()
        else:
            self._actor.GetProperty().SetRepresentationToSurface()

        self._plotter.render()
        return self._wireframe_enabled

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

        return {
            'loaded': True,
            'n_points': self._mesh.n_points,
            'n_cells': self._mesh.n_cells,
            'bounds': self._mesh.bounds,
            'center': tuple(self._mesh_center),
            'size': self._mesh_size
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
        self._mesh_center = np.array([0.0, 0.0, 0.0])
        self._mesh_size = 1.0
        self._wireframe_enabled = False
        self._is_volumetric = False
