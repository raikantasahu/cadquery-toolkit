"""T1.3 (Architecture Review) — app_gtk survives a missing dependency.

The GTK shell's deep import chain (app_core/converter/models all import cadquery)
used to crash at module load with a raw traceback, before the friendly
dependency dialog could run. With the core/UI split (T2.1), only app_gtk imports
gi, so the guard is local: a guarded import block must let the module load and
capture the error for main() to surface.
"""
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Subprocess: block cadquery via an import hook, then import app_gtk and confirm
# it loaded (class defined, no crash) with _IMPORT_ERROR captured.
_PROBE = r"""
import builtins
_real = builtins.__import__
def _fake(name, *a, **k):
    if name == "cadquery" or name.startswith("cadquery."):
        raise ImportError("No module named 'cadquery'")
    return _real(name, *a, **k)
builtins.__import__ = _fake

import app_gtk
assert app_gtk._IMPORT_ERROR is not None, "_IMPORT_ERROR not set"
assert hasattr(app_gtk, "CadQueryApp"), "module did not finish loading"
assert hasattr(app_gtk, "main") and hasattr(app_gtk, "_show_import_error")
print("OK")
"""


def test_app_gtk_loads_without_cadquery():
    res = subprocess.run([sys.executable, "-c", _PROBE],
                         cwd=APP_DIR, capture_output=True, text=True)
    assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]
    assert "OK" in res.stdout


def test_app_gtk_imports_normally_with_cadquery():
    res = subprocess.run(
        [sys.executable, "-c",
         "import app_gtk; assert app_gtk._IMPORT_ERROR is None; print('OK')"],
        cwd=APP_DIR, capture_output=True, text=True)
    assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]
    assert "OK" in res.stdout
