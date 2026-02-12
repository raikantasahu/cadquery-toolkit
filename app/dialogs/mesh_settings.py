"""
mesh_settings.py - Mesh settings dialog for configuring element size and type.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


def ask_mesh_settings(parent):
    """Show a dialog for mesh generation settings.

    Args:
        parent: Parent GTK window.

    Returns:
        Dictionary with 'element_size' (float) and 'mesh_type' (str),
        or None if cancelled.
    """
    dialog = Gtk.Dialog(
        title="Mesh Settings",
        transient_for=parent,
        modal=True,
    )
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OK, Gtk.ResponseType.OK,
    )
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.set_resizable(False)

    content = dialog.get_content_area()
    content.set_spacing(10)
    content.set_margin_start(15)
    content.set_margin_end(15)
    content.set_margin_top(10)
    content.set_margin_bottom(5)

    # Element size
    size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    size_label = Gtk.Label(label="Element Size:")
    size_label.set_halign(Gtk.Align.START)
    size_label.set_width_chars(14)
    size_box.pack_start(size_label, False, False, 0)

    adjustment = Gtk.Adjustment(value=5.0, lower=0.01, upper=1000.0,
                                step_increment=0.5, page_increment=5.0)
    element_size_spin = Gtk.SpinButton()
    element_size_spin.set_adjustment(adjustment)
    element_size_spin.set_digits(2)
    element_size_spin.set_value(5.0)
    element_size_spin.set_activates_default(True)
    size_box.pack_start(element_size_spin, True, True, 0)

    content.pack_start(size_box, False, False, 0)

    # Mesh type
    type_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    type_label = Gtk.Label(label="Mesh Type:")
    type_label.set_halign(Gtk.Align.START)
    type_label.set_width_chars(14)
    type_box.pack_start(type_label, False, False, 0)

    mesh_type_combo = Gtk.ComboBoxText()
    mesh_type_combo.append_text("tet4")
    mesh_type_combo.append_text("hex8")
    mesh_type_combo.append_text("mixed")
    mesh_type_combo.set_active(0)
    type_box.pack_start(mesh_type_combo, True, True, 0)

    content.pack_start(type_box, False, False, 0)

    dialog.show_all()
    response = dialog.run()

    element_size = element_size_spin.get_value()
    mesh_type = mesh_type_combo.get_active_text()
    dialog.destroy()

    if response != Gtk.ResponseType.OK:
        return None

    return {
        'element_size': element_size,
        'mesh_type': mesh_type,
    }
