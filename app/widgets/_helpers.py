"""Shared GTK widget helpers for the model-source tabs."""
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


def make_view_model_button(on_clicked) -> Gtk.Button:
    """The accent "View Model" button shared by the model-source tabs.

    Built disabled (no model yet); the caller packs it into its own action row
    and toggles sensitivity. Keeps the builder and STEP-import tabs visually
    identical without a shared base class (GObject metaclass forbids one).
    ``on_clicked`` receives the button (GTK ``clicked`` signature).
    """
    button = Gtk.Button(label="View Model")
    button.get_style_context().add_class("suggested-action")
    button.set_sensitive(False)
    button.set_size_request(150, -1)
    button.connect("clicked", on_clicked)
    return button
