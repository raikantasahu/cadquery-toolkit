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
from widgets import ModelBuilder
from viewer import ModelViewer


class CadQueryApp(Gtk.Window):
    """Main application window"""

    def __init__(self):
        super().__init__(title="CadQuery Model Studio")
        self.set_default_size(700, 600)
        self.set_border_width(10)

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

    def _create_widgets(self) -> None:
        """Create the main UI"""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Header
        title_label = Gtk.Label()
        title_label.set_markup('<span size="x-large" weight="bold">CadQuery Model Studio</span>')
        title_label.set_margin_bottom(5)
        vbox.pack_start(title_label, False, False, 0)

        # Model Builder widget
        self.model_builder = ModelBuilder()
        self.model_builder.connect('view-requested', self._on_view_requested)
        self.model_builder.connect('export-requested', self._on_export_requested)
        self.model_builder.connect('status-changed', self._on_status_changed)
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
        self.status_label.set_text("Viewer open - close viewer window to continue")

        # Show viewer (blocking)
        viewer.show_viewer()

    def _on_viewer_error(self, message: str) -> None:
        """Handle viewer error"""
        self.model_builder.set_sensitive_controls(True)
        self._show_error("Viewer Error", message)
        self.status_label.set_text("Error: Viewer failed")

    def _on_viewer_closed(self) -> None:
        """Called when viewer window is closed"""
        self.model_builder.set_sensitive_controls(True)
        self.present()
        self.status_label.set_text("Viewer closed. Ready to continue.")

    def _on_export_requested(self, builder, model, exporter) -> None:
        """Handle export request from ModelBuilder"""
        # File chooser dialog
        dialog = Gtk.FileChooserDialog(
            title="Export CAD Model",
            parent=self,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK
        )

        # File filters
        filter_json = Gtk.FileFilter()
        filter_json.set_name("JSON files (*.json)")
        filter_json.add_pattern("*.json")
        dialog.add_filter(filter_json)

        filter_step = Gtk.FileFilter()
        filter_step.set_name("STEP files (*.step, *.stp)")
        filter_step.add_pattern("*.step")
        filter_step.add_pattern("*.stp")
        dialog.add_filter(filter_step)

        filter_all = Gtk.FileFilter()
        filter_all.set_name("All supported formats")
        filter_all.add_pattern("*.json")
        filter_all.add_pattern("*.step")
        filter_all.add_pattern("*.stp")
        dialog.add_filter(filter_all)

        dialog.set_do_overwrite_confirmation(True)

        model_name = builder.get_selected_model_name() or "model"
        dialog.set_current_name(f"{model_name}.step")

        response = dialog.run()
        filename = dialog.get_filename()
        selected_filter = dialog.get_filter()
        dialog.destroy()

        if response != Gtk.ResponseType.OK or not filename:
            self.status_label.set_text("Export cancelled")
            return

        # Determine format from extension or filter
        is_step = filename.lower().endswith(('.step', '.stp'))
        is_json = filename.lower().endswith('.json')

        # Add extension if missing based on selected filter
        if not is_step and not is_json:
            if selected_filter == filter_step:
                filename += '.step'
                is_step = True
            else:
                filename += '.json'
                is_json = True

        try:
            if is_step:
                exporter.save_to_step(filename)
            else:
                exporter.save_to_file(filename)
            self.status_label.set_text(f"Exported to {Path(filename).name}")
            self._show_info("Export Successful", f"Model exported to:\n{filename}")
        except Exception as e:
            self._show_error("Export Error", f"Failed to export:\n{str(e)}")
            self.status_label.set_text("Error: Export failed")

    def _on_status_changed(self, builder, message: str) -> None:
        """Handle status change from ModelBuilder"""
        self.status_label.set_text(message)

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
