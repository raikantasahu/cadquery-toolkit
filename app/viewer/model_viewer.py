"""model_viewer.py - GTK ModelViewer controller.

The GObject wrapper around the pyvista viewers: loads a mesh, opens the right
viewer window (delegating to ``viewer.viewers``), and exposes picks via
signals/properties for the GTK app. The rendering/picking internals live in
the GTK-free sibling modules (style/picking/scene/viewers).

Usage:
    viewer = ModelViewer()
    viewer.connect('viewer-closed', on_viewer_closed)
    viewer.set_mesh_from_dict(model_data)
    viewer.show_viewer()
"""
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, GLib

import pyvista as pv
from typing import Any, Dict, List, Optional

from model.tessellation import (
    create_polydata_from_model_data,
    create_polydatas_per_part,
)
from .viewers import (
    show_model_viewer,
    show_pick_viewer,
    show_pyvista,
    show_volumetric_viewer,
)


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
                # Always build the per-part split so the plain view can offer
                # per-part hide/show on assemblies (show_model_viewer) and the
                # pick view can route to show_pick_viewer. face_index is only
                # needed for picking, so it tracks with_face_index.
                self._parts = create_polydatas_per_part(
                    data, with_face_index=with_face_index)
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
            pick_mode: ``"faces"`` (default), ``"vertices"``, or ``"edges"`` —
                which entity type to pick. Only meaningful when ``pick_faces``
                is True. After close, read the matching ``picked_*`` property.
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
            elif self._is_volumetric:
                show_volumetric_viewer(self._mesh, title=title)
            elif self._parts is not None and len(self._parts) > 1:
                # Assembly geometry view: one actor per part + hide/show column.
                show_model_viewer(self._parts, title=title)
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

    @property
    def picked_edges(self) -> List[tuple]:
        """Return the most recent picks after a ``pick_mode="edges"`` run.

        Alias of the same underlying ``_last_picks`` (a viewer instance only
        ever runs one pick mode), named for clarity at the call site.
        """
        return list(self._last_picks)

    def clear(self) -> None:
        """Clear the loaded mesh"""
        self._mesh = None
        self._parts = None
        self._is_volumetric = False
