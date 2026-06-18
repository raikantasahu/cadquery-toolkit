"""
mesh_settings.py - Mesh settings dialog for configuring element size and type.

Tabbed layout: General (type / size / sag), Refinement (a table of local/contact
refinement regions), and Extruded Hex. The Refinement tab holds a list so the
mesher can be given several regions at once; per-part controls will later become
their own tab (see docs/plans/Part-Specific-Mesh-Controls.md).
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk

# Custom dialog responses. The caller closes the dialog, runs a picker, and
# reopens with ``initial`` + ``refinements`` set so other settings survive the
# round-trip.
RESPONSE_PICK_CAP = 1        # pick the extruded-hex cap face
RESPONSE_ADD_LOCAL = 2       # pick a vertex, add a local refinement region
RESPONSE_ADD_CONTACT = 3     # pick a vertex, add a contact refinement region

# Refinement-region table columns.
_COL_SCOPE, _COL_VERTEX, _COL_FINE, _COL_RADIUS, _COL_LABEL = range(5)


def ask_mesh_settings(parent, cap_face_pid=None, refinements=None, initial=None):
    """Show a dialog for mesh generation settings.

    Args:
        parent: Parent GTK window.
        cap_face_pid: PersistentID of the cap face for extruded hex, or None.
        refinements: List of refinement-region dicts to populate the table,
            each ``{scope, vertex_pid, vertex_label, fine_size, radius}``.
        initial: Optional dict of prior non-refinement field values to restore
            so settings survive a "Pick…" / "Add…" round-trip.

    Returns:
        ``None`` if cancelled, otherwise a dict of field values plus
        ``'refinements'`` (the table's regions) and ``'_action'``: ``'ok'``,
        ``'pick_cap'``, ``'add_local'``, or ``'add_contact'``.
    """
    initial = initial or {}
    refinements = refinements or []
    dialog = Gtk.Dialog(title="Create Mesh", transient_for=parent, modal=True)
    dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
    dialog.add_button("Create Mesh", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.set_default_size(480, 380)

    content = dialog.get_content_area()
    content.set_spacing(8)
    content.set_margin_start(10)
    content.set_margin_end(10)
    content.set_margin_top(8)
    content.set_margin_bottom(6)

    heading = Gtk.Label()
    heading.set_markup("<b>Mesh Settings</b>")
    heading.set_halign(Gtk.Align.START)
    content.pack_start(heading, False, False, 0)

    notebook = Gtk.Notebook()
    content.pack_start(notebook, True, True, 0)

    def _page(title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        notebook.append_page(box, Gtk.Label(label=title))
        return box

    def _labeled_row(parent_box, label_text):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl = Gtk.Label(label=label_text)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_width_chars(14)
        row.pack_start(lbl, False, False, 0)
        parent_box.pack_start(row, False, False, 0)
        return row

    # ----- General tab -------------------------------------------------------
    general = _page("General")

    type_row = _labeled_row(general, "Mesh Type:")
    mesh_type_combo = Gtk.ComboBoxText()
    types = ["tet4", "tet10", "hex8", "hex20", "hex27"]
    for t in types:
        mesh_type_combo.append_text(t)
    mesh_type_combo.set_active(types.index(initial.get('mesh_type', 'tet4'))
                               if initial.get('mesh_type') in types else 0)
    type_row.pack_start(mesh_type_combo, True, True, 0)

    size_row = _labeled_row(general, "Element Size:")
    element_size_spin = Gtk.SpinButton()
    element_size_spin.set_adjustment(Gtk.Adjustment(
        value=5.0, lower=0.01, upper=1000.0,
        step_increment=0.5, page_increment=5.0))
    element_size_spin.set_digits(2)
    element_size_spin.set_value(initial.get('element_size', 5.0))
    element_size_spin.set_activates_default(True)
    size_row.pack_start(element_size_spin, True, True, 0)

    sag_row = _labeled_row(general, "Sag Tolerance:")
    sag_check = Gtk.CheckButton()
    sag_check.set_tooltip_text(
        "Refine curved faces so the chord sag stays below this fraction "
        "of the radius (S = δ/R). Leave unchecked to disable.")
    sag_check.set_active(bool(initial.get('sag_enabled', False)))
    sag_row.pack_start(sag_check, False, False, 0)
    sag_spin = Gtk.SpinButton()
    sag_spin.set_adjustment(Gtk.Adjustment(
        value=0.01, lower=0.0001, upper=1.0,
        step_increment=0.001, page_increment=0.01))
    sag_spin.set_digits(4)
    sag_spin.set_value(initial.get('sag_value', 0.01))
    sag_spin.set_sensitive(sag_check.get_active())
    sag_spin.set_activates_default(True)
    sag_row.pack_start(sag_spin, True, True, 0)
    sag_check.connect(
        "toggled", lambda btn: sag_spin.set_sensitive(btn.get_active()))

    # ----- Refinement tab ----------------------------------------------------
    refine_page = _page("Refinement")
    hint = Gtk.Label()
    hint.set_markup(
        "<small>Fine mesh near a vertex, coarse away. Add regions, then edit "
        "Fine Size / Refine Radius inline.</small>")
    hint.set_halign(Gtk.Align.START)
    hint.set_line_wrap(True)
    refine_page.pack_start(hint, False, False, 0)

    # scope, vertex_pid, fine, radius (all str), vertex_label
    store = Gtk.ListStore(str, str, str, str, str)
    for r in refinements:
        store.append([
            r.get('scope', ''), r.get('vertex_pid', ''),
            f"{float(r.get('fine_size', 0.5)):g}",
            f"{float(r.get('radius', 2.0)):g}",
            r.get('vertex_label', ''),
        ])

    tree = Gtk.TreeView(model=store)
    tree.set_tooltip_text(
        "Each row refines around one picked vertex. 'local' refines only that "
        "part; 'contact' refines every part meeting at the vertex.")

    # Track an in-progress cell edit so a click on OK / Add (which doesn't move
    # focus out of the entry, so GTK emits 'editing-canceled' not 'edited') still
    # commits the typed value. Mirrors the rename dialog's fix.
    active_edit = {}

    def _set_cell(path, col, text):
        try:
            if float(text) > 0:
                store[path][col] = f"{float(text):g}"
        except (TypeError, ValueError):
            pass  # reject non-numeric / non-positive; keep prior value

    def _flush_edit():
        if {'path', 'col', 'text'} <= active_edit.keys():
            _set_cell(active_edit['path'], active_edit['col'],
                      active_edit['text'])
        active_edit.clear()

    def _on_editable_key(_editable, event):
        if event.keyval == Gdk.KEY_Escape:
            active_edit['escaped'] = True
        return False

    def _attach_editable(renderer, col):
        renderer.set_property("editable", True)

        def _on_start(_r, editable, path):
            active_edit.clear()
            active_edit.update(col=col, path=path, text=editable.get_text())
            editable.connect(
                "changed",
                lambda e: active_edit.__setitem__('text', e.get_text()))
            editable.connect("key-press-event", _on_editable_key)

        def _on_edited(_r, path, text):
            _set_cell(path, col, text)
            active_edit.clear()

        def _on_canceled(_r):
            if active_edit.get('escaped'):
                active_edit.clear()
            else:
                _flush_edit()

        renderer.connect("editing-started", _on_start)
        renderer.connect("edited", _on_edited)
        renderer.connect("editing-canceled", _on_canceled)

    for title, col, editable in (
            ("Scope", _COL_SCOPE, False),
            ("Vertex", _COL_VERTEX, False),
            ("Fine Size", _COL_FINE, True),
            ("Refine Radius", _COL_RADIUS, True)):
        renderer = Gtk.CellRendererText()
        if editable:
            _attach_editable(renderer, col)
        column = Gtk.TreeViewColumn(title, renderer, text=col)
        column.set_expand(True)
        tree.append_column(column)

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroller.set_hexpand(True)
    scroller.set_vexpand(True)
    scroller.add(tree)
    refine_page.pack_start(scroller, True, True, 0)

    button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    add_local_btn = Gtk.Button.new_with_label("Add Local…")
    add_local_btn.set_tooltip_text("Pick a vertex; refine only its part")
    add_local_btn.connect(
        "clicked", lambda *_: dialog.response(RESPONSE_ADD_LOCAL))
    add_contact_btn = Gtk.Button.new_with_label("Add Contact…")
    add_contact_btn.set_tooltip_text(
        "Pick a vertex; refine all parts meeting there")
    add_contact_btn.connect(
        "clicked", lambda *_: dialog.response(RESPONSE_ADD_CONTACT))
    remove_btn = Gtk.Button.new_with_label("Remove")

    def _on_remove(_btn):
        _, treeiter = tree.get_selection().get_selected()
        if treeiter is not None:
            store.remove(treeiter)

    remove_btn.connect("clicked", _on_remove)
    button_row.pack_start(add_local_btn, False, False, 0)
    button_row.pack_start(add_contact_btn, False, False, 0)
    button_row.pack_start(remove_btn, False, False, 0)
    refine_page.pack_start(button_row, False, False, 0)

    # ----- Extruded Hex tab --------------------------------------------------
    hex_page = _page("Extruded Hex")
    extrude_check = Gtk.CheckButton(label="Extruded hex (extrude a cap face)")
    extrude_check.set_tooltip_text(
        "Build structured hex8 by quad-meshing a cap face and extruding it "
        "through the thickness. Requires elementType hex8; mutually exclusive "
        "with refinement.")
    extrude_check.set_active(bool(initial.get('extrude_enabled', False)))
    hex_page.pack_start(extrude_check, False, False, 0)

    cap_box = _labeled_row(hex_page, "Cap Face:")
    cap_value = Gtk.Label(label=(cap_face_pid or "(none)"))
    cap_value.set_halign(Gtk.Align.START)
    cap_box.pack_start(cap_value, True, True, 0)
    pick_btn = Gtk.Button.new_with_label("Pick…")
    pick_btn.set_tooltip_text("Pick the cap face in the 3D viewer")
    pick_btn.connect("clicked", lambda *_: dialog.response(RESPONSE_PICK_CAP))
    cap_box.pack_start(pick_btn, False, False, 0)

    layers_box = _labeled_row(hex_page, "Layers:")
    layers_spin = Gtk.SpinButton()
    layers_spin.set_adjustment(Gtk.Adjustment(
        value=1, lower=1, upper=1000, step_increment=1, page_increment=5))
    layers_spin.set_digits(0)
    layers_spin.set_value(initial.get('num_layers', 1))
    layers_spin.set_activates_default(True)
    layers_box.pack_start(layers_spin, True, True, 0)

    def _sync_sensitivity(*_):
        is_hex8 = mesh_type_combo.get_active_text() == "hex8"
        extrude_check.set_sensitive(is_hex8)
        extruding = is_hex8 and extrude_check.get_active()
        cap_box.set_sensitive(extruding)
        layers_box.set_sensitive(extruding)
        # Refinement and extruded hex are mutually exclusive.
        refine_page.set_sensitive(not extruding)

    mesh_type_combo.connect("changed", _sync_sensitivity)
    extrude_check.connect("toggled", _sync_sensitivity)
    _sync_sensitivity()

    dialog.show_all()
    # Reopen on the tab the user was working in (survives a Pick…/Add… round-trip
    # and is restored next invocation), not always General.
    restore_tab = initial.get('active_tab', 0)
    notebook.set_current_page(restore_tab if restore_tab and restore_tab > 0
                              else 0)
    response = dialog.run()

    mesh_type = mesh_type_combo.get_active_text()
    sag_enabled = sag_check.get_active()
    extrude_enabled = mesh_type == "hex8" and extrude_check.get_active()

    # Serialize the region table (flush any in-progress cell edit first).
    _flush_edit()
    regions = []
    for row in store:
        try:
            fine = float(row[_COL_FINE])
            radius = float(row[_COL_RADIUS])
        except (TypeError, ValueError):
            continue
        regions.append({
            'scope': row[_COL_SCOPE], 'vertex_pid': row[_COL_VERTEX],
            'vertex_label': row[_COL_LABEL], 'fine_size': fine,
            'radius': radius,
        })

    values = {
        'mesh_type': mesh_type,
        'element_size': element_size_spin.get_value(),
        'sag_enabled': sag_enabled,
        'sag_value': sag_spin.get_value(),
        'relative_sag_tolerance': sag_spin.get_value() if sag_enabled else None,
        'extrude_enabled': extrude_enabled,
        'num_layers': int(layers_spin.get_value()),
        # Refinement is suppressed while extruding (mutually exclusive), but the
        # rows are kept so they survive a toggle / round-trip.
        'refinements': [] if extrude_enabled else regions,
        '_all_refinements': regions,
        'active_tab': notebook.get_current_page(),
    }
    dialog.destroy()

    if response == RESPONSE_PICK_CAP:
        values['_action'] = 'pick_cap'
        return values
    if response == RESPONSE_ADD_LOCAL:
        values['_action'] = 'add_local'
        return values
    if response == RESPONSE_ADD_CONTACT:
        values['_action'] = 'add_contact'
        return values
    if response != Gtk.ResponseType.OK:
        return None
    values['_action'] = 'ok'
    values['extrusion'] = (
        {'cap_face': cap_face_pid, 'num_layers': values['num_layers']}
        if extrude_enabled else None
    )
    return values
