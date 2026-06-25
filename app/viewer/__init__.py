"""viewer - CAD model viewer package.

Lazy public API (PEP 562): importing the ``viewer`` package — or any of its
GTK-free submodules (``style``/``picking``/``scene``/``viewers``) — must not pull
in the GObject/Gtk stack. ``ModelViewer`` and ``mesh_viewer.show_mesh`` sit behind
a ``gi`` import, so they are resolved only when actually accessed. This lets the
pure pyvista/numpy rendering+picking logic be imported and unit-tested headlessly
(no display, no Gtk), per the separate-core-from-UI convention.
"""
import importlib

__all__ = ['ModelViewer', 'show_pyvista', 'show_mesh']

# name -> (submodule, attribute). show_pyvista is itself GTK-free (it lives in
# .viewers), but is exposed here lazily too so a bare ``import viewer`` stays cheap.
_LAZY = {
    'ModelViewer': ('.model_viewer', 'ModelViewer'),
    'show_pyvista': ('.viewers', 'show_pyvista'),
    'show_mesh': ('.mesh_viewer', 'show_mesh'),
}


def __getattr__(name):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(target[0], __name__)
    attr = getattr(module, target[1])
    globals()[name] = attr  # cache: subsequent access skips __getattr__
    return attr


def __dir__():
    return sorted(__all__)
