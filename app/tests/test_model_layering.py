"""Layering guard — the CADModelData schema must stay dependency-light.

`model/tessellation.py` pulls in pyvista/vtk, but it lives under `model/` only
as a sibling module and is deliberately NOT re-exported from `model/__init__.py`.
Importing the schema (`from model import CADModelData`) must therefore not drag
pyvista/vtk into the process, so converter/exporters that depend on the schema
stay light. A fresh subprocess is used so prior test imports don't mask it.
"""
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = r"""
import sys
from model import CADModelData          # schema only
heavy = [m for m in ("pyvista", "vtk") if m in sys.modules]
assert not heavy, f"importing model schema pulled in: {heavy}"
# the helpers are still reachable from their own module (just not via model/)
from model.tessellation import create_polydatas_per_part, anchor_for_pick  # noqa
print("OK")
"""


def test_schema_import_is_pyvista_free():
    res = subprocess.run([sys.executable, "-c", _PROBE],
                         cwd=APP_DIR, capture_output=True, text=True)
    assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]
    assert "OK" in res.stdout
