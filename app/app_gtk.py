"""
app_gtk.py - CadQuery Model Studio (GTK shell)

Thin GTK wrapper over the GTK-free app_core.AppCore: window, widgets, 3D picking,
dialogs, and menu handlers that translate UI <-> core. Domain logic lives in the
core (see docs/plans/Core-UI-Separation.md).

Usage:
    python app_gtk.py
"""
# Lazy annotations (PEP 563): method signatures reference names from the guarded
# import block below (e.g. ModelBuilder); without this they'd be evaluated at
# class-definition time and a missing dependency would crash the module before
# main() can show the friendly dialog (T1.3).
from __future__ import annotations

import logging
import os
os.environ['NO_AT_BRIDGE'] = '1'

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Pango

from pathlib import Path
from typing import Optional

# Dependency-sensitive imports are guarded as one block (Architecture-Review
# T1.3): this GTK shell is the only module that imports gi, and a missing
# dependency (cadquery/freecad/vtk/gmsh) on this chain would otherwise crash at
# module load with a raw traceback before main() can show a friendly dialog.
try:
    import cadquery as cq

    from converter import HAS_FREECAD
    from mesher import HAS_GMSH
    from dialogs import (
        ask_save_mesh_file, ask_export_file, ask_mesh_settings,
        edit_face_selection, pick_entities,
    )
    from widgets import ModelBuilder, StepImportPanel
    from viewer import ModelViewer, show_mesh
    from models.parts import get_all_parts
    from models.assemblies import get_all_assemblies
    from app_core import AppCore

    _IMPORT_ERROR = None
except ImportError as _exc:
    _IMPORT_ERROR = _exc


class CadQueryApp(Gtk.Window):
    """Main application window"""

    def __init__(self):
        super().__init__(title="CadQuery Model Studio")
        self.set_default_size(700, 600)
        self.set_border_width(10)

        # Application icon
        icon_path = Path(__file__).parent / "images" / "parametric_gear.png"
        if icon_path.exists():
            self.set_icon_from_file(str(icon_path))

        # Model + mesh state live in the GTK-free core; the window keeps only
        # UI/selection state (the picks below) and delegates domain logic.
        self._core = AppCore()
        # Face / vertex picks: lists of (persistent_id, owner_label) tuples.
        # Populated by the model viewer's pick modes; both consumed by the
        # MeshData save flow as entity_owners. Cleared on model change.
        # Kept separate so each picker pre-populates and edits only its own
        # entity type (F* and V* keys never collide in entity_owners).
        self._picked_faces: list = []
        self._picked_vertices: list = []
        # Edge picks: (E#, label) tuples. Stored here (Edge-Identity-and-Picking
        # F1); wiring them into entity_owners is the edge-container feature (F2).
        self._picked_edges: list = []
        # Single cap face (persistent_id, label) for extruded hex, or None.
        self._cap_face: tuple = None
        # Refinement regions: list of dicts
        # {scope, vertex_pid, vertex_label, fine_size, radius}. Each anchors on
        # a picked vertex; resolved to (coordinate, part index) at mesh time.
        self._refinements: list = []
        # Last-used Mesh Settings, persisted across dialog invocations for the
        # same model; reset to None (dialog defaults) when the model changes.
        self._mesh_settings: dict = None
        # Last directory a model/mesh was saved to (session) — save/export
        # dialogs reopen there, like the STEP import chooser.
        self._last_save_dir: str = None
        self.connect("destroy", self._on_destroy)

        # cadquery-missing is handled before the window is built (main() shows a
        # dialog if the guarded imports failed). FreeCAD can be absent while
        # cadquery imports, so check it here.
        if not HAS_FREECAD:
            self._show_dependency_error("FreeCAD not installed.\nRun: conda install -c conda-forge freecad")
            return

        self._setup_css()
        self._create_widgets()

    def _show_dependency_error(self, message: str) -> None:
        """Show dependency error and exit"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Missing Dependencies"
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()
        Gtk.main_quit()

    def _setup_css(self) -> None:
        """Set up CSS styling"""
        css_provider = Gtk.CssProvider()
        css = b"""
        .suggested-action {
            background: #667eea;
        }
        """
        css_provider.load_from_data(css)

        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _create_menu_bar(self) -> Gtk.MenuBar:
        """Load the menu bar from ui/window.ui via Gtk.Builder"""
        ui_path = Path(__file__).parent / "ui" / "window.ui"
        builder = Gtk.Builder()
        builder.add_from_file(str(ui_path))
        builder.connect_signals(self)

        # Keep references to menu items for sensitivity control
        self.menu_view = builder.get_object("menu_view")
        self.menu_export = builder.get_object("menu_export")
        self.menu_pick_faces = builder.get_object("menu_pick_faces")
        self.menu_edit_face_selection = builder.get_object(
            "menu_edit_face_selection"
        )
        self.menu_pick_vertices = builder.get_object("menu_pick_vertices")
        self.menu_edit_vertex_selection = builder.get_object(
            "menu_edit_vertex_selection"
        )
        self.menu_pick_edges = builder.get_object("menu_pick_edges")
        self.menu_edit_edge_selection = builder.get_object(
            "menu_edit_edge_selection"
        )
        self.menu_create_mesh = builder.get_object("menu_create_mesh")
        self.menu_view_mesh = builder.get_object("menu_view_mesh")
        self.menu_save_mesh = builder.get_object("menu_save_mesh")
        self.menu_show_stats = builder.get_object("menu_show_stats")

        return builder.get_object("menubar")

    def _create_widgets(self) -> None:
        """Create the main UI"""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Menu bar (loaded from ui/window.ui)
        menubar = self._create_menu_bar()
        vbox.pack_start(menubar, False, False, 0)

        # Header
        title_label = Gtk.Label()
        title_label.set_markup('<span size="x-large" weight="bold">CadQuery Model Studio</span>')
        title_label.set_margin_bottom(5)
        vbox.pack_start(title_label, False, False, 0)

        # Two top-level tabs: Parts and Assemblies. Each tab wraps a
        # ModelBuilder bound to its own registry (parts vs. parametric
        # assemblies). The "active" builder — used by all menu callbacks —
        # is whichever notebook page is currently visible.
        self.notebook = Gtk.Notebook()

        self.parts_builder = ModelBuilder(
            model_functions=get_all_parts(), kind_label="Part",
        )
        self._add_tab_padding(self.parts_builder)
        self._wire_builder(self.parts_builder)
        self.notebook.append_page(
            self.parts_builder, Gtk.Label(label="Parts"),
        )

        self.assemblies_builder = ModelBuilder(
            model_functions=get_all_assemblies(), kind_label="Assembly",
        )
        self._add_tab_padding(self.assemblies_builder)
        self._wire_builder(self.assemblies_builder)
        self.notebook.append_page(
            self.assemblies_builder, Gtk.Label(label="Assemblies"),
        )

        # Third source: an imported external STEP, used exactly like a built
        # model. Its signal set differs from a builder (no params/type change;
        # a single model-changed on import), so it is wired here.
        self.step_panel = StepImportPanel()
        self._add_tab_padding(self.step_panel)
        self.step_panel.connect('view-requested', self._on_view_requested)
        self.step_panel.connect('status-changed', self._on_status_changed)
        self.step_panel.connect(
            'model-changed', lambda _panel: self._invalidate_selections())
        self.notebook.append_page(
            self.step_panel, Gtk.Label(label="Imported STEP"),
        )

        vbox.pack_start(self.notebook, True, True, 0)

        # Status bar
        vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 5)

        self.status_label = Gtk.Label(label="Select a model type to begin")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_selectable(True)
        attr_list = Pango.AttrList()
        attr_list.insert(Pango.attr_scale_new(0.9))
        self.status_label.set_attributes(attr_list)
        vbox.pack_start(self.status_label, False, False, 0)

        # Connect the tab-switch handler only AFTER the pages and status_label
        # exist. append_page() emits 'switch-page' during construction, and the
        # handler restores the new tab's status via self.status_label + re-syncs
        # menus; connecting before line creating status_label ran it too early
        # (AttributeError on self.status_label, swallowed by GTK and printed to
        # stderr). Do the initial menu-sensitivity sync explicitly here instead
        # of relying on those construction-time emissions.
        self.notebook.connect('switch-page', self._on_tab_switched)
        self._sync_menu_sensitivity()

    # --- Active-builder helpers ---

    @property
    def active_source(self) -> Optional[ModelBuilder]:
        """Return the active tab if it is a *model source*, else ``None``.

        A model source is any tab the window can drive uniformly to produce a
        model — today ``ModelBuilder`` (Parts/Assemblies); ``StepImportPanel``
        joins it later. It is a duck-typed contract (a shared method/signal
        surface, not a base class — GObject metaclass; see
        docs/plans/STEP-Import-GUI.md), so membership is tested by ``isinstance``
        against the known source classes. Callers either short-circuit on
        ``None`` or are gated by menu sensitivity (``False`` when no source has a
        model).
        """
        page_num = self.notebook.get_current_page()
        if page_num < 0:
            return None
        page = self.notebook.get_nth_page(page_num)
        return page if isinstance(page, (ModelBuilder, StepImportPanel)) else None

    def _wire_builder(self, builder: ModelBuilder) -> None:
        """Connect a ModelBuilder's signals to the app's handlers."""
        builder.connect('view-requested', self._on_view_requested)
        builder.connect('status-changed', self._on_status_changed)
        builder.connect('params-changed', self._on_params_changed)
        builder.connect('model-type-changed', self._on_model_type_changed)

    def _add_tab_padding(self, widget: Gtk.Widget, margin: int = 10) -> None:
        """Give a notebook page widget breathing room from the tab borders."""
        widget.set_margin_start(margin)
        widget.set_margin_end(margin)
        widget.set_margin_top(margin)
        widget.set_margin_bottom(margin)

    def _on_tab_switched(self, notebook, page, page_num) -> None:
        """Tab switch invalidates any held mesh, re-syncs menu sensitivity,
        and restores the new tab's last builder status.

        Reads the new source from `page_num` rather than via the
        `active_source` property because GTK has not yet committed
        `get_current_page()` at the time this signal fires.
        """
        source = notebook.get_nth_page(page_num)
        self._invalidate_selections(source=source)
        status = source.last_status_message
        if not status:
            status = f"{notebook.get_tab_label_text(source)} — no model selected"
        self.status_label.set_text(status)

    def _on_view_requested(self, builder, model) -> None:
        """Handle view request from ModelBuilder"""
        self.status_label.set_text("Opening viewer...")
        while Gtk.events_pending():
            Gtk.main_iteration()

        # Create viewer widget
        viewer = ModelViewer()
        viewer.connect('viewer-closed', lambda v: self._on_viewer_closed())
        viewer.connect('error', lambda v, msg: self._on_viewer_error(msg))

        # Convert the active model to CADModelData via the core and feed it to
        # the viewer (the core dispatches part vs assembly).
        model_data = self._current_model_data()
        if model_data is None:
            self.status_label.set_text("Error: Conversion failed")
            return

        if not viewer.set_mesh_from_dict(model_data):
            self.status_label.set_text("Error: Failed to load mesh")
            return

        # Disable both builders + the notebook while viewer is open.
        self.parts_builder.set_sensitive_controls(False)
        self.assemblies_builder.set_sensitive_controls(False)
        self.notebook.set_sensitive(False)
        self._sync_menu_sensitivity(enabled=False)
        self.status_label.set_text("Viewer open - close viewer window to continue")

        # Show viewer (blocking)
        viewer.show_viewer()

    def _on_viewer_error(self, message: str) -> None:
        """Handle viewer error"""
        self.parts_builder.set_sensitive_controls(True)
        self.assemblies_builder.set_sensitive_controls(True)
        self.notebook.set_sensitive(True)
        self._sync_menu_sensitivity()
        self._show_error("Viewer Error", message)
        self.status_label.set_text("Error: Viewer failed")

    def _on_viewer_closed(self) -> None:
        """Called when viewer window is closed"""
        self.parts_builder.set_sensitive_controls(True)
        self.assemblies_builder.set_sensitive_controls(True)
        self.notebook.set_sensitive(True)
        self._sync_menu_sensitivity()
        self.present()
        self.status_label.set_text("Viewer closed. Ready to continue.")

    # --- Menu callbacks ---

    def _on_menu_view(self, menuitem) -> None:
        """Handle Model > View menu activation"""
        builder = self.active_source
        if builder is None:
            return
        builder.request_view()

    def _on_menu_pick_faces(self, menuitem) -> None:
        """Handle Model > Pick Faces menu activation."""
        self._open_pick_viewer(
            pick_mode="faces",
            title="Pick Faces",
            status_text=(
                "Face picker open — left-click a face to pick/unpick. "
                "Close window when done."
            ),
            initial_picks=self._picked_faces,
            on_closed=self._on_pick_faces_viewer_closed,
        )

    def _on_menu_pick_vertices(self, menuitem) -> None:
        """Handle Model > Pick Vertices menu activation."""
        self._open_pick_viewer(
            pick_mode="vertices",
            title="Pick Vertices",
            status_text=(
                "Vertex picker open — left-click a vertex to pick/unpick. "
                "Close window when done."
            ),
            initial_picks=self._picked_vertices,
            on_closed=self._on_pick_vertices_viewer_closed,
        )

    def _on_menu_pick_edges(self, menuitem) -> None:
        """Handle Model > Pick Edges menu activation."""
        self._open_pick_viewer(
            pick_mode="edges",
            title="Pick Edges",
            status_text=(
                "Edge picker open — left-click an edge to pick/unpick. "
                "Close window when done."
            ),
            initial_picks=self._picked_edges,
            on_closed=self._on_pick_edges_viewer_closed,
        )

    def _open_pick_viewer(self, pick_mode, title, status_text,
                          initial_picks, on_closed) -> None:
        """Build the current model and open the viewer in a pick mode.

        Shared by the face and vertex pickers — they differ only in mode,
        window title, status text, the pre-populated selection, and the
        close handler that commits the result.
        """
        model_data = self._current_model_data()
        if model_data is None:
            return

        viewer = ModelViewer()
        viewer.connect('viewer-closed', lambda v: on_closed(v))
        viewer.connect('error', lambda v, msg: self._on_viewer_error(msg))

        if not viewer.set_mesh_from_dict(model_data, with_face_index=True):
            self.status_label.set_text("Error: Failed to load model")
            return

        self.parts_builder.set_sensitive_controls(False)
        self.assemblies_builder.set_sensitive_controls(False)
        self.notebook.set_sensitive(False)
        self._sync_menu_sensitivity(enabled=False)
        self.status_label.set_text(status_text)

        viewer.show_viewer(
            title=title,
            pick_faces=True,
            initial_picks=initial_picks,
            pick_mode=pick_mode,
        )

    def _on_pick_faces_viewer_closed(self, viewer) -> None:
        """Commit face picks when the face picker closes."""
        self._picked_faces = list(viewer.picked_faces)
        self._finish_pick_viewer("face", "faces", len(self._picked_faces))

    def _on_pick_vertices_viewer_closed(self, viewer) -> None:
        """Commit vertex picks when the vertex picker closes."""
        self._picked_vertices = list(viewer.picked_vertices)
        self._finish_pick_viewer(
            "vertex", "vertices", len(self._picked_vertices),
        )

    def _on_pick_edges_viewer_closed(self, viewer) -> None:
        """Commit edge picks when the edge picker closes."""
        self._picked_edges = list(viewer.picked_edges)
        self._finish_pick_viewer("edge", "edges", len(self._picked_edges))

    def _finish_pick_viewer(self, singular: str, plural: str, n: int) -> None:
        """Restore UI sensitivity and report the count after a picker closes."""
        self.parts_builder.set_sensitive_controls(True)
        self.assemblies_builder.set_sensitive_controls(True)
        self.notebook.set_sensitive(True)
        self._sync_menu_sensitivity()
        self.present()
        if n:
            noun = singular if n == 1 else plural
            self.status_label.set_text(
                f"{singular.capitalize()} picker closed. {n} {noun} selected."
            )
        else:
            self.status_label.set_text(
                f"{singular.capitalize()} picker closed. No {plural} selected."
            )

    def _on_menu_edit_face_selection(self, menuitem) -> None:
        """Handle Model > Edit Face Selection menu activation."""
        if not self._picked_faces:
            return
        edited = edit_face_selection(self, self._picked_faces)
        if edited is None:
            return
        self._picked_faces = edited
        self._sync_menu_sensitivity()
        n = len(self._picked_faces)
        self.status_label.set_text(
            f"Face selection updated. {n} face{'s' if n != 1 else ''}."
        )

    def _on_menu_edit_vertex_selection(self, menuitem) -> None:
        """Handle Model > Edit Vertex Selection menu activation."""
        if not self._picked_vertices:
            return
        edited = edit_face_selection(
            self, self._picked_vertices, title="Edit Vertex Selection",
        )
        if edited is None:
            return
        self._picked_vertices = edited
        self._sync_menu_sensitivity()
        n = len(self._picked_vertices)
        self.status_label.set_text(
            f"Vertex selection updated. {n} "
            f"{'vertex' if n == 1 else 'vertices'}."
        )

    def _on_menu_edit_edge_selection(self, menuitem) -> None:
        """Handle Model > Edit Edge Selection menu activation."""
        if not self._picked_edges:
            return
        edited = edit_face_selection(
            self, self._picked_edges, title="Edit Edge Selection",
        )
        if edited is None:
            return
        self._picked_edges = edited
        self._sync_menu_sensitivity()
        n = len(self._picked_edges)
        self.status_label.set_text(
            f"Edge selection updated. {n} edge{'s' if n != 1 else ''}."
        )

    def _sync_core_model(self) -> bool:
        """Build the active builder's model and load it into the core.

        The GTK side owns the builder (a widget); it hands the built model +
        params to the GTK-free core. Returns False if there's no model.
        """
        builder = self.active_source
        if builder is None or not builder.build_model():
            return False
        model = builder.get_current_model()
        name = builder.get_selected_model_name() or "model"
        if isinstance(model, cq.Assembly):
            self._core.set_model(model, name)
        else:
            self._core.set_model(
                model, name,
                parameters=builder.get_current_build_params(),
                param_signature=builder.get_current_build_signature(),
            )
        return True

    def _current_model_data(self) -> Optional[dict]:
        """Sync the active model into the core and return its CADModelData dict
        for picking, or None (with an error dialog on conversion failure)."""
        if not self._sync_core_model():
            return None
        try:
            return self._core.model_data()
        except Exception as e:
            self._show_error("Conversion Error", f"Failed to convert model:\n{e}")
            return None

    def _pick_single_cap_face(self):
        """Pick ONE cap face for extruded hex; return (pid, label) or None.

        Thin wrapper over the reusable ``pick_entities`` pattern — the template
        any future face/edge/vertex mesh-control picker should follow.
        """
        model_data = self._current_model_data()
        if model_data is None:
            return None
        return pick_entities(
            self, model_data, kind="face", single=True,
            title="Pick Cap Face",
            initial=[self._cap_face] if self._cap_face else [],
        )

    def _pick_single_vertex(self, current):
        """Pick ONE anchor vertex for local/contact refinement.

        Returns (pid, label) or None. ``current`` is the previously picked
        vertex (pre-populates the picker), or None.
        """
        model_data = self._current_model_data()
        if model_data is None:
            return None
        return pick_entities(
            self, model_data, kind="vertex", single=True,
            title="Pick Refinement Vertex",
            initial=[current] if current else [],
        )

    def _pick_single_edge(self, current):
        """Pick ONE anchor edge for local/contact edge refinement.

        Returns (pid, label) or None. ``current`` pre-populates the picker.
        """
        model_data = self._current_model_data()
        if model_data is None:
            return None
        return pick_entities(
            self, model_data, kind="edge", single=True,
            title="Pick Refinement Edge",
            initial=[current] if current else [],
        )

    def _on_menu_export(self, menuitem) -> None:
        """Handle Model > Export menu activation"""
        builder = self.active_source
        if builder is None:
            return
        if not self._sync_core_model():
            return

        model_name = builder.get_selected_model_name() or "model"
        result = ask_export_file(self, model_name,
                                 initial_dir=self._last_save_dir)
        if result is None:
            self.status_label.set_text("Export cancelled")
            return

        filename, fmt = result
        self._last_save_dir = os.path.dirname(filename)
        try:
            self._core.export_model(filename, fmt)
            self.status_label.set_text(f"Exported to {Path(filename).name}")
            self._show_info("Export Successful", f"Model exported to:\n{filename}")
        except Exception as e:
            self._show_error("Export Error", f"Failed to export:\n{str(e)}")
            self.status_label.set_text("Error: Export failed")

    def _on_menu_create_mesh(self, menuitem) -> None:
        """Handle Mesh > Create Mesh menu activation"""
        if not HAS_GMSH:
            self._show_error(
                "Missing Dependency",
                "Gmsh is not installed.\nRun: pip install gmsh"
            )
            return

        # Settings dialog loop. ``state`` starts from the persisted last-used
        # settings, so they are restored across invocations for the same model
        # (reset to None — dialog defaults — when the model changes). The
        # "Pick…" button closes the dialog with a pick request; we run the
        # picker and reopen with all settings preserved.
        state = self._mesh_settings
        while True:
            cap_pid = self._cap_face[0] if self._cap_face else None
            mesh_config = ask_mesh_settings(
                self, cap_face_pid=cap_pid,
                refinements=self._refinements, initial=state)
            if mesh_config is None:
                self.status_label.set_text("Mesh creation cancelled")
                return
            # Capture inline edits to the region table before any round-trip.
            self._refinements = mesh_config.get('_all_refinements', [])
            action = mesh_config.get('_action')
            if action == 'pick_cap':
                picked = self._pick_single_cap_face()
                if picked is not None:
                    self._cap_face = picked
                state = mesh_config
                continue
            if action in ('add_local', 'add_contact'):
                scope = 'local' if action == 'add_local' else 'contact'
                picked = self._pick_single_vertex(None)
                if picked is not None:
                    self._refinements.append({
                        'scope': scope, 'vertex_pid': picked[0],
                        'vertex_label': picked[1],
                        'fine_size': 0.5, 'radius': 2.0,
                    })
                state = mesh_config
                continue
            if action in ('add_local_edge', 'add_contact_edge'):
                scope = 'local' if action == 'add_local_edge' else 'contact'
                picked = self._pick_single_edge(None)
                if picked is not None:
                    self._refinements.append({
                        'scope': scope, 'edge_pid': picked[0],
                        'edge_label': picked[1],
                        'fine_size': 0.5, 'radius': 2.0,
                    })
                state = mesh_config
                continue
            break

        # Persist the accepted settings for the next invocation (same model).
        self._mesh_settings = mesh_config

        # Sync the active model into the core; it resolves the cap face and
        # refinement vertices geometrically from mesh_config and meshes.
        if self._current_model_data() is None:
            return

        self.status_label.set_text("Generating mesh...")
        while Gtk.events_pending():
            Gtk.main_iteration()

        try:
            stats = self._core.mesh(mesh_config)
        except Exception as e:
            self._show_error("Mesh Error", f"Failed to generate mesh:\n{str(e)}")
            self.status_label.set_text("Error: Mesh generation failed")
            return

        self._sync_menu_sensitivity()

        summary = (
            f"Nodes: {stats['node_count']}, "
            f"Elements: {stats['element_count']}, "
            f"Types: {stats['element_types']}"
        )
        self.status_label.set_text(f"Mesh created — {summary}")

        if "warning" in stats:
            self._show_error("Mesh Warning", stats["warning"])

    def _on_menu_view_mesh(self, menuitem) -> None:
        """Handle Mesh > View Mesh menu activation"""
        if not self._core.has_mesh():
            return

        ugrid = self._core.mesh_object.get_pyvista_mesh(
            part_labels=self._core.part_labels())

        self.parts_builder.set_sensitive_controls(False)
        self.assemblies_builder.set_sensitive_controls(False)
        self.notebook.set_sensitive(False)
        self._sync_menu_sensitivity(enabled=False)
        self.status_label.set_text("Mesh viewer open - close viewer window to continue")

        if not show_mesh(ugrid, on_closed=self._on_viewer_closed, on_error=self._on_viewer_error):
            self.parts_builder.set_sensitive_controls(True)
            self.assemblies_builder.set_sensitive_controls(True)
            self.notebook.set_sensitive(True)
            self._sync_menu_sensitivity()
            self.status_label.set_text("Error: Failed to load mesh")

    def _on_menu_save_mesh(self, menuitem) -> None:
        """Handle Mesh > Save Mesh menu activation"""
        if not self._core.has_mesh():
            return

        builder = self.active_source
        model_name = "model"
        if builder is not None:
            model_name = builder.get_selected_model_name() or model_name
        result = ask_save_mesh_file(self, model_name,
                                    initial_dir=self._last_save_dir)
        if result is None:
            self.status_label.set_text("Mesh save cancelled")
            return

        filename, fmt = result
        self._last_save_dir = os.path.dirname(filename)

        # For owner containers the core needs the current model + picked owners;
        # sync them so it can resolve owner selections geometrically.
        if fmt == "meshdata_json":
            if self._current_model_data() is None:
                return
            self._core.set_face_owners(self._picked_faces)
            self._core.set_vertex_owners(self._picked_vertices)
            self._core.set_edge_owners(self._picked_edges)
        try:
            self._core.save_mesh(filename, fmt, model_name=model_name)
        except Exception as e:
            self._show_error("Mesh Error", f"Failed to save mesh:\n{str(e)}")
            self.status_label.set_text("Error: Mesh save failed")
            return

        self.status_label.set_text(f"Mesh saved to {Path(filename).name}")

    def _face_anchor(self, pid):
        """Geometric anchor for a picked face PID via the core (or None)."""
        if self._current_model_data() is None:
            return None
        return self._core.face_anchor(pid)

    def _on_menu_show_stats(self, menuitem) -> None:
        """Handle Mesh > Show Stats menu activation"""
        stats = self._core.mesh_stats()
        if stats is None:
            return

        dialog = Gtk.Dialog(
            title="Mesh Statistics",
            transient_for=self,
            flags=0,
        )
        dialog.add_button("_Close", Gtk.ResponseType.CLOSE)

        grid = Gtk.Grid()
        grid.set_column_spacing(20)
        grid.set_row_spacing(8)
        grid.set_margin_top(15)
        grid.set_margin_bottom(15)
        grid.set_margin_start(20)
        grid.set_margin_end(20)

        rows = [
            ("Nodes", str(stats['node_count'])),
            ("Elements", str(stats['element_count'])),
            ("Element Types", str(stats['element_types'])),
        ]
        if "warning" in stats:
            rows.append(("Warning", stats["warning"]))

        for i, (prop, value) in enumerate(rows):
            prop_label = Gtk.Label(label=prop)
            prop_label.set_halign(Gtk.Align.START)
            prop_label.set_markup(f"<b>{prop}</b>")
            grid.attach(prop_label, 0, i, 1, 1)

            val_label = Gtk.Label(label=value)
            val_label.set_halign(Gtk.Align.START)
            val_label.set_selectable(True)
            grid.attach(val_label, 1, i, 1, 1)

        dialog.get_content_area().add(grid)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    # --- Menu helper methods ---

    def _finalize_current_mesh(self) -> None:
        """Finalize the core's stored mesh if one exists"""
        self._core.finalize()

    def _sync_menu_sensitivity(
        self,
        enabled: bool = True,
        source=None,
    ) -> None:
        """Update every menu item from current model and mesh state.

        Args:
            enabled: When False, all items are forced off regardless of
                state (used while a viewer is open).
            source: The model source to read model state from. Defaults to the
                active tab (``None`` if it isn't a model source, in which case
                model-related items are disabled). Pass an explicit source from
                a ``switch-page`` handler, where the ``active_source`` property
                has not yet committed to the new page.
        """
        if source is None:
            source = self.active_source
        has_model = source is not None and source.has_model()
        has_mesh = self._core.has_mesh()
        has_picks = bool(self._picked_faces)
        has_vertex_picks = bool(self._picked_vertices)
        has_edge_picks = bool(self._picked_edges)
        self.menu_view.set_sensitive(enabled and has_model)
        self.menu_export.set_sensitive(enabled and has_model)
        self.menu_pick_faces.set_sensitive(enabled and has_model)
        self.menu_edit_face_selection.set_sensitive(enabled and has_picks)
        self.menu_pick_vertices.set_sensitive(enabled and has_model)
        self.menu_edit_vertex_selection.set_sensitive(
            enabled and has_vertex_picks
        )
        self.menu_pick_edges.set_sensitive(enabled and has_model)
        self.menu_edit_edge_selection.set_sensitive(
            enabled and has_edge_picks
        )
        self.menu_create_mesh.set_sensitive(enabled and has_model)
        self.menu_view_mesh.set_sensitive(enabled and has_mesh)
        self.menu_save_mesh.set_sensitive(enabled and has_mesh)
        self.menu_show_stats.set_sensitive(enabled and has_mesh)

    def _invalidate_selections(self, source=None) -> None:
        """Drop the held mesh and all picks/owners/refinements, then refresh
        menu sensitivity.

        Called whenever the active model changes — a parameter or model-type
        change, a tab switch, or (later) a STEP import. Persistent face/vertex
        IDs can shift when topology changes, so stale picks are dropped to avoid
        silently writing wrong MeshEntityContainers. ``source`` is forwarded to
        the sensitivity refresh (needed from ``switch-page``, where
        ``active_source`` hasn't committed yet).
        """
        self._finalize_current_mesh()
        self._picked_faces = []
        self._picked_vertices = []
        self._picked_edges = []
        self._cap_face = None
        self._refinements = []
        self._mesh_settings = None
        self._sync_menu_sensitivity(source=source)

    def _on_params_changed(self, builder) -> None:
        """Model parameters changed → invalidate held mesh + picks."""
        self._invalidate_selections()

    def _on_model_type_changed(self, builder, name: str) -> None:
        """Model-type selection changed → invalidate held mesh + picks."""
        self._invalidate_selections()

    def _on_destroy(self, window) -> None:
        """Clean up mesh resources on window destroy"""
        self._finalize_current_mesh()

    def _on_status_changed(self, builder, message: str) -> None:
        """Handle status change from ModelBuilder.

        Filters out emissions from the inactive tab so they don't overwrite
        the active tab's status display.
        """
        if builder is not self.active_source:
            return
        self.status_label.set_text(message)
        self._sync_menu_sensitivity()

    def _show_info(self, title: str, message: str) -> None:
        """Show info dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _show_error(self, title: str, message: str) -> None:
        """Show error dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title
        )
        dialog.format_secondary_text(message)
        for label in dialog.get_message_area().get_children():
            if isinstance(label, Gtk.Label):
                label.set_selectable(True)
        dialog.run()
        dialog.destroy()


def _show_import_error(exc: ImportError) -> None:
    """Friendly dialog when a required dependency is missing (T1.3)."""
    missing = getattr(exc, "name", None) or "a required module"
    dialog = Gtk.MessageDialog(
        transient_for=None, flags=0,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK,
        text="Missing Dependencies",
    )
    dialog.format_secondary_text(
        f"Could not start: '{missing}' is not available.\n\n"
        f"  {exc}\n\n"
        "Install the project dependencies in the conda environment "
        "(e.g. cadquery, freecad) and try again."
    )
    dialog.run()
    dialog.destroy()


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Set environment for Mesa rendering if needed
    if 'DISPLAY' not in os.environ or not os.environ['DISPLAY']:
        os.environ['DISPLAY'] = ':0'

    os.environ.setdefault('__GLX_VENDOR_LIBRARY_NAME', 'mesa')
    os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')

    # A dependency was missing at import (guarded block above): report it loudly
    # to stderr (developers) and via a friendly dialog (users), then exit.
    if _IMPORT_ERROR is not None:
        import traceback
        traceback.print_exception(type(_IMPORT_ERROR), _IMPORT_ERROR,
                                  _IMPORT_ERROR.__traceback__)
        _show_import_error(_IMPORT_ERROR)
        return

    app = CadQueryApp()
    app.connect("destroy", Gtk.main_quit)
    app.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
