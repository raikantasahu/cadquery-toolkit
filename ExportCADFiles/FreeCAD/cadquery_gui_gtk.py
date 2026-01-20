"""
cadquery_gui_gtk.py - GTK-based GUI application for creating CadQuery models

This application provides a graphical interface using GTK3 for better text rendering
on Linux systems, especially under conda environments.

Requirements:
    pip install cadquery pygobject --break-system-packages
    # Or: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0
"""
import os
os.environ['NO_AT_BRIDGE'] = '1'

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Pango
import json
import inspect
from pathlib import Path
import tempfile
import base64
import os
from typing import get_origin, get_args, Union

# Import the model creation functions
from models import get_all_models
from cadquery_freecad_exporter import FreeCADExporter

class CadQueryGUI(Gtk.Window):
    def __init__(self):
        super().__init__(title="CadQuery Model Creator")
        self.set_default_size(650, 550)
        self.set_border_width(10)

        # Set up CSS for styling
        self.setup_css()

        # Dictionary to store function references and parameter widgets
        self.functions = {}
        self.param_entries = {}

        # Discover all model creation functions
        self.discover_functions()

        # Create the UI
        self.create_widgets()

    def setup_css(self):
        """Set up CSS styling for the application"""
        css_provider = Gtk.CssProvider()
        css = b"""
        #description-label {
            color: #808080;
        }
        """
        css_provider.load_from_data(css)

        screen = Gdk.Screen.get_default()
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(
            screen,
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def discover_functions(self):
        """Discover all callable functions in models module"""
        from models import get_all_models
        self.functions = get_all_models()

    def get_type_name(self, annotation):
        """Get a human-readable name for a type annotation"""
        if annotation == inspect.Parameter.empty:
            return ""

        # Handle Optional types (Union with None)
        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            # Optional[X] is Union[X, None]
            non_none_args = [a for a in args if a is not type(None)]
            if len(non_none_args) == 1:
                return f"{non_none_args[0].__name__}?"  # ? indicates optional
            return str(annotation)

        if hasattr(annotation, '__name__'):
            return annotation.__name__
        return str(annotation)

    def convert_value(self, value_str: str, annotation, param_name: str, has_default: bool):
        """Convert a string value to the appropriate Python type based on annotation"""
        value_str = value_str.strip()

        # Handle empty string
        if not value_str:
            # Check if parameter has a default or is Optional
            origin = get_origin(annotation)
            if origin is Union:
                args = get_args(annotation)
                if type(None) in args:
                    return None  # Optional parameter, empty means None
            if has_default:
                return None  # Will use default value
            raise ValueError(f"Parameter '{param_name}' is required")

        # Handle explicit None
        if value_str.lower() in ('none', 'null'):
            return None

        # Handle bool (must check before int, since bool is subclass of int)
        if annotation == bool:
            if value_str.lower() in ('true', 'yes', '1'):
                return True
            elif value_str.lower() in ('false', 'no', '0'):
                return False
            else:
                raise ValueError(f"Parameter '{param_name}' expects a boolean (true/false)")

        # Handle int
        if annotation == int:
            try:
                return int(value_str)
            except ValueError:
                raise ValueError(f"Parameter '{param_name}' expects an integer")

        # Handle float
        if annotation == float:
            try:
                return float(value_str)
            except ValueError:
                raise ValueError(f"Parameter '{param_name}' expects a number")

        # Handle str
        if annotation == str:
            return value_str

        # Handle Optional types
        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            non_none_args = [a for a in args if a is not type(None)]
            if non_none_args:
                # Try to convert to the non-None type
                return self.convert_value(value_str, non_none_args[0], param_name, has_default)

        # No annotation or unknown type - use heuristic conversion
        if annotation == inspect.Parameter.empty:
            # Handle explicit None/null
            if value_str.lower() in ('none', 'null'):
                return None

            # Handle boolean strings
            if value_str.lower() in ('true', 'yes'):
                return True
            if value_str.lower() in ('false', 'no'):
                return False

            # Try numeric conversion
            try:
                if '.' in value_str:
                    return float(value_str)
                else:
                    return int(value_str)
            except ValueError:
                return value_str

        # Default: return as string
        return value_str

    def create_widgets(self):
        """Create the GTK widgets"""
        # Main vertical box
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Title
        title_label = Gtk.Label()
        title_label.set_markup('<span size="x-large" weight="bold">CadQuery Model Creator</span>')
        title_label.set_margin_bottom(10)
        vbox.pack_start(title_label, False, False, 0)

        # Model type selection
        selection_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        type_label = Gtk.Label(label="Select Model Type:")
        type_label.set_markup('<b>Select Model Type:</b>')
        type_label.set_halign(Gtk.Align.START)
        selection_box.pack_start(type_label, False, False, 0)

        # Create combo box
        self.function_combo = Gtk.ComboBoxText()
        self.function_combo.set_hexpand(True)
        for func_name in sorted(self.functions.keys()):
            self.function_combo.append_text(func_name)
        self.function_combo.connect("changed", self.on_function_changed)
        selection_box.pack_start(self.function_combo, True, True, 0)

        vbox.pack_start(selection_box, False, False, 0)

        # Description label
        self.description_label = Gtk.Label()
        self.description_label.set_line_wrap(True)
        self.description_label.set_max_width_chars(60)
        self.description_label.set_halign(Gtk.Align.START)
        self.description_label.set_margin_top(5)
        self.description_label.set_margin_bottom(5)
        # Use CSS for styling instead of deprecated override_color
        self.description_label.set_name("description-label")
        vbox.pack_start(self.description_label, False, False, 0)

        # Separator
        separator1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.pack_start(separator1, False, False, 5)

        # Parameters section
        params_label = Gtk.Label()
        params_label.set_markup('<b>Parameters:</b>')
        params_label.set_halign(Gtk.Align.START)
        vbox.pack_start(params_label, False, False, 0)

        # Scrolled window for parameters
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        scrolled.set_vexpand(True)

        # Parameters grid (will be populated dynamically)
        self.params_grid = Gtk.Grid()
        self.params_grid.set_column_spacing(10)
        self.params_grid.set_row_spacing(8)
        self.params_grid.set_margin_start(10)
        self.params_grid.set_margin_end(10)
        self.params_grid.set_margin_top(10)

        scrolled.add(self.params_grid)
        vbox.pack_start(scrolled, True, True, 0)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(10)

        self.export_button = Gtk.Button(label="Create and Export Model")
        self.export_button.connect("clicked", self.on_export_clicked)
        self.export_button.set_sensitive(False)
        button_box.pack_start(self.export_button, False, False, 0)

        clear_button = Gtk.Button(label="Clear")
        clear_button.connect("clicked", self.on_clear_clicked)
        button_box.pack_start(clear_button, False, False, 0)

        vbox.pack_start(button_box, False, False, 0)

        # Status bar
        separator2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.pack_start(separator2, False, False, 5)

        self.status_label = Gtk.Label(label="Select a model type to begin")
        self.status_label.set_halign(Gtk.Align.START)
        # Make status label slightly smaller
        attr_list = Pango.AttrList()
        attr_list.insert(Pango.attr_scale_new(0.9))
        self.status_label.set_attributes(attr_list)
        vbox.pack_start(self.status_label, False, False, 0)

    def on_function_changed(self, combo):
        """Handle function selection"""
        func_name = combo.get_active_text()
        if not func_name:
            return

        # Get the function
        func = self.functions[func_name]

        # Update description
        doc = inspect.getdoc(func)
        if doc:
            # Get first line of docstring
            first_line = doc.split('\n')[0]
            self.description_label.set_text(first_line)
        else:
            self.description_label.set_text("")

        # Clear existing parameter widgets
        for child in self.params_grid.get_children():
            self.params_grid.remove(child)
        self.param_entries.clear()

        # Get function signature
        sig = inspect.signature(func)

        # Create parameter input fields
        if sig.parameters:
            row = 0
            for param_name, param in sig.parameters.items():
                # Get type annotation for display
                type_name = self.get_type_name(param.annotation)

                # Parameter label with type hint
                if type_name:
                    label_text = f"{param_name} ({type_name}):"
                else:
                    label_text = f"{param_name}:"

                label = Gtk.Label(label=label_text)
                label.set_halign(Gtk.Align.END)
                self.params_grid.attach(label, 0, row, 1, 1)

                # Parameter entry
                entry = Gtk.Entry()
                entry.set_hexpand(True)
                entry.set_width_chars(20)

                # Add placeholder text for booleans
                if param.annotation == bool:
                    entry.set_placeholder_text("true / false")

                # Add default value if exists
                if param.default != inspect.Parameter.empty:
                    entry.set_text(str(param.default))

                self.params_grid.attach(entry, 1, row, 1, 1)

                # Store reference
                self.param_entries[param_name] = entry
                row += 1

            self.params_grid.show_all()
            self.export_button.set_sensitive(True)
            self.status_label.set_text(f"Enter parameters for {func_name}")
        else:
            # No parameters needed
            no_params_label = Gtk.Label(label="This model requires no parameters")
            self.params_grid.attach(no_params_label, 0, 0, 2, 1)
            self.params_grid.show_all()
            self.export_button.set_sensitive(True)
            self.status_label.set_text(f"Ready to create {func_name}")

    def on_export_clicked(self, button):
        """Create the model and export to JSON with embedded CAD data"""
        func_name = self.function_combo.get_active_text()
        if not func_name:
            self.show_warning("No Selection", "Please select a model type first.")
            return

        func = self.functions[func_name]

        # Collect parameters
        params = {}
        sig = inspect.signature(func)

        try:
            for param_name, param in sig.parameters.items():
                if param_name in self.param_entries:
                    value_str = self.param_entries[param_name].get_text()
                    has_default = param.default != inspect.Parameter.empty

                    # Convert value based on type annotation
                    converted = self.convert_value(
                        value_str,
                        param.annotation,
                        param_name,
                        has_default
                    )

                    # Only add to params if we got a value (skip None for optional with defaults)
                    if converted is not None:
                        params[param_name] = converted
                    elif not has_default:
                        # Required parameter with None value - this shouldn't happen
                        # but let's handle it
                        params[param_name] = None

            # Create the model
            self.status_label.set_text(f"Creating {func_name}...")
            while Gtk.events_pending():
                Gtk.main_iteration()

            model = func(**params)

            # Ask for save location
            dialog = Gtk.FileChooserDialog(
                title="Save CAD Model Data",
                parent=self,
                action=Gtk.FileChooserAction.SAVE
            )
            dialog.add_buttons(
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_SAVE, Gtk.ResponseType.OK
            )

            # Add file filter for JSON
            filter_json = Gtk.FileFilter()
            filter_json.set_name("JSON files")
            filter_json.add_pattern("*.json")
            dialog.add_filter(filter_json)

            filter_all = Gtk.FileFilter()
            filter_all.set_name("All files")
            filter_all.add_pattern("*")
            dialog.add_filter(filter_all)

            dialog.set_do_overwrite_confirmation(True)
            dialog.set_current_name("model.json")

            response = dialog.run()
            filename = dialog.get_filename()
            dialog.destroy()

            if response != Gtk.ResponseType.OK or not filename:
                self.status_label.set_text("Export cancelled")
                return

            # Ensure .json extension
            if not filename.endswith('.json'):
                filename += '.json'

            # Export model to STEP format in a temporary file
            self.status_label.set_text(f"Exporting geometry data...")
            while Gtk.events_pending():
                Gtk.main_iteration()

            # Export model to CAD_ModelData format
            model_filename = Path(filename).stem
            exporter = FreeCADExporter(model, model_name=model_filename)
            exporter.save_to_file(filename)

            self.status_label.set_text(f"Model exported successfully to {Path(filename).name}")
            self.show_info(
                "Success",
                f"Model created and exported!\n\n"
                f"JSON: {Path(filename).name}\n"
            )

        except ValueError as e:
            self.show_error("Input Error", str(e))
            self.status_label.set_text("Error: Invalid input")
        except Exception as e:
            self.show_error("Error", f"Failed to create model:\n{str(e)}")
            self.status_label.set_text("Error: Model creation failed")

    def on_clear_clicked(self, button):
        """Clear the form"""
        self.function_combo.set_active(-1)
        self.description_label.set_text("")
        for child in self.params_grid.get_children():
            self.params_grid.remove(child)
        self.param_entries.clear()
        self.export_button.set_sensitive(False)
        self.status_label.set_text("Select a model type to begin")

    def show_info(self, title, message):
        """Show an info dialog"""
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

    def show_warning(self, title, message):
        """Show a warning dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text=title
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def show_error(self, title, message):
        """Show an error dialog"""
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
    win = CadQueryGUI()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
