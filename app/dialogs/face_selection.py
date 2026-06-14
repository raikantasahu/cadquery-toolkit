"""
face_selection.py - Dialog for editing a picked-entity list.

Lets the user rename or remove entries from the list returned by the
model viewer's face or vertex picker, before they flow into a MeshData
save as MeshEntityContainers. The dialog is entity-agnostic — it edits
``[(persistent_id, label)]`` rows; only the window title differs.
"""

from typing import List, Optional, Tuple

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


def edit_face_selection(
    parent: Optional[Gtk.Window],
    picks: List[Tuple[str, str]],
    title: str = "Edit Face Selection",
) -> Optional[List[Tuple[str, str]]]:
    """Show a dialog to rename or remove entries in a picked-entity list.

    Args:
        parent: Parent GTK window.
        picks: Current picks as ``[(persistent_id, owner_label), ...]``.
        title: Window title (e.g. ``"Edit Vertex Selection"`` when editing
            vertex picks). The dialog is otherwise entity-agnostic.

    Returns:
        The edited list on OK, or ``None`` on cancel.
    """
    dialog = Gtk.Dialog(
        title=title, transient_for=parent, flags=0,
    )
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OK, Gtk.ResponseType.OK,
    )
    dialog.set_default_size(420, 320)

    # Columns: persistent_id (read-only), label (editable).
    store = Gtk.ListStore(str, str)
    for pid, label in picks:
        store.append([pid, label])

    tree = Gtk.TreeView(model=store)

    pid_renderer = Gtk.CellRendererText()
    pid_col = Gtk.TreeViewColumn("Persistent ID", pid_renderer, text=0)
    pid_col.set_min_width(120)
    tree.append_column(pid_col)

    label_renderer = Gtk.CellRendererText()
    label_renderer.set_property("editable", True)

    def _on_label_edited(_renderer, path, new_text):
        # Strip but allow empty rows; we drop empties on OK.
        store[path][1] = new_text.strip()

    label_renderer.connect("edited", _on_label_edited)
    label_col = Gtk.TreeViewColumn("Owner label", label_renderer, text=1)
    label_col.set_expand(True)
    tree.append_column(label_col)

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroller.set_hexpand(True)
    scroller.set_vexpand(True)
    scroller.add(tree)

    remove_btn = Gtk.Button.new_with_label("Remove selected")
    clear_btn = Gtk.Button.new_with_label("Remove all")

    def _on_remove(_btn):
        selection = tree.get_selection()
        _, treeiter = selection.get_selected()
        if treeiter is not None:
            store.remove(treeiter)

    def _on_clear(_btn):
        store.clear()

    remove_btn.connect("clicked", _on_remove)
    clear_btn.connect("clicked", _on_clear)

    button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    button_row.pack_start(remove_btn, False, False, 0)
    button_row.pack_start(clear_btn, False, False, 0)

    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    body.set_margin_top(10)
    body.set_margin_bottom(10)
    body.set_margin_start(10)
    body.set_margin_end(10)
    body.pack_start(scroller, True, True, 0)
    body.pack_start(button_row, False, False, 0)

    dialog.get_content_area().add(body)
    dialog.show_all()

    response = dialog.run()
    edited: List[Tuple[str, str]] = []
    if response == Gtk.ResponseType.OK:
        for row in store:
            pid, label = row[0], row[1]
            if label:
                edited.append((pid, label))
    dialog.destroy()

    while Gtk.events_pending():
        Gtk.main_iteration()

    return edited if response == Gtk.ResponseType.OK else None
