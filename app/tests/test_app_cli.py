"""app_cli — headless registry-model CLI on AppCore (Core-UI-Separation P2).

End-to-end (subprocess): mesh a registry part, list its entities, and attach
PID-based owners on an assembly through to a saved MeshData JSON.
"""
import json
import os
import subprocess
import sys

import yaml

from helpers import cadmodeldata
from model.tessellation import create_polydatas_per_part

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(*args):
    return subprocess.run([sys.executable, "app_cli.py", *args],
                          cwd=APP_DIR, capture_output=True, text=True)


def test_mesh_registry_part(tmp_path):
    out = str(tmp_path / "h.msh")
    res = _run("hemisphere_sector", "-o", out)
    assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]
    assert os.path.getsize(out) > 0
    assert "Wrote" in res.stdout


def test_list_entities():
    res = _run("hemisphere_sector", "--list-entities")
    assert res.returncode == 0, res.stderr[-800:]
    assert "V0" in res.stdout and "centroid" in res.stdout


def test_pid_owners_on_assembly(fixtures, tmp_path):
    # PIDs are deterministic for a registry model, so compute the same ones the
    # CLI will see (fixtures' hertz is built from the same registry function).
    md = cadmodeldata(fixtures["hertz"]["model"])
    face_pid = vtx_pid = None
    for _label, pd in create_polydatas_per_part(md, with_face_index=True):
        fd = pd.field_data
        if face_pid is None and len(fd.get("face_pids", [])):
            face_pid = str(fd["face_pids"][0])
        if vtx_pid is None and len(fd.get("vertex_pids", [])):
            vtx_pid = str(fd["vertex_pids"][0])

    cfg = {
        "mesh": {"elementType": "tet4", "elementSize": 8.0},
        "owners": [
            {"kind": "face", "pid": face_pid, "label": "myface"},
            {"kind": "vertex", "pid": vtx_pid, "label": "myvertex"},
        ],
        "output": {"format": "meshdata_json"},
    }
    cfg_path = str(tmp_path / "cfg.yaml")
    with open(cfg_path, "w") as f:
        yaml.safe_dump(cfg, f)
    out = str(tmp_path / "out.json")

    res = _run("hertzian_sphere_on_block_quarter_symmetry",
               "--kind", "assembly", "-c", cfg_path, "-o", out)
    assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]

    data = json.load(open(out))
    conts = {c["owner"]: c for c in data["meshEntityContainers"]}
    assert "myface" in conts and conts["myface"]["nodeIds"]
    assert "myvertex" in conts and conts["myvertex"]["nodeIds"]
