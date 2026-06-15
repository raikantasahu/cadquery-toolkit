"""
mesh_settings.py - Mesh settings dialog for configuring element size and type.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

# Custom dialog response: the user clicked "Pick…" to choose a cap face. The
# caller closes the dialog, runs the picker, and reopens with ``initial`` set.
RESPONSE_PICK_CAP = 1


def ask_mesh_settings(parent, cap_face_pid=None, initial=None):
    """Show a dialog for mesh generation settings.

    Args:
        parent: Parent GTK window.
        cap_face_pid: PersistentID of the cap face currently chosen for
            extruded hex, or None. Shown read-only.
        initial: Optional dict of prior field values to restore (returned by a
            previous call) so settings survive a "Pick…" round-trip.

    Returns:
        ``None`` if cancelled, otherwise a dict carrying every field value plus
        ``'_action'``: ``'ok'`` when accepted (with ``'extrusion'`` set to
        ``{'cap_face', 'num_layers'}`` when extruded hex is enabled, else None), or
        ``'pick_cap'`` when the user asked to pick a cap face.
    """
    initial = initial or {}
    dialog = Gtk.Dialog(title="Mesh Settings", transient_for=parent, modal=True)
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

    # Mesh type
    type_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    type_label = Gtk.Label(label="Mesh Type:")
    type_label.set_halign(Gtk.Align.START)
    type_label.set_width_chars(14)
    type_box.pack_start(type_label, False, False, 0)

    mesh_type_combo = Gtk.ComboBoxText()
    types = ["tet4", "tet10", "hex8", "hex20", "hex27"]
    for t in types:
        mesh_type_combo.append_text(t)
    mesh_type_combo.set_active(types.index(initial.get('mesh_type', 'tet4'))
                               if initial.get('mesh_type') in types else 0)
    type_box.pack_start(mesh_type_combo, True, True, 0)
    content.pack_start(type_box, False, False, 0)

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
    element_size_spin.set_value(initial.get('element_size', 5.0))
    element_size_spin.set_activates_default(True)
    size_box.pack_start(element_size_spin, True, True, 0)
    content.pack_start(size_box, False, False, 0)

    # Relative sag tolerance (optional curvature-driven refinement)
    sag_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    sag_label = Gtk.Label(label="Sag Tolerance:")
    sag_label.set_halign(Gtk.Align.START)
    sag_label.set_width_chars(14)
    sag_box.pack_start(sag_label, False, False, 0)

    sag_check = Gtk.CheckButton()
    sag_check.set_tooltip_text(
        "Refine curved faces so the chord sag stays below this fraction "
        "of the radius (S = δ/R). Leave unchecked to disable curvature "
        "refinement."
    )
    sag_check.set_active(bool(initial.get('sag_enabled', False)))
    sag_box.pack_start(sag_check, False, False, 0)

    sag_adjustment = Gtk.Adjustment(value=0.01, lower=0.0001, upper=1.0,
                                    step_increment=0.001, page_increment=0.01)
    sag_spin = Gtk.SpinButton()
    sag_spin.set_adjustment(sag_adjustment)
    sag_spin.set_digits(4)
    sag_spin.set_value(initial.get('sag_value', 0.01))
    sag_spin.set_sensitive(sag_check.get_active())
    sag_spin.set_activates_default(True)
    sag_box.pack_start(sag_spin, True, True, 0)
    sag_check.connect(
        "toggled", lambda btn: sag_spin.set_sensitive(btn.get_active()))
    content.pack_start(sag_box, False, False, 0)

    # --- Extruded hex8 -------------------------------------------------------
    content.pack_start(
        Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

    extrude_check = Gtk.CheckButton(label="Extruded hex (extrude a cap face)")
    extrude_check.set_tooltip_text(
        "Build structured hex8 by quad-meshing a cap face and extruding it "
        "through the thickness. Requires elementType hex8."
    )
    extrude_check.set_active(bool(initial.get('extrude_enabled', False)))
    content.pack_start(extrude_check, False, False, 0)

    cap_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    cap_label = Gtk.Label(label="Cap Face:")
    cap_label.set_halign(Gtk.Align.START)
    cap_label.set_width_chars(14)
    cap_box.pack_start(cap_label, False, False, 0)
    cap_value = Gtk.Label(label=(cap_face_pid or "(none)"))
    cap_value.set_halign(Gtk.Align.START)
    cap_box.pack_start(cap_value, True, True, 0)
    pick_btn = Gtk.Button.new_with_label("Pick…")
    pick_btn.set_tooltip_text("Pick the cap face in the 3D viewer")
    pick_btn.connect("clicked", lambda *_: dialog.response(RESPONSE_PICK_CAP))
    cap_box.pack_start(pick_btn, False, False, 0)
    content.pack_start(cap_box, False, False, 0)

    layers_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    layers_label = Gtk.Label(label="Layers:")
    layers_label.set_halign(Gtk.Align.START)
    layers_label.set_width_chars(14)
    layers_box.pack_start(layers_label, False, False, 0)
    layers_adjustment = Gtk.Adjustment(value=1, lower=1, upper=1000,
                                       step_increment=1, page_increment=5)
    layers_spin = Gtk.SpinButton()
    layers_spin.set_adjustment(layers_adjustment)
    layers_spin.set_digits(0)
    layers_spin.set_value(initial.get('num_layers', 1))
    layers_spin.set_activates_default(True)
    layers_box.pack_start(layers_spin, True, True, 0)
    content.pack_start(layers_box, False, False, 0)

    def _sync_extrude_sensitivity(*_):
        is_hex8 = mesh_type_combo.get_active_text() == "hex8"
        extrude_check.set_sensitive(is_hex8)
        enabled = is_hex8 and extrude_check.get_active()
        cap_box.set_sensitive(enabled)
        layers_box.set_sensitive(enabled)

    mesh_type_combo.connect("changed", _sync_extrude_sensitivity)
    extrude_check.connect("toggled", _sync_extrude_sensitivity)
    _sync_extrude_sensitivity()

    dialog.show_all()
    response = dialog.run()

    mesh_type = mesh_type_combo.get_active_text()
    sag_enabled = sag_check.get_active()
    extrude_enabled = mesh_type == "hex8" and extrude_check.get_active()
    values = {
        'mesh_type': mesh_type,
        'element_size': element_size_spin.get_value(),
        'sag_enabled': sag_enabled,
        'sag_value': sag_spin.get_value(),
        'relative_sag_tolerance': sag_spin.get_value() if sag_enabled else None,
        'extrude_enabled': extrude_enabled,
        'num_layers': int(layers_spin.get_value()),
    }
    dialog.destroy()

    if response == RESPONSE_PICK_CAP:
        values['_action'] = 'pick_cap'
        return values
    if response != Gtk.ResponseType.OK:
        return None
    values['_action'] = 'ok'
    values['extrusion'] = (
        {'cap_face': cap_face_pid, 'num_layers': values['num_layers']}
        if extrude_enabled else None
    )
    return values
