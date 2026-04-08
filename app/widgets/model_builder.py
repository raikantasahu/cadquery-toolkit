"""
model_builder.py - Composite widget for CadQuery model construction

This widget provides:
- Model type selection dropdown
- Dynamic parameter inputs based on function signature
- Build, view, and export actions

Usage:
    builder = ModelBuilder()
    builder.connect('model-built', on_model_built)
    builder.connect('view-requested', on_view_requested)
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, Pango

import inspect
from typing import get_origin, get_args, Union, Optional, Callable, Dict, Any


class ModelBuilder(Gtk.Box):
    """
    Composite widget for building CadQuery models.

    Signals:
        model-built: Emitted when a model is successfully built
            Args: model (CadQuery Workplane)
        view-requested: Emitted when user clicks View Model
            Args: model (CadQuery Workplane)
        status-changed: Emitted when status message changes
            Args: message (str)
    """

    __gtype_name__ = 'ModelBuilder'

    __gsignals__ = {
        'model-built': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'view-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'status-changed': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'params-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, model_functions: Optional[Dict[str, Callable]] = None):
        """
        Initialize the ModelBuilder widget.

        Args:
            model_functions: Dictionary of {name: function} for available models.
                            If None, will attempt to load from models module.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # State
        self.functions = model_functions or {}
        self.param_entries = {}
        self.current_model = None
        self.current_build_params = {}
        self.current_build_sig = None

        # Load models if not provided
        if not self.functions:
            self._load_models()

        # Build UI
        self._create_widgets()

    def _load_models(self) -> None:
        """Load model functions from models module"""
        try:
            from models import get_all_models
            self.functions = get_all_models()
        except ImportError:
            self.functions = {}

    def _create_widgets(self) -> None:
        """Create the widget UI"""
        # Model type selection
        selection_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        type_label = Gtk.Label()
        type_label.set_markup('<b>Model Type:</b>')
        selection_box.pack_start(type_label, False, False, 0)

        self.function_combo = Gtk.ComboBoxText()
        self.function_combo.set_hexpand(True)
        for func_name in sorted(self.functions.keys()):
            self.function_combo.append_text(func_name)
        self.function_combo.connect("changed", self._on_function_changed)
        selection_box.pack_start(self.function_combo, True, True, 0)

        self.pack_start(selection_box, False, False, 0)

        # Description label
        self.description_label = Gtk.Label()
        self.description_label.set_line_wrap(True)
        self.description_label.set_max_width_chars(80)
        self.description_label.set_halign(Gtk.Align.START)
        self.pack_start(self.description_label, False, False, 0)

        # Separator
        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 5)

        # Parameters section
        params_label = Gtk.Label()
        params_label.set_markup('<b>Parameters:</b>')
        params_label.set_halign(Gtk.Align.START)
        self.pack_start(params_label, False, False, 0)

        # Scrolled window for parameters
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        scrolled.set_vexpand(True)

        self.params_grid = Gtk.Grid()
        self.params_grid.set_column_spacing(10)
        self.params_grid.set_row_spacing(8)
        self.params_grid.set_margin_start(10)
        self.params_grid.set_margin_end(10)
        self.params_grid.set_margin_top(10)

        scrolled.add(self.params_grid)
        self.pack_start(scrolled, True, True, 0)

        # Action buttons
        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 5)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(10)

        # View Model button
        self.view_button = Gtk.Button(label="View Model")
        self.view_button.get_style_context().add_class("suggested-action")
        self.view_button.connect("clicked", self._on_view_clicked)
        self.view_button.set_sensitive(False)
        self.view_button.set_size_request(150, -1)
        button_box.pack_start(self.view_button, False, False, 0)

        # Clear button
        self.clear_button = Gtk.Button(label="Clear")
        self.clear_button.connect("clicked", self._on_clear_clicked)
        self.clear_button.set_size_request(100, -1)
        button_box.pack_start(self.clear_button, False, False, 0)

        self.pack_start(button_box, False, False, 0)

    def _get_type_name(self, annotation) -> str:
        """Get human-readable type name from annotation"""
        if annotation == inspect.Parameter.empty:
            return ""

        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            non_none_args = [a for a in args if a is not type(None)]
            if len(non_none_args) == 1:
                return f"{non_none_args[0].__name__}?"
            return str(annotation)

        if hasattr(annotation, '__name__'):
            return annotation.__name__
        return str(annotation)

    def _convert_value(self, value_str: str, annotation, param_name: str, has_default: bool):
        """Convert string to appropriate Python type"""
        value_str = value_str.strip()

        if not value_str:
            origin = get_origin(annotation)
            if origin is Union:
                args = get_args(annotation)
                if type(None) in args:
                    return None
            if has_default:
                return None
            raise ValueError(f"Parameter '{param_name}' is required")

        if value_str.lower() in ('none', 'null'):
            return None

        if annotation == bool:
            if value_str.lower() in ('true', 'yes', '1'):
                return True
            elif value_str.lower() in ('false', 'no', '0'):
                return False
            raise ValueError(f"Parameter '{param_name}' expects boolean")

        if annotation == int:
            try:
                return int(value_str)
            except ValueError:
                raise ValueError(f"Parameter '{param_name}' expects integer")

        if annotation == float:
            try:
                return float(value_str)
            except ValueError:
                raise ValueError(f"Parameter '{param_name}' expects number")

        if annotation == str:
            return value_str

        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            non_none_args = [a for a in args if a is not type(None)]
            if non_none_args:
                return self._convert_value(value_str, non_none_args[0], param_name, has_default)

        if annotation == inspect.Parameter.empty:
            if value_str.lower() in ('none', 'null'):
                return None
            if value_str.lower() in ('true', 'yes'):
                return True
            if value_str.lower() in ('false', 'no'):
                return False
            try:
                return float(value_str) if '.' in value_str else int(value_str)
            except ValueError:
                return value_str

        return value_str

    def _on_function_changed(self, combo) -> None:
        """Handle model type selection"""
        func_name = combo.get_active_text()
        if not func_name:
            return

        func = self.functions[func_name]

        # Update description
        doc = inspect.getdoc(func)
        if doc:
            first_line = doc.split('\n')[0]
            self.description_label.set_text(first_line)
        else:
            self.description_label.set_text("")

        # Clear parameters
        for child in self.params_grid.get_children():
            self.params_grid.remove(child)
        self.param_entries.clear()

        # Create parameter inputs
        sig = inspect.signature(func)

        if sig.parameters:
            row = 0
            for param_name, param in sig.parameters.items():
                type_name = self._get_type_name(param.annotation)

                label_text = f"{param_name} ({type_name}):" if type_name else f"{param_name}:"
                label = Gtk.Label(label=label_text)
                label.set_halign(Gtk.Align.END)
                self.params_grid.attach(label, 0, row, 1, 1)

                entry = Gtk.Entry()
                entry.set_hexpand(True)
                entry.set_width_chars(20)

                if param.annotation == bool:
                    entry.set_placeholder_text("true / false")

                if param.default != inspect.Parameter.empty:
                    entry.set_text(str(param.default))

                # Connect Enter key to view action
                entry.connect("activate", lambda w: self._on_view_clicked(None))
                entry.connect("changed", lambda w: self.emit('params-changed'))

                self.params_grid.attach(entry, 1, row, 1, 1)
                self.param_entries[param_name] = entry
                row += 1

            self.params_grid.show_all()
        else:
            no_params = Gtk.Label(label="This model requires no parameters")
            self.params_grid.attach(no_params, 0, 0, 2, 1)
            self.params_grid.show_all()

        self.view_button.set_sensitive(True)
        self._emit_status(f"Configure parameters for {func_name}")

    def _build_model(self) -> bool:
        """Build the current model. Returns True on success."""
        func_name = self.function_combo.get_active_text()
        if not func_name:
            self._emit_status("Please select a model type first")
            return False

        func = self.functions[func_name]
        sig = inspect.signature(func)

        # Collect parameters
        params = {}
        try:
            for param_name, param in sig.parameters.items():
                if param_name in self.param_entries:
                    value_str = self.param_entries[param_name].get_text()
                    has_default = param.default != inspect.Parameter.empty

                    converted = self._convert_value(
                        value_str,
                        param.annotation,
                        param_name,
                        has_default
                    )

                    if converted is not None:
                        params[param_name] = converted
                    elif not has_default:
                        params[param_name] = None

            # Build model
            self._emit_status(f"Building {func_name}...")

            # Process GTK events to update UI
            while Gtk.events_pending():
                Gtk.main_iteration()

            self.current_model = func(**params)
            self.current_build_params = params
            self.current_build_sig = sig

            self._emit_status(f"Model '{func_name}' built successfully")
            self.emit('model-built', self.current_model)
            return True

        except ValueError as e:
            self._emit_status(f"Input error: {str(e)}")
            return False
        except Exception as e:
            self._emit_status(f"Build error: {str(e)}")
            return False

    def _on_view_clicked(self, button) -> None:
        """Handle View Model button click"""
        if self._build_model():
            self.emit('view-requested', self.current_model)

    def _on_clear_clicked(self, button) -> None:
        """Handle Clear button click"""
        self.clear()

    def _emit_status(self, message: str) -> None:
        """Emit status-changed signal"""
        self.emit('status-changed', message)

    # Public API

    def clear(self) -> None:
        """Clear the form and reset state"""
        self.function_combo.set_active(-1)
        self.description_label.set_text("")

        for child in self.params_grid.get_children():
            self.params_grid.remove(child)
        self.param_entries.clear()

        self.current_model = None
        self.current_build_params = {}
        self.current_build_sig = None

        self.view_button.set_sensitive(False)
        self._emit_status("Select a model type to begin")

    def build_model(self) -> bool:
        """Public wrapper around _build_model(). Returns True on success."""
        return self._build_model()

    def set_sensitive_controls(self, sensitive: bool) -> None:
        """Enable or disable all controls"""
        has_model = self.function_combo.get_active_text() is not None
        self.function_combo.set_sensitive(sensitive)
        self.view_button.set_sensitive(sensitive and has_model)
        self.clear_button.set_sensitive(sensitive)
        self.params_grid.set_sensitive(sensitive)

    def get_selected_model_name(self) -> Optional[str]:
        """Get the currently selected model name"""
        return self.function_combo.get_active_text()

    def get_current_model(self):
        """Get the current built model (or None)"""
        return self.current_model

    def get_current_build_params(self) -> dict:
        """Get the parameters used for the last build"""
        return self.current_build_params

    def get_current_build_signature(self):
        """Get the inspect.Signature used for the last build (or None)"""
        return self.current_build_sig
