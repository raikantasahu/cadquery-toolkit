"""
file_choosers.py - GTK file chooser dialog helpers for export and mesh saving.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


def ask_open_file(parent=None):
    """Show an open dialog for model/mesh files.

    Args:
        parent: Optional parent GTK window.

    Returns:
        Filepath string, or None if cancelled.
    """
    dialog = Gtk.FileChooserDialog(
        title="Select a model or mesh file",
        parent=parent,
        action=Gtk.FileChooserAction.OPEN,
    )
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
    )

    filter_all = Gtk.FileFilter()
    filter_all.set_name("All supported formats")
    for pattern in ("*.json", "*.msh", "*.step", "*.stp"):
        filter_all.add_pattern(pattern)
    dialog.add_filter(filter_all)

    for name, patterns in [
        ("JSON files (*.json)", ["*.json"]),
        ("Gmsh mesh (*.msh)", ["*.msh"]),
        ("STEP files (*.step, *.stp)", ["*.step", "*.stp"]),
    ]:
        f = Gtk.FileFilter()
        f.set_name(name)
        for p in patterns:
            f.add_pattern(p)
        dialog.add_filter(f)

    response = dialog.run()
    path = dialog.get_filename()
    dialog.destroy()

    # Drain pending GTK events so the dialog window fully closes
    while Gtk.events_pending():
        Gtk.main_iteration()

    if response != Gtk.ResponseType.OK or not path:
        return None
    return path


def ask_save_mesh_file(parent, default_name):
    """Show a save dialog for mesh files (Gmsh or JSON).

    Args:
        parent: Parent GTK window.
        default_name: Default filename stem (without extension).

    Returns:
        Tuple of (filepath, format) where format is "msh" or "json",
        or None if cancelled.
    """
    dialog = Gtk.FileChooserDialog(
        title="Save Mesh File",
        parent=parent,
        action=Gtk.FileChooserAction.SAVE
    )
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_SAVE, Gtk.ResponseType.OK
    )

    filter_msh = Gtk.FileFilter()
    filter_msh.set_name("Gmsh files (*.msh)")
    filter_msh.add_pattern("*.msh")
    dialog.add_filter(filter_msh)

    filter_json = Gtk.FileFilter()
    filter_json.set_name("JSON files (*.json)")
    filter_json.add_pattern("*.json")
    dialog.add_filter(filter_json)

    filter_all = Gtk.FileFilter()
    filter_all.set_name("All supported formats")
    filter_all.add_pattern("*.msh")
    filter_all.add_pattern("*.json")
    dialog.add_filter(filter_all)

    _EXT_FOR_FILTER = {id(filter_msh): ".msh", id(filter_json): ".json"}

    def _on_filter_changed(dlg, _pspec):
        new_ext = _EXT_FOR_FILTER.get(id(dlg.get_filter()))
        if new_ext is None:
            return
        name = dlg.get_current_name() or ""
        stem, _, _ = name.rpartition(".")
        if stem:
            dlg.set_current_name(stem + new_ext)

    dialog.connect("notify::filter", _on_filter_changed)

    dialog.set_do_overwrite_confirmation(True)
    dialog.set_current_name(f"{default_name}.msh")

    response = dialog.run()
    filename = dialog.get_filename()
    selected_filter = dialog.get_filter()
    dialog.destroy()

    if response != Gtk.ResponseType.OK or not filename:
        return None

    is_msh = filename.lower().endswith('.msh')
    is_json = filename.lower().endswith('.json')

    if not is_msh and not is_json:
        if selected_filter == filter_json:
            filename += '.json'
            is_json = True
        else:
            filename += '.msh'
            is_msh = True

    fmt = "json" if is_json else "msh"
    return (filename, fmt)


def ask_export_file(parent, default_name):
    """Show a save dialog for CAD model export (JSON or STEP).

    Args:
        parent: Parent GTK window.
        default_name: Default filename stem (without extension).

    Returns:
        Tuple of (filepath, format) where format is "step" or "json",
        or None if cancelled.
    """
    dialog = Gtk.FileChooserDialog(
        title="Export CAD Model",
        parent=parent,
        action=Gtk.FileChooserAction.SAVE
    )
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_SAVE, Gtk.ResponseType.OK
    )

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
    dialog.set_current_name(f"{default_name}.step")

    response = dialog.run()
    filename = dialog.get_filename()
    selected_filter = dialog.get_filter()
    dialog.destroy()

    if response != Gtk.ResponseType.OK or not filename:
        return None

    is_step = filename.lower().endswith(('.step', '.stp'))
    is_json = filename.lower().endswith('.json')

    if not is_step and not is_json:
        if selected_filter == filter_step:
            filename += '.step'
            is_step = True
        else:
            filename += '.json'
            is_json = True

    fmt = "step" if is_step else "json"
    return (filename, fmt)
