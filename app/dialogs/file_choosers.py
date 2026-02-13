"""
file_choosers.py - GTK file chooser dialog helpers.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


# Each filter entry is (display_name, [glob_patterns...]).
_MESH_FILTERS = [
    ("Gmsh files (*.msh)", ["*.msh"]),
    ("JSON files (*.json)", ["*.json"]),
]

_EXPORT_FILTERS = [
    ("JSON files (*.json)", ["*.json"]),
    ("STEP files (*.step, *.stp)", ["*.step", "*.stp"]),
]

_OPEN_FILTERS = [
    ("JSON files (*.json)", ["*.json"]),
    ("Gmsh mesh (*.msh)", ["*.msh"]),
    ("STEP files (*.step, *.stp)", ["*.step", "*.stp"]),
]


def _make_filter(name, patterns):
    """Create a Gtk.FileFilter from a name and list of glob patterns."""
    f = Gtk.FileFilter()
    f.set_name(name)
    for p in patterns:
        f.add_pattern(p)
    return f


def _run_dialog(title, parent, action, filters, default_name=None,
                swap_ext=False):
    """Run a GTK file chooser dialog.

    Args:
        title: Dialog window title.
        parent: Parent GTK window (or None).
        action: Gtk.FileChooserAction (OPEN or SAVE).
        filters: List of (name, [patterns]) tuples for per-type filters.
        default_name: Default filename for SAVE dialogs (with extension).
        swap_ext: If True, swap the file extension when the filter changes.

    Returns:
        (filename, selected_filter_index) if accepted.
        selected_filter_index is the index into *filters*, or None if
        the "All supported" filter was active.
        Returns (None, None) if cancelled.
    """
    is_save = (action == Gtk.FileChooserAction.SAVE)
    ok_stock = Gtk.STOCK_SAVE if is_save else Gtk.STOCK_OPEN

    dialog = Gtk.FileChooserDialog(
        title=title, parent=parent, action=action,
    )
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        ok_stock, Gtk.ResponseType.OK,
    )

    # Per-type filters
    gtk_filters = []
    for name, patterns in filters:
        f = _make_filter(name, patterns)
        dialog.add_filter(f)
        gtk_filters.append(f)

    # "All supported" catch-all filter
    all_filter = _make_filter(
        "All supported formats",
        [p for _, pats in filters for p in pats],
    )
    dialog.add_filter(all_filter)

    if is_save:
        dialog.set_do_overwrite_confirmation(True)
        if default_name:
            dialog.set_current_name(default_name)

    # Auto-swap extension when user switches filter
    if swap_ext:
        ext_for_filter = {}
        for f, (_, patterns) in zip(gtk_filters, filters):
            ext_for_filter[id(f)] = patterns[0].lstrip("*")

        def _on_filter_changed(dlg, _pspec):
            new_ext = ext_for_filter.get(id(dlg.get_filter()))
            if new_ext is None:
                return
            name = dlg.get_current_name() or ""
            stem, _, _ = name.rpartition(".")
            if stem:
                dlg.set_current_name(stem + new_ext)

        dialog.connect("notify::filter", _on_filter_changed)

    response = dialog.run()
    filename = dialog.get_filename()
    selected = dialog.get_filter()
    dialog.destroy()

    while Gtk.events_pending():
        Gtk.main_iteration()

    if response != Gtk.ResponseType.OK or not filename:
        return None, None

    # Map selected Gtk.FileFilter back to an index into filters
    idx = None
    for i, gf in enumerate(gtk_filters):
        if gf == selected:
            idx = i
            break

    return filename, idx


def _ensure_extension(filename, filters, selected_idx):
    """Append a default extension if the filename lacks a recognised one.

    Returns (filename, fmt) where fmt is the bare extension (e.g. "msh").
    """
    lower = filename.lower()

    # All known extensions from the filter specs
    all_exts = [p.lstrip("*") for _, pats in filters for p in pats]

    for ext in all_exts:
        if lower.endswith(ext):
            return filename, ext.lstrip(".")

    # No recognised extension — use the selected filter's default,
    # or the first filter if "All" was selected.
    idx = selected_idx if selected_idx is not None else 0
    ext = filters[idx][1][0].lstrip("*")
    return filename + ext, ext.lstrip(".")


# ── Public API ───────────────────────────────────────────────────────────────

def ask_open_file(parent=None):
    """Show an open dialog for model/mesh files.

    Args:
        parent: Optional parent GTK window.

    Returns:
        Filepath string, or None if cancelled.
    """
    filename, _ = _run_dialog(
        "Select a model or mesh file", parent,
        Gtk.FileChooserAction.OPEN, _OPEN_FILTERS,
    )
    return filename


def ask_save_mesh_file(parent, default_name):
    """Show a save dialog for mesh files (Gmsh or JSON).

    Args:
        parent: Parent GTK window.
        default_name: Default filename stem (without extension).

    Returns:
        Tuple of (filepath, format) where format is "msh" or "json",
        or None if cancelled.
    """
    filename, idx = _run_dialog(
        "Save Mesh File", parent,
        Gtk.FileChooserAction.SAVE, _MESH_FILTERS,
        default_name=f"{default_name}.msh", swap_ext=True,
    )
    if filename is None:
        return None
    return _ensure_extension(filename, _MESH_FILTERS, idx)


def ask_export_file(parent, default_name):
    """Show a save dialog for CAD model export (JSON or STEP).

    Args:
        parent: Parent GTK window.
        default_name: Default filename stem (without extension).

    Returns:
        Tuple of (filepath, format) where format is "step" or "json",
        or None if cancelled.
    """
    filename, idx = _run_dialog(
        "Export CAD Model", parent,
        Gtk.FileChooserAction.SAVE, _EXPORT_FILTERS,
        default_name=f"{default_name}.step",
    )
    if filename is None:
        return None
    return _ensure_extension(filename, _EXPORT_FILTERS, idx)
