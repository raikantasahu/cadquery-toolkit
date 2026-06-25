"""Refactor C: the GTK-free viewer modules import without the GObject/Gtk layer.

The pure pyvista/numpy rendering+picking modules (style/picking/scene/viewers)
must be importable — and their pure logic testable — without pulling in the
``ModelViewer`` GObject controller or ``gi``. A lazy ``viewer/__init__`` (PEP 562)
makes that hold; this pins it so a future eager import in ``__init__`` regresses
loudly.
"""
import os
import subprocess
import sys

from viewer.picking import _next_auto_pick_number

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_pure_viewer_modules_do_not_pull_gtk():
    """Importing the GTK-free submodules leaves the GObject controller layer
    unimported — and since ``gi`` enters our code only through ``model_viewer``,
    that means no Gtk was pulled. Checked in a fresh interpreter so the assertion
    is about what *these* imports drag in, not what the pytest session loaded.
    (Asserting on ``model_viewer``/``mesh_viewer`` rather than scanning for ``gi``
    keeps it robust against a third-party dep importing gi for its own reasons.)"""
    code = (
        "import viewer.style, viewer.picking, viewer.scene, viewer.viewers\n"
        "import sys\n"
        "leaked = sorted(m for m in sys.modules\n"
        "                if m in ('viewer.model_viewer', 'viewer.mesh_viewer'))\n"
        "assert not leaked, leaked\n"
        "print('clean')\n"
    )
    r = subprocess.run([sys.executable, "-c", code],
                       cwd=APP_DIR, capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    assert "clean" in r.stdout


def test_model_viewer_resolves_lazily():
    """The package still exposes the public names — they just load on access."""
    code = (
        "import viewer\n"
        "assert 'viewer.model_viewer' not in __import__('sys').modules\n"
        "assert viewer.ModelViewer.__name__ == 'ModelViewer'\n"  # triggers lazy load
        "assert 'viewer.model_viewer' in __import__('sys').modules\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code],
                       cwd=APP_DIR, capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    assert "ok" in r.stdout


def test_next_auto_pick_number_pure_logic():
    """A pure picking helper, now unit-testable headlessly (no plotter/Gtk)."""
    assert _next_auto_pick_number([]) == 1
    assert _next_auto_pick_number([("F0", "Face 1"), ("F3", "Face 3")]) == 4
    assert _next_auto_pick_number([("V0", "Vertex 2")], prefix="Vertex") == 3
    # a user-renamed label doesn't match "{prefix} N" and is ignored
    assert _next_auto_pick_number([("F0", "Top surface")]) == 1
