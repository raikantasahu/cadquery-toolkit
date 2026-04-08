"""
CAD Model Viewer using PyVista

A Python implementation of the CAD model viewer that mirrors the JavaScript/ThreeJS version.
Supports loading CADModelData JSON files and provides interactive 3D visualization.
"""

import json
import numpy as np
import pyvista as pv
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

# Import the CADModelData class
from model.CADModelData import CADModelData, Face


class CADViewer:
    """
    PyVista-based CAD Model Viewer.

    Provides interactive 3D visualization of CAD models with features matching
    the JavaScript/ThreeJS implementation:
    - Model loading from JSON files
    - Dual camera modes (perspective/parallel)
    - Preset views (top, bottom, left, right, front, back)
    - Wireframe toggle
    - Grid and axes display
    - Interactive orbit controls
    """

    # Default material color (matches JS: 0x667eea)
    DEFAULT_COLOR = '#667eea'
    BACKGROUND_COLOR = '#1a1a1a'

    def __init__(self):
        """Initialize the CAD viewer."""
        self.plotter: Optional[pv.Plotter] = None
        self.mesh: Optional[pv.PolyData] = None
        self.model_data: Optional[CADModelData] = None
        self.actor: Optional[pv.Actor] = None

        # State
        self.is_perspective = True
        self.wireframe_enabled = False
        self.axes_visible = False
        self.grid_visible = True

        # Store original mesh bounds for view calculations
        self._mesh_center = np.array([0.0, 0.0, 0.0])
        self._mesh_size = 1.0

    def _create_mesh_from_model(self, model_data: CADModelData) -> pv.PolyData:
        """
        Create a PyVista mesh from CADModelData.

        Args:
            model_data: The CAD model data containing face tessellation

        Returns:
            PyVista PolyData mesh
        """
        all_vertices = []
        all_faces = []
        vertex_offset = 0

        for face in model_data.FaceList:
            if not face.VertexLocations or not face.Connectivity:
                continue

            # Extract vertices for this face
            vertex_locations = face.VertexLocations
            num_vertices = len(vertex_locations) // 3

            # Add vertices
            for i in range(num_vertices):
                all_vertices.append([
                    vertex_locations[i * 3],
                    vertex_locations[i * 3 + 1],
                    vertex_locations[i * 3 + 2]
                ])

            # Add triangles with offset
            connectivity = face.Connectivity
            num_triangles = len(connectivity) // 3

            for i in range(num_triangles):
                # PyVista faces format: [n, v0, v1, v2, ...] where n is vertex count
                all_faces.extend([
                    3,  # Triangle has 3 vertices
                    vertex_offset + connectivity[i * 3],
                    vertex_offset + connectivity[i * 3 + 1],
                    vertex_offset + connectivity[i * 3 + 2]
                ])

            vertex_offset += num_vertices

        if not all_vertices:
            # Return an empty mesh if no valid faces
            return pv.PolyData()

        vertices = np.array(all_vertices, dtype=np.float64)
        faces = np.array(all_faces, dtype=np.int64)

        mesh = pv.PolyData(vertices, faces)
        mesh.compute_normals(inplace=True)

        return mesh

    def _create_mesh_from_dict(self, data: Dict[str, Any]) -> pv.PolyData:
        """
        Create a PyVista mesh directly from a dictionary (JSON format).

        Args:
            data: Dictionary containing faceList with vertexLocations and connectivity

        Returns:
            PyVista PolyData mesh
        """
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

            # Add vertices
            for i in range(num_vertices):
                all_vertices.append([
                    vertex_locations[i * 3],
                    vertex_locations[i * 3 + 1],
                    vertex_locations[i * 3 + 2]
                ])

            # Add triangles
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
            return pv.PolyData()

        vertices = np.array(all_vertices, dtype=np.float64)
        faces = np.array(all_faces, dtype=np.int64)

        mesh = pv.PolyData(vertices, faces)
        mesh.compute_normals(inplace=True)

        return mesh

    def load_json(self, filepath: str) -> None:
        """
        Load a CAD model from a JSON file.

        Args:
            filepath: Path to the JSON file
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        # Try to load as CADModelData first
        try:
            self.model_data = CADModelData.from_dict(data)
            self.mesh = self._create_mesh_from_model(self.model_data)
        except Exception:
            # Fall back to direct dictionary parsing
            self.model_data = None
            self.mesh = self._create_mesh_from_dict(data)

        if self.mesh.n_points == 0:
            raise ValueError("No valid geometry found in the file")

        # Calculate mesh properties for view operations
        bounds = self.mesh.bounds
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

    def load_model(self, model_data: CADModelData) -> None:
        """
        Load a CAD model from a CADModelData object.

        Args:
            model_data: The CADModelData object
        """
        self.model_data = model_data
        self.mesh = self._create_mesh_from_model(model_data)

        if self.mesh.n_points == 0:
            raise ValueError("No valid geometry in the model data")

        bounds = self.mesh.bounds
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

    def create_sample_cube(self) -> None:
        """Create a sample cube model for testing."""
        # Create a simple cube using CADModelData format
        # Cube vertices: 8 corners of a unit cube centered at origin
        size = 1.0
        half = size / 2

        # Define the 6 faces of a cube with triangulation
        faces = []

        # Face definitions: each face has 4 vertices and 2 triangles
        face_defs = [
            # Front face (z = half)
            ([[-half, -half, half], [half, -half, half], [half, half, half], [-half, half, half]], [0, 1, 2, 0, 2, 3]),
            # Back face (z = -half)
            ([[-half, -half, -half], [-half, half, -half], [half, half, -half], [half, -half, -half]], [0, 1, 2, 0, 2, 3]),
            # Top face (y = half)
            ([[-half, half, -half], [-half, half, half], [half, half, half], [half, half, -half]], [0, 1, 2, 0, 2, 3]),
            # Bottom face (y = -half)
            ([[-half, -half, -half], [half, -half, -half], [half, -half, half], [-half, -half, half]], [0, 1, 2, 0, 2, 3]),
            # Right face (x = half)
            ([[half, -half, -half], [half, half, -half], [half, half, half], [half, -half, half]], [0, 1, 2, 0, 2, 3]),
            # Left face (x = -half)
            ([[-half, -half, -half], [-half, -half, half], [-half, half, half], [-half, half, -half]], [0, 1, 2, 0, 2, 3]),
        ]

        for i, (verts, conn) in enumerate(face_defs):
            vertex_locations = []
            for v in verts:
                vertex_locations.extend(v)

            face = Face(
                PersistentID=f"face_{i}",
                VertexLocations=vertex_locations,
                Connectivity=conn
            )
            faces.append(face)

        self.model_data = CADModelData(
            CadName="Sample",
            ModelName="Cube",
            ComponentName="Sample Cube",
            FaceList=faces
        )

        self.mesh = self._create_mesh_from_model(self.model_data)

        bounds = self.mesh.bounds
        self._mesh_center = np.array([0.0, 0.0, 0.0])
        self._mesh_size = size

    def _setup_plotter(self) -> None:
        """Set up the PyVista plotter with initial configuration."""
        self.plotter = pv.Plotter()
        self.plotter.set_background(self.BACKGROUND_COLOR)

        # Add the mesh
        if self.mesh is not None:
            self.actor = self.plotter.add_mesh(
                self.mesh,
                color=self.DEFAULT_COLOR,
                show_edges=False,
                lighting=True,
                smooth_shading=True,
                specular=0.5,
                specular_power=30
            )

        # Add grid (floor plane)
        if self.grid_visible:
            self._add_grid()

        # Set up lighting (similar to JS version)
        self.plotter.enable_3_lights()

        # Set initial camera
        self._reset_camera()

        # Add key bindings
        self._setup_key_bindings()

    def _add_grid(self) -> None:
        """Add a floor grid to the scene."""
        if self.mesh is None:
            return

        # Create grid plane below the model
        grid_size = max(200, self._mesh_size * 4)
        bounds = self.mesh.bounds
        z_min = bounds[4]  # Minimum Z coordinate

        # Create a plane for the grid
        grid = pv.Plane(
            center=(self._mesh_center[0], self._mesh_center[1], z_min - self._mesh_size * 0.1),
            direction=(0, 0, 1),
            i_size=grid_size,
            j_size=grid_size,
            i_resolution=20,
            j_resolution=20
        )

        self.plotter.add_mesh(
            grid,
            color='#333333',
            style='wireframe',
            line_width=1,
            opacity=0.5
        )

    def _reset_camera(self) -> None:
        """Reset camera to default isometric view."""
        if self.plotter is None or self.mesh is None:
            return

        distance = self._mesh_size * 2.5
        self.plotter.camera_position = [
            (self._mesh_center[0] + distance,
             self._mesh_center[1] + distance,
             self._mesh_center[2] + distance),
            tuple(self._mesh_center),
            (0, 0, 1)  # Z-up
        ]

    def _setup_key_bindings(self) -> None:
        """Set up keyboard shortcuts for viewer controls."""
        if self.plotter is None:
            return

        # Key bindings for views and toggles
        self.plotter.add_key_event('1', lambda: self.view_from_front())
        self.plotter.add_key_event('2', lambda: self.view_from_back())
        self.plotter.add_key_event('3', lambda: self.view_from_left())
        self.plotter.add_key_event('4', lambda: self.view_from_right())
        self.plotter.add_key_event('5', lambda: self.view_from_top())
        self.plotter.add_key_event('6', lambda: self.view_from_bottom())
        self.plotter.add_key_event('r', lambda: self._reset_camera())
        self.plotter.add_key_event('w', lambda: self.toggle_wireframe())
        self.plotter.add_key_event('a', lambda: self.toggle_axes())
        self.plotter.add_key_event('p', lambda: self.toggle_camera_type())

    # =========================================================================
    # Preset Views
    # =========================================================================

    def view_from_top(self) -> None:
        """Set camera to top-down view (looking down Z axis)."""
        if self.plotter is None:
            return
        distance = self._mesh_size * 2.5
        self.plotter.camera_position = [
            (self._mesh_center[0], self._mesh_center[1], self._mesh_center[2] + distance),
            tuple(self._mesh_center),
            (0, 1, 0)
        ]
        self.plotter.render()

    def view_from_bottom(self) -> None:
        """Set camera to bottom-up view (looking up Z axis)."""
        if self.plotter is None:
            return
        distance = self._mesh_size * 2.5
        self.plotter.camera_position = [
            (self._mesh_center[0], self._mesh_center[1], self._mesh_center[2] - distance),
            tuple(self._mesh_center),
            (0, 1, 0)
        ]
        self.plotter.render()

    def view_from_front(self) -> None:
        """Set camera to front view (looking down Y axis)."""
        if self.plotter is None:
            return
        distance = self._mesh_size * 2.5
        self.plotter.camera_position = [
            (self._mesh_center[0], self._mesh_center[1] - distance, self._mesh_center[2]),
            tuple(self._mesh_center),
            (0, 0, 1)
        ]
        self.plotter.render()

    def view_from_back(self) -> None:
        """Set camera to back view (looking up Y axis)."""
        if self.plotter is None:
            return
        distance = self._mesh_size * 2.5
        self.plotter.camera_position = [
            (self._mesh_center[0], self._mesh_center[1] + distance, self._mesh_center[2]),
            tuple(self._mesh_center),
            (0, 0, 1)
        ]
        self.plotter.render()

    def view_from_left(self) -> None:
        """Set camera to left view (looking down X axis)."""
        if self.plotter is None:
            return
        distance = self._mesh_size * 2.5
        self.plotter.camera_position = [
            (self._mesh_center[0] - distance, self._mesh_center[1], self._mesh_center[2]),
            tuple(self._mesh_center),
            (0, 0, 1)
        ]
        self.plotter.render()

    def view_from_right(self) -> None:
        """Set camera to right view (looking up X axis)."""
        if self.plotter is None:
            return
        distance = self._mesh_size * 2.5
        self.plotter.camera_position = [
            (self._mesh_center[0] + distance, self._mesh_center[1], self._mesh_center[2]),
            tuple(self._mesh_center),
            (0, 0, 1)
        ]
        self.plotter.render()

    # =========================================================================
    # Display Toggles
    # =========================================================================

    def toggle_wireframe(self) -> bool:
        """Toggle wireframe display mode."""
        if self.plotter is None or self.actor is None:
            return self.wireframe_enabled

        self.wireframe_enabled = not self.wireframe_enabled

        # Remove current mesh and re-add with new style
        self.plotter.remove_actor(self.actor)

        if self.wireframe_enabled:
            self.actor = self.plotter.add_mesh(
                self.mesh,
                color=self.DEFAULT_COLOR,
                style='wireframe',
                line_width=1
            )
        else:
            self.actor = self.plotter.add_mesh(
                self.mesh,
                color=self.DEFAULT_COLOR,
                show_edges=False,
                lighting=True,
                smooth_shading=True,
                specular=0.5,
                specular_power=30
            )

        self.plotter.render()
        return self.wireframe_enabled

    def toggle_axes(self) -> bool:
        """Toggle axes display."""
        if self.plotter is None:
            return self.axes_visible

        self.axes_visible = not self.axes_visible

        if self.axes_visible:
            self.plotter.show_axes()
        else:
            self.plotter.hide_axes()

        self.plotter.render()
        return self.axes_visible

    def toggle_camera_type(self) -> bool:
        """Toggle between perspective and parallel (orthographic) projection."""
        if self.plotter is None:
            return self.is_perspective

        self.is_perspective = not self.is_perspective
        self.plotter.camera.SetParallelProjection(not self.is_perspective)

        if not self.is_perspective:
            # Adjust parallel scale for orthographic view
            self.plotter.camera.SetParallelScale(self._mesh_size * 1.5)

        self.plotter.render()
        return self.is_perspective

    # =========================================================================
    # Main Methods
    # =========================================================================

    def show(self, interactive: bool = True) -> None:
        """
        Display the viewer window.

        Args:
            interactive: If True, show interactive window. If False, return immediately.
        """
        if self.mesh is None:
            raise ValueError("No model loaded. Call load_json() or load_model() first.")

        self._setup_plotter()

        # Print keyboard shortcuts
        print("\n=== CAD Viewer Controls ===")
        print("Mouse: Orbit (left), Pan (middle/shift+left), Zoom (right/scroll)")
        print("Keys:")
        print("  1-6: Preset views (Front/Back/Left/Right/Top/Bottom)")
        print("  r: Reset camera")
        print("  w: Toggle wireframe")
        print("  a: Toggle axes")
        print("  p: Toggle perspective/parallel projection")
        print("  q: Quit")
        print("===========================\n")

        if interactive:
            self.plotter.show()
        else:
            self.plotter.show(interactive=False, auto_close=False)

    def show_offscreen(self, screenshot_path: str = 'output.png') -> None:
        """
        Render the model off-screen and save a screenshot.

        Args:
            screenshot_path: Path to save the screenshot
        """
        if self.mesh is None:
            raise ValueError("No model loaded. Call load_json() or load_model() first.")

        # Create off-screen plotter
        self.plotter = pv.Plotter(off_screen=True, window_size=[1920, 1080])
        self.plotter.set_background(self.BACKGROUND_COLOR)

        # Add the mesh
        self.actor = self.plotter.add_mesh(
            self.mesh,
            color=self.DEFAULT_COLOR,
            show_edges=False,
            lighting=True,
            smooth_shading=True,
            specular=0.5,
            specular_power=30
        )

        # Add grid
        if self.grid_visible:
            self._add_grid()

        # Set up lighting
        self.plotter.enable_3_lights()

        # Set camera to isometric view
        self._reset_camera()

        # Show axes
        self.plotter.show_axes()

        # Save screenshot
        self.plotter.screenshot(screenshot_path)
        print(f"\nScreenshot saved to: {screenshot_path}")
        self.plotter.close()

    def screenshot(self, filename: str) -> None:
        """
        Save a screenshot of the current view.

        Args:
            filename: Output filename (e.g., 'model.png')
        """
        if self.plotter is None:
            raise ValueError("Viewer not initialized. Call show() first.")
        self.plotter.screenshot(filename)

    def close(self) -> None:
        """Close the viewer window."""
        if self.plotter is not None:
            self.plotter.close()
            self.plotter = None

    def get_model_info(self) -> Dict[str, Any]:
        """
        Get information about the loaded model.

        Returns:
            Dictionary with model information
        """
        info = {
            'has_mesh': self.mesh is not None,
            'n_points': 0,
            'n_faces': 0,
            'bounds': None,
            'center': None,
        }

        if self.mesh is not None:
            info['n_points'] = self.mesh.n_points
            info['n_faces'] = self.mesh.n_cells
            info['bounds'] = self.mesh.bounds
            info['center'] = tuple(self._mesh_center)

        if self.model_data is not None:
            info['model_name'] = self.model_data.ModelName
            info['component_name'] = self.model_data.ComponentName
            info['cad_name'] = self.model_data.CadName
            info['length_unit'] = self.model_data.LengthUnit
            info['total_faces'] = self.model_data.total_face_count
            info['total_triangles'] = self.model_data.total_triangle_count

        return info


def main():
    """Main entry point for the CAD viewer."""
    import argparse

    parser = argparse.ArgumentParser(description='CAD Model Viewer using PyVista')
    parser.add_argument('file', nargs='?', help='JSON file containing CAD model data')
    parser.add_argument('--sample', action='store_true', help='Load sample cube model')
    parser.add_argument('--screenshot', '-s', type=str, help='Save screenshot to file (for headless environments)')
    parser.add_argument('--offscreen', action='store_true', help='Run in off-screen mode')

    args = parser.parse_args()

    viewer = CADViewer()

    if args.sample or args.file is None:
        print("Loading sample cube model...")
        viewer.create_sample_cube()
    else:
        print(f"Loading model from: {args.file}")
        viewer.load_json(args.file)

    # Print model info
    info = viewer.get_model_info()
    print(f"\nModel Information:")
    print(f"  Points: {info['n_points']}")
    print(f"  Faces: {info['n_faces']}")
    if info.get('model_name'):
        print(f"  Name: {info.get('component_name') or info.get('model_name')}")
    if info.get('length_unit'):
        print(f"  Units: {info['length_unit']}")

    # Handle off-screen or screenshot mode
    if args.screenshot or args.offscreen:
        viewer.show_offscreen(args.screenshot or 'output.png')
    else:
        viewer.show()


if __name__ == '__main__':
    main()
