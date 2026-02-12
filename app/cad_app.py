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

from pathlib import Path

from exporter import HAS_CADQUERY, HAS_FREECAD
from mesher import HAS_GMSH, create_mesh, save_mesh, save_mesh_json
from dialogs import ask_save_mesh_file, ask_export_file, ask_mesh_settings
from widgets import ModelBuilder
from viewer import ModelViewer, show_mesh


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
        self.menu_create_mesh = builder.get_object("menu_create_mesh")
        self.menu_view_mesh = builder.get_object("menu_view_mesh")
        self.menu_save_mesh = builder.get_object("menu_save_mesh")

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

        # Model Builder widget
        self.model_builder = ModelBuilder()
        self.model_builder.connect('view-requested', self._on_view_requested)
        self.model_builder.connect('status-changed', self._on_status_changed)
        self.model_builder.connect('params-changed', self._on_params_changed)
        self.model_builder.function_combo.connect('changed', self._on_model_type_changed)
        vbox.pack_start(self.model_builder, True, True, 0)

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

    def _on_view_requested(self, builder, model, exporter) -> None:
        """Handle view request from ModelBuilder"""
        self.status_label.set_text("Opening viewer...")
        while Gtk.events_pending():
            Gtk.main_iteration()

        # Create viewer widget
        viewer = ModelViewer()
        viewer.connect('viewer-closed', lambda v: self._on_viewer_closed())
        viewer.connect('error', lambda v, msg: self._on_viewer_error(msg))

        # Load mesh
        if not viewer.set_mesh_from_exporter(exporter):
            self.status_label.set_text("Error: Failed to load mesh")
            return

        # Disable controls while viewer is open
        self.model_builder.set_sensitive_controls(False)
        self._set_menu_sensitive(False)
        self.status_label.set_text("Viewer open - close viewer window to continue")

        # Show viewer (blocking)
        viewer.show_viewer()

    def _on_viewer_error(self, message: str) -> None:
        """Handle viewer error"""
        self.model_builder.set_sensitive_controls(True)
        self._set_menu_sensitive(True)
        self._show_error("Viewer Error", message)
        self.status_label.set_text("Error: Viewer failed")

    def _on_viewer_closed(self) -> None:
        """Called when viewer window is closed"""
        self.model_builder.set_sensitive_controls(True)
        self._set_menu_sensitive(True)
        self.present()
        self.status_label.set_text("Viewer closed. Ready to continue.")

    # --- Menu callbacks ---

    def _on_menu_view(self, menuitem) -> None:
        """Handle Model > View menu activation"""
        self.model_builder.view_button.clicked()

    def _on_menu_export(self, menuitem) -> None:
        """Handle Model > Export menu activation"""
        if not self.model_builder.build_model():
            return

        model_name = self.model_builder.get_selected_model_name() or "model"
        exporter = self.model_builder.get_current_exporter()
        result = ask_export_file(self, model_name)

        if result is None:
            self.status_label.set_text("Export cancelled")
            return

        filename, fmt = result

        try:
            if fmt == "step":
                exporter.save_to_step(filename)
            else:
                exporter.save_to_file(filename)
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

        # Show mesh settings dialog
        mesh_config = ask_mesh_settings(self)
        if mesh_config is None:
            self.status_label.set_text("Mesh creation cancelled")
            return

        if not self.model_builder.build_model():
            return

        # Finalize any previously held mesh
        self._finalize_current_mesh()

        model = self.model_builder.get_current_model()
        model_name = self.model_builder.get_selected_model_name() or "model"

        self.status_label.set_text("Generating mesh...")
        while Gtk.events_pending():
            Gtk.main_iteration()

        try:
            mesh, stats = create_mesh(
                model, mesh_config['mesh_type'], mesh_config['element_size'],
                model_name=model_name,
            )
        except Exception as e:
            self._show_error("Mesh Error", f"Failed to generate mesh:\n{str(e)}")
            self.status_label.set_text("Error: Mesh generation failed")
            return

        self._current_mesh = mesh
        self._current_mesh_stats = stats
        self._update_mesh_menu_sensitivity()

        summary = (
            f"Nodes: {stats['node_count']}, "
            f"Elements: {stats['element_count']}, "
            f"Types: {stats['element_types']}"
        )
        self.status_label.set_text(f"Mesh created — {summary}")

    def _on_menu_view_mesh(self, menuitem) -> None:
        """Handle Mesh > View Mesh menu activation"""
        if self._current_mesh is None:
            return

        ugrid = self._current_mesh.get_pyvista_mesh()

        self.model_builder.set_sensitive_controls(False)
        self._set_menu_sensitive(False)
        self.status_label.set_text("Mesh viewer open - close viewer window to continue")

        if not show_mesh(ugrid, on_closed=self._on_viewer_closed, on_error=self._on_viewer_error):
            self.model_builder.set_sensitive_controls(True)
            self._set_menu_sensitive(True)
            self.status_label.set_text("Error: Failed to load mesh")

    def _on_menu_save_mesh(self, menuitem) -> None:
        """Handle Mesh > Save Mesh menu activation"""
        if self._current_mesh is None:
            return

        model_name = self.model_builder.get_selected_model_name() or "model"
        result = ask_save_mesh_file(self, model_name)
        if result is None:
            self.status_label.set_text("Mesh save cancelled")
            return

        filename, fmt = result

        try:
            if fmt == "json":
                save_mesh_json(self._current_mesh, filename, title=model_name)
            else:
                save_mesh(self._current_mesh, filename)
        except Exception as e:
            self._show_error("Mesh Error", f"Failed to save mesh:\n{str(e)}")
            self.status_label.set_text("Error: Mesh save failed")
            return

        self.status_label.set_text(f"Mesh saved to {Path(filename).name}")

    # --- Menu helper methods ---

    def _finalize_current_mesh(self) -> None:
        """Finalize the stored mesh if one exists"""
        if self._current_mesh is not None:
            self._current_mesh.finalize()
            self._current_mesh = None
            self._current_mesh_stats = None

    def _update_mesh_menu_sensitivity(self) -> None:
        """Update View Mesh / Save Mesh sensitivity based on stored mesh"""
        has_mesh = self._current_mesh is not None
        self.menu_view_mesh.set_sensitive(has_mesh)
        self.menu_save_mesh.set_sensitive(has_mesh)

    def _set_menu_sensitive(self, sensitive: bool) -> None:
        """Enable/disable all menu items, respecting model/mesh state"""
        has_model = self.model_builder.get_selected_model_name() is not None
        has_mesh = self._current_mesh is not None
        self.menu_view.set_sensitive(sensitive and has_model)
        self.menu_export.set_sensitive(sensitive and has_model)
        self.menu_create_mesh.set_sensitive(sensitive and has_model)
        self.menu_view_mesh.set_sensitive(sensitive and has_mesh)
        self.menu_save_mesh.set_sensitive(sensitive and has_mesh)

    def _on_params_changed(self, builder) -> None:
        """Clear stored mesh when model parameters change"""
        self._finalize_current_mesh()
        self._update_mesh_menu_sensitivity()

    def _on_model_type_changed(self, combo) -> None:
        """Clear stored mesh when model type selection changes"""
        self._finalize_current_mesh()
        self._update_mesh_menu_sensitivity()

    def _on_destroy(self, window) -> None:
        """Clean up mesh resources on window destroy"""
        self._finalize_current_mesh()

    def _on_status_changed(self, builder, message: str) -> None:
        """Handle status change from ModelBuilder"""
        self.status_label.set_text(message)
        # Sync menu sensitivity with builder state
        has_model = self.model_builder.get_selected_model_name() is not None
        has_mesh = self._current_mesh is not None
        self.menu_view.set_sensitive(has_model)
        self.menu_export.set_sensitive(has_model)
        self.menu_create_mesh.set_sensitive(has_model)
        self.menu_view_mesh.set_sensitive(has_mesh)
        self.menu_save_mesh.set_sensitive(has_mesh)

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
