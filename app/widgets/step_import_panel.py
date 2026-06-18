"""StepImportPanel — a model source backed by an imported STEP file.

Implements the same duck-typed "model source" surface the GTK window drives for
ModelBuilder (get_current_model / get_selected_model_name /
get_current_build_params / get_current_build_signature / build_model / has_model
/ request_view / last_status_message, plus view-requested and status-changed
signals), so an imported STEP is used exactly like a built model. Adds a
`model-changed` signal, emitted on import, which the window wires to its
selection-invalidation. Holds one imported model at a time; re-import replaces.

See docs/plans/STEP-Import-GUI.md.
"""
import logging
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from importer import step_importer

logger = logging.getLogger(__name__)


class StepImportPanel(Gtk.Box):

    __gsignals__ = {
        # model handed to the viewer (mirrors ModelBuilder.view-requested)
        'view-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'status-changed': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # emitted on (re)import so the window drops stale picks/mesh
        'model-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._model = None
        self._name = None
        self.last_status_message = ""

        heading = Gtk.Label()
        heading.set_markup("<b>Imported STEP</b>")
        heading.set_halign(Gtk.Align.START)
        self.pack_start(heading, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._import_btn = Gtk.Button(label="Import STEP…")
        self._import_btn.connect('clicked', self._on_import_clicked)
        row.pack_start(self._import_btn, False, False, 0)
        self.pack_start(row, False, False, 0)

        self._file_label = Gtk.Label(label="No file imported")
        self._file_label.set_halign(Gtk.Align.START)
        self.pack_start(self._file_label, False, False, 0)

        # Bottom action row — matches the builder tabs: an accent "View Model"
        # button pushed to the bottom after a separator.
        self.pack_start(Gtk.Box(), True, True, 0)
        self.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 5)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(10)
        self._view_btn = Gtk.Button(label="View Model")
        self._view_btn.get_style_context().add_class("suggested-action")
        self._view_btn.set_sensitive(False)
        self._view_btn.set_size_request(150, -1)
        self._view_btn.connect('clicked', lambda _b: self.request_view())
        button_box.pack_start(self._view_btn, False, False, 0)
        self.pack_start(button_box, False, False, 0)

    # ---- model-source surface ----
    def get_current_model(self):
        return self._model

    def get_selected_model_name(self):
        return self._name

    def get_current_build_params(self) -> dict:
        return {}

    def get_current_build_signature(self):
        return None

    def build_model(self) -> bool:
        """No build step for an imported model; True iff one is loaded."""
        return self._model is not None

    def has_model(self) -> bool:
        return self._model is not None

    def request_view(self) -> None:
        if self._model is not None:
            self.emit('view-requested', self._model)

    def set_sensitive_controls(self, sensitive: bool) -> None:
        self._import_btn.set_sensitive(sensitive)
        self._view_btn.set_sensitive(sensitive and self._model is not None)

    # ---- import ----
    def _on_import_clicked(self, _button) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Import STEP", transient_for=self.get_toplevel(),
            action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        flt = Gtk.FileFilter()
        flt.set_name("STEP files")
        for pattern in ("*.step", "*.stp", "*.STEP", "*.STP"):
            flt.add_pattern(pattern)
        dialog.add_filter(flt)
        response = dialog.run()
        path = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if path:
            self._load(path)

    def _load(self, path: str) -> None:
        try:
            model = step_importer.read(path)
        except Exception as e:
            # Loud, named — never a silent failed import.
            logger.warning("failed to import STEP %s: %s", path, e,
                           exc_info=True)
            self._error(f"Could not import STEP file:\n{path}\n\n{e}")
            return
        self._model = model
        self._name = Path(path).stem
        self._file_label.set_text(f"Imported: {Path(path).name}")
        self._view_btn.set_sensitive(True)
        self.last_status_message = f"Imported {Path(path).name}"
        self.emit('status-changed', self.last_status_message)
        self.emit('model-changed')

    def _error(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self.get_toplevel(), flags=0,
            message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text="Import Error")
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()
