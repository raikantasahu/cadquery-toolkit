"""
cad_app.py - CadQuery Model Studio

Main application combining model creation and 3D viewing.

Usage:
    python cad_app.py
"""

import os
os.environ['NO_AT_BRIDGE'] = '1'

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Pango

import cadquery as cq

from pathlib import Path
from typing import Optional

from converter import (
    HAS_CADQUERY, HAS_FREECAD,
    part_to_modeldata, assembly_to_modeldata,
)
from exporter import cadmodeldata_exporter, step_exporter
from mesher import (
    HAS_GMSH, create_mesh, save_mesh, save_mesh_json,
    save_mesh_meshdata_json, ExtrusionSpec, RefinementSpec,
)
from dialogs import (
    ask_save_mesh_file, ask_export_file, ask_mesh_settings,
    edit_face_selection, pick_entities,
)
from widgets import ModelBuilder
from viewer import ModelViewer, show_mesh
from viewer.model_viewer import enumerate_part_labels, create_polydatas_per_part

from models.parts import get_all_parts
from models.assemblies import get_all_assemblies


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

        # Mesh state
        self._current_mesh = None
        self._current_mesh_stats = None
        # Face / vertex picks: lists of (persistent_id, owner_label) tuples.
        # Populated by the model viewer's pick modes; both consumed by the
        # MeshData save flow as entity_owners. Cleared on model change.
        # Kept separate so each picker pre-populates and edits only its own
        # entity type (F* and V* keys never collide in entity_owners).
        self._picked_faces: list = []
        self._picked_vertices: list = []
        # Single cap face (persistent_id, label) for extruded hex, or None.
        self._cap_face: tuple = None
        # Refinement regions: list of dicts
        # {scope, vertex_pid, vertex_label, fine_size, radius}. Each anchors on
        # a picked vertex; resolved to (coordinate, part index) at mesh time.
        self._refinements: list = []
        # Last-used Mesh Settings, persisted across dialog invocations for the
        # same model; reset to None (dialog defaults) when the model changes.
        self._mesh_settings: dict = None
        self.connect("destroy", self._on_destroy)

        # Check dependencies
        if not HAS_CADQUERY:
            self._show_dependency_error("CadQuery not installed.\nRun: conda install -c conda-forge cadquery")
            return
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
        self.notebook.connect('switch-page', self._on_tab_switched)

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

        # Keyboard shortcuts info
        shortcuts_label = Gtk.Label()
        shortcuts_label.set_markup(
            '<small><b>Viewer shortcuts:</b> 1-6: Views | R: Reset | W: Wireframe | Q: Close</small>'
        )
        shortcuts_label.set_halign(Gtk.Align.START)
        shortcuts_label.set_margin_top(5)
        vbox.pack_start(shortcuts_label, False, False, 0)

    # --- Active-builder helpers ---

    @property
    def model_builder(self) -> Optional[ModelBuilder]:
        """Return the active tab if it is a ``ModelBuilder``, else ``None``.

        Answers the typed conditional question "is the active tab a model
        builder, and if so, which?" — not the broader "which widget is the
        active tab?" The notebook can in principle hold non-builder pages
        (a future Settings tab, etc.); this property returns ``None`` for
        those, and callers that operate on a builder either short-circuit
        on ``None`` or are gated upstream by menu-item sensitivity (which
        is itself ``False`` when no active builder is present).
        """
        page_num = self.notebook.get_current_page()
        if page_num < 0:
            return None
        page = self.notebook.get_nth_page(page_num)
        return page if isinstance(page, ModelBuilder) else None

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

        Reads the new builder from `page_num` rather than via the
        `model_builder` property because GTK has not yet committed
        `get_current_page()` at the time this signal fires.
        """
        self._finalize_current_mesh()
        self._picked_faces = []
        self._picked_vertices = []
        self._cap_face = None
        self._refinements = []
        self._mesh_settings = None
        builder = notebook.get_nth_page(page_num)
        self._sync_menu_sensitivity(builder=builder)
        status = builder.last_status_message
        if not status:
            status = f"{notebook.get_tab_label_text(builder)} — no model selected"
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

        # Convert the freshly built model to a CAD_ModelData and feed it to
        # the viewer. Assemblies route through assembly_to_modeldata; parts
        # carry their build parameters / signature into the part envelope.
        try:
            if isinstance(model, cq.Assembly):
                model_data = assembly_to_modeldata(model)
            else:
                model_data = part_to_modeldata(
                    model,
                    name=builder.get_selected_model_name() or "model",
                    parameters=builder.get_current_build_params(),
                    param_signature=builder.get_current_build_signature(),
                )
        except Exception as e:
            self._show_error("Conversion Error", f"Failed to convert model:\n{e}")
            self.status_label.set_text("Error: Conversion failed")
            return

        if not viewer.set_mesh_from_dict(model_data.to_dict()):
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
        builder = self.model_builder
        if builder is None:
            return
        builder.request_view()

    def _on_menu_pick_faces(self, menuitem) -> None:
        """Handle Model > Pick Faces menu activation."""
        self._open_pick_viewer(
            pick_mode="faces",
            title="Pick Faces",
            status_text=(
                "Face picker open — press 'p' over a face to pick/unpick. "
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
                "Vertex picker open — press 'p' over a vertex to pick/unpick. "
                "Close window when done."
            ),
            initial_picks=self._picked_vertices,
            on_closed=self._on_pick_vertices_viewer_closed,
        )

    def _open_pick_viewer(self, pick_mode, title, status_text,
                          initial_picks, on_closed) -> None:
        """Build the current model and open the viewer in a pick mode.

        Shared by the face and vertex pickers — they differ only in mode,
        window title, status text, the pre-populated selection, and the
        close handler that commits the result.
        """
        builder = self.model_builder
        if builder is None:
            return
        if not builder.build_model():
            return

        model = builder.get_current_model()
        try:
            if isinstance(model, cq.Assembly):
                model_data = assembly_to_modeldata(model)
            else:
                model_data = part_to_modeldata(
                    model,
                    name=builder.get_selected_model_name() or "model",
                    parameters=builder.get_current_build_params(),
                    param_signature=builder.get_current_build_signature(),
                )
        except Exception as e:
            self._show_error("Conversion Error", f"Failed to convert model:\n{e}")
            self.status_label.set_text("Error: Conversion failed")
            return

        viewer = ModelViewer()
        viewer.connect('viewer-closed', lambda v: on_closed(v))
        viewer.connect('error', lambda v, msg: self._on_viewer_error(msg))

        if not viewer.set_mesh_from_dict(
            model_data.to_dict(), with_face_index=True,
        ):
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

    def _current_model_data(self) -> Optional[dict]:
        """Build the active model's CADModelData dict for picking, or None.

        Shared entry point for any pick-driven mesh control (see
        ``dialogs.entity_picker.pick_entities``). Shows an error dialog and
        returns None if there's no model or conversion fails.
        """
        builder = self.model_builder
        if builder is None or not builder.build_model():
            return None
        model = builder.get_current_model()
        try:
            if isinstance(model, cq.Assembly):
                model_data = assembly_to_modeldata(model)
            else:
                model_data = part_to_modeldata(
                    model,
                    name=builder.get_selected_model_name() or "model",
                    parameters=builder.get_current_build_params(),
                    param_signature=builder.get_current_build_signature(),
                )
        except Exception as e:
            self._show_error("Conversion Error", f"Failed to convert model:\n{e}")
            return None
        return model_data.to_dict()

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

    def _resolve_vertex_anchor(self, picked):
        """Resolve a picked vertex ``(pid, label)`` to ``(coord, part_index)``.

        The picker's vertex ids are not portable to the mesher (CAD traversal
        order != gmsh import order on assemblies), but the vertex's world
        coordinate is — and so is its 0-based part index (assembly order ==
        gmsh volume order). Both come from the same per-part PolyData the picker
        itself used. The mesher re-identifies its own vertex from the
        coordinate. Returns ``(coord_tuple, part_index)`` or ``None``.
        """
        if not picked:
            return None
        pid = picked[0]
        model_data = self._current_model_data()
        if model_data is None:
            return None
        import numpy as np
        for part_index, (_label, pd) in enumerate(
                create_polydatas_per_part(model_data, with_face_index=True)):
            fd = pd.field_data
            if "vertex_pids" not in fd:
                continue
            pids = [str(v) for v in fd["vertex_pids"]]
            pts = np.asarray(fd["vertex_points"]).reshape(-1, 3)
            for vpid, p in zip(pids, pts):
                if vpid == pid:
                    return (tuple(float(c) for c in p), part_index)
        return None

    def _on_menu_export(self, menuitem) -> None:
        """Handle Model > Export menu activation"""
        builder = self.model_builder
        if builder is None:
            return
        if not builder.build_model():
            return

        model_name = builder.get_selected_model_name() or "model"
        model = builder.get_current_model()
        result = ask_export_file(self, model_name)

        if result is None:
            self.status_label.set_text("Export cancelled")
            return

        filename, fmt = result

        try:
            if fmt == "step":
                step_exporter.export(model, filename)
            elif isinstance(model, cq.Assembly):
                cadmodeldata_exporter.export(model, filename)
            else:
                cadmodeldata_exporter.export(
                    model,
                    filename,
                    name=model_name,
                    parameters=builder.get_current_build_params(),
                    param_signature=builder.get_current_build_signature(),
                )
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
            break

        # Persist the accepted settings for the next invocation (same model).
        self._mesh_settings = mesh_config

        # Build the extrusion spec when extruded hex is requested.
        extrusion = None
        ex = mesh_config.get('extrusion')
        if ex:
            if not ex.get('cap_face'):
                self._show_error(
                    "Mesh Error",
                    "Extruded hex needs a cap face.\n"
                    "Click \"Pick…\" in the mesh dialog to choose one."
                )
                self.status_label.set_text("Error: no cap face for extrusion")
                return
            extrusion = ExtrusionSpec(
                cap_face=ex['cap_face'], num_layers=ex['num_layers'])

        # Build refinement specs from the region table. Each region anchors on a
        # picked vertex resolved to its world COORDINATE (and 0-based part index
        # for local scope): picker vertex ids do not match gmsh's import ordering
        # on assemblies, but coordinates and part order do. See
        # _resolve_vertex_anchor. mesh_config['refinements'] is empty while
        # extruding (mutually exclusive).
        refinements = []
        for region in mesh_config.get('refinements', []):
            anchor = self._resolve_vertex_anchor(
                (region['vertex_pid'], region.get('vertex_label', '')))
            if anchor is None:
                self._show_error(
                    "Mesh Error",
                    f"Refinement vertex {region['vertex_pid']} could not be "
                    "resolved on the current model."
                )
                self.status_label.set_text("Error: unresolved refinement vertex")
                return
            coord, part_index = anchor
            refinements.append(RefinementSpec(
                at=coord, fine_size=region['fine_size'],
                radius=region['radius'], scope=region['scope'],
                part_index=part_index if region['scope'] == 'local' else None))

        builder = self.model_builder
        if builder is None:
            return
        if not builder.build_model():
            return

        # Finalize any previously held mesh
        self._finalize_current_mesh()

        model = builder.get_current_model()
        model_name = builder.get_selected_model_name() or "model"

        self.status_label.set_text("Generating mesh...")
        while Gtk.events_pending():
            Gtk.main_iteration()

        try:
            mesh, stats = create_mesh(
                model, mesh_config['mesh_type'], mesh_config['element_size'],
                model_name=model_name,
                relative_sag_tolerance=mesh_config['relative_sag_tolerance'],
                extrusion=extrusion,
                refinements=refinements,
            )
        except Exception as e:
            self._show_error("Mesh Error", f"Failed to generate mesh:\n{str(e)}")
            self.status_label.set_text("Error: Mesh generation failed")
            return

        self._current_mesh = mesh
        self._current_mesh_stats = stats
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
        if self._current_mesh is None:
            return

        ugrid = self._current_mesh.get_pyvista_mesh()

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
        if self._current_mesh is None:
            return

        builder = self.model_builder
        model_name = "model"
        if builder is not None:
            model_name = builder.get_selected_model_name() or model_name
        result = ask_save_mesh_file(self, model_name)
        if result is None:
            self.status_label.set_text("Mesh save cancelled")
            return

        filename, fmt = result

        entity_owners = self._build_entity_owners(builder) if fmt == "meshdata_json" else None
        try:
            if fmt == "meshdata_json":
                save_mesh_meshdata_json(
                    self._current_mesh, filename, owner=model_name,
                    entity_owners=entity_owners,
                )
            elif fmt == "json":
                save_mesh_json(self._current_mesh, filename, title=model_name)
            else:
                save_mesh(self._current_mesh, filename)
        except Exception as e:
            self._show_error("Mesh Error", f"Failed to save mesh:\n{str(e)}")
            self.status_label.set_text("Error: Mesh save failed")
            return

        self.status_label.set_text(f"Mesh saved to {Path(filename).name}")

    def _build_entity_owners(self, builder) -> Optional[dict]:
        """Assemble the entity_owners dict passed to MeshData JSON save.

        Picked-face ``Fn`` entries come from the model viewer's picker;
        ``Pn`` entries are auto-filled from the current model's part
        labels (same DFS order used by ``create_polydatas_per_part``) so
        per-part MeshFragments come out named without the user having to
        author a YAML config. Returns ``None`` when nothing to attach.
        """
        owners: dict = {}
        if self._picked_faces:
            owners.update(self._picked_faces)
        if self._picked_vertices:
            owners.update(self._picked_vertices)

        if builder is not None:
            model = builder.get_current_model()
            try:
                if isinstance(model, cq.Assembly):
                    model_data = assembly_to_modeldata(model)
                else:
                    model_data = part_to_modeldata(
                        model,
                        name=builder.get_selected_model_name() or "model",
                        parameters=builder.get_current_build_params(),
                        param_signature=builder.get_current_build_signature(),
                    )
                labels = enumerate_part_labels(model_data.to_dict())
            except Exception:
                # If label enumeration fails, fall through with what we have
                # (the mesher will apply "part_{n+1}" defaults per volume).
                labels = []
            for i, label in enumerate(labels):
                owners.setdefault(f"P{i}", label)

        return owners or None

    def _on_menu_show_stats(self, menuitem) -> None:
        """Handle Mesh > Show Stats menu activation"""
        stats = self._current_mesh_stats
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
        """Finalize the stored mesh if one exists"""
        if self._current_mesh is not None:
            self._current_mesh.finalize()
            self._current_mesh = None
            self._current_mesh_stats = None

    def _sync_menu_sensitivity(
        self,
        enabled: bool = True,
        builder: Optional[ModelBuilder] = None,
    ) -> None:
        """Update every menu item from current model and mesh state.

        Args:
            enabled: When False, all items are forced off regardless of
                state (used while a viewer is open).
            builder: The ModelBuilder to read model state from. Defaults to
                the active tab (which may be ``None`` if the active tab is
                not a ModelBuilder, in which case all model-related items
                are disabled). Pass an explicit builder when called from
                inside a ``switch-page`` handler, where the
                ``model_builder`` property has not yet committed to the new
                page.
        """
        if builder is None:
            builder = self.model_builder
        has_model = (
            builder is not None
            and builder.get_selected_model_name() is not None
        )
        has_mesh = self._current_mesh is not None
        has_picks = bool(self._picked_faces)
        has_vertex_picks = bool(self._picked_vertices)
        self.menu_view.set_sensitive(enabled and has_model)
        self.menu_export.set_sensitive(enabled and has_model)
        self.menu_pick_faces.set_sensitive(enabled and has_model)
        self.menu_edit_face_selection.set_sensitive(enabled and has_picks)
        self.menu_pick_vertices.set_sensitive(enabled and has_model)
        self.menu_edit_vertex_selection.set_sensitive(
            enabled and has_vertex_picks
        )
        self.menu_create_mesh.set_sensitive(enabled and has_model)
        self.menu_view_mesh.set_sensitive(enabled and has_mesh)
        self.menu_save_mesh.set_sensitive(enabled and has_mesh)
        self.menu_show_stats.set_sensitive(enabled and has_mesh)

    def _on_params_changed(self, builder) -> None:
        """Clear stored mesh and face picks when model parameters change.

        Persistent face IDs can shift when parameters alter topology
        (e.g. a dimension change that adds or removes a fillet), so the
        previous selection is dropped to avoid silently writing wrong
        MeshEntityContainers.
        """
        self._finalize_current_mesh()
        self._picked_faces = []
        self._picked_vertices = []
        self._cap_face = None
        self._refinements = []
        self._mesh_settings = None
        self._sync_menu_sensitivity()

    def _on_model_type_changed(self, builder, name: str) -> None:
        """Clear stored mesh and face picks when model type selection changes"""
        self._finalize_current_mesh()
        self._picked_faces = []
        self._picked_vertices = []
        self._cap_face = None
        self._refinements = []
        self._mesh_settings = None
        self._sync_menu_sensitivity()

    def _on_destroy(self, window) -> None:
        """Clean up mesh resources on window destroy"""
        self._finalize_current_mesh()

    def _on_status_changed(self, builder, message: str) -> None:
        """Handle status change from ModelBuilder.

        Filters out emissions from the inactive tab so they don't overwrite
        the active tab's status display.
        """
        if builder is not self.model_builder:
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


def main():
    # Set environment for Mesa rendering if needed
    if 'DISPLAY' not in os.environ or not os.environ['DISPLAY']:
        os.environ['DISPLAY'] = ':0'

    os.environ.setdefault('__GLX_VENDOR_LIBRARY_NAME', 'mesa')
    os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')

    app = CadQueryApp()
    app.connect("destroy", Gtk.main_quit)
    app.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
