"""Edge-MeshEntityContainer (F2) — picked edges export as MeshEntityContainers.

Headless end-to-end: an edge owner — specified via the registry CLI (`E#` PID),
the GUI bridge (AppCore, the GUI's save path minus the window), or a foreign STEP
(by samples) — becomes a `meshEntityContainer` in the saved MeshData. The contact
line is coincident on both bodies, so it yields one container per body.

See docs/plans/Edge-MeshEntityContainer/.
"""
import json
import logging
import os
import subprocess
import sys

import yaml

from app_core import AppCore
from helpers import cadmodeldata
from models.assemblies import get_assembly_function
from models.parts import get_part_function
from model.tessellation import anchor_for_pick, create_polydatas_per_part

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = "hertzian_cylinder_on_block_quarter_symmetry"
_RADIUS = 10.0  # default cylinder_radius -> contact line at x=0, z=-RADIUS


def _cyl_model():
    return get_assembly_function(_MODEL)()


def _contact_edge_pids(md):
    """The E# of the contact-line edge on each body (samples all at x=0, z=-R)."""
    pids = []
    for _label, pd in create_polydatas_per_part(md, with_face_index=True):
        for pid in (str(v) for v in pd.field_data.get("edge_pids", [])):
            s = anchor_for_pick(md, pid)["samples"]
            if all(abs(x) < 1e-6 and abs(z + _RADIUS) < 1e-6 for (x, _y, z) in s):
                pids.append(pid)
    return pids


def _containers(path, owner):
    data = json.load(open(path))
    return [c for c in data["meshEntityContainers"] if c["owner"] == owner]


def _run(script, *args):
    return subprocess.run([sys.executable, script, *args],
                          cwd=APP_DIR, capture_output=True, text=True)


# ── T1 — registry CLI: edge owner -> container (keystone) ───────────────────

def test_registry_cli_edge_owner_exports_container(tmp_path):
    epids = _contact_edge_pids(cadmodeldata(_cyl_model()))
    assert epids, "contact-line edge must be surfaced"
    cfg = {
        "mesh": {"elementType": "tet4", "elementSize": 8.0},
        "owners": [{"kind": "edge", "pid": epids[0], "label": "contact-line"}],
        "output": {"format": "meshdata_json"},
    }
    cfg_path = str(tmp_path / "cfg.yaml")
    yaml.safe_dump(cfg, open(cfg_path, "w"))
    out = str(tmp_path / "out.json")
    res = _run("app_cli.py", _MODEL, "--kind", "assembly", "-c", cfg_path,
               "-o", out)
    assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]
    conts = _containers(out, "contact-line")
    assert conts and all(c["nodeIds"] for c in conts)


# ── T2 — GUI bridge (headless): set_edge_owners -> container ────────────────

def test_gui_bridge_edge_owner_exports_container(tmp_path):
    core = AppCore()
    core.set_model(_cyl_model(), "cylblock")
    epid = _contact_edge_pids(core.model_data())[0]
    core.set_edge_owners([(epid, "contact-line")])
    core.mesh({"mesh_type": "tet4", "element_size": 8.0})
    out = str(tmp_path / "out.json")
    core.save_mesh(out, "meshdata_json")
    core.finalize()
    conts = _containers(out, "contact-line")
    assert conts and all(c["nodeIds"] for c in conts)


# ── T3 — coincident contact edge -> one container per body ──────────────────

def test_contact_edge_yields_one_container_per_body(tmp_path):
    core = AppCore()
    core.set_model(_cyl_model(), "cylblock")
    epid = _contact_edge_pids(core.model_data())[0]
    core.set_edge_owners([(epid, "contact-line")])
    core.mesh({"mesh_type": "tet4", "element_size": 8.0})
    out = str(tmp_path / "out.json")
    core.save_mesh(out, "meshdata_json")
    core.finalize()
    conts = _containers(out, "contact-line")
    assert len(conts) == 2, [c["containerKey"] for c in conts]  # one per body
    assert all(c["nodeIds"] for c in conts)
    # the two bodies' coincident-but-separate curves have distinct node sets
    assert conts[0]["nodeIds"] != conts[1]["nodeIds"]


# ── T4 — independence + non-destructive (use the single-body box) ───────────

def test_owner_independence_and_nondestructive(tmp_path):
    box = get_part_function("box")()
    fpid = vpid = epid = None
    for _label, pd in create_polydatas_per_part(cadmodeldata(box),
                                                 with_face_index=True):
        fd = pd.field_data
        fpid = str(fd["face_pids"][0])
        vpid = str(fd["vertex_pids"][0])
        epid = str(fd["edge_pids"][0])

    def _mesh_save(owners, name):
        core = AppCore()
        core.set_model(box, "box")
        core.set_face_owners([(fpid, "myface")] if owners else [])
        core.set_vertex_owners([(vpid, "myvertex")] if owners else [])
        core.set_edge_owners([(epid, "myedge")] if owners else [])
        core.mesh({"mesh_type": "tet4", "element_size": 6.0})
        path = str(tmp_path / name)
        core.save_mesh(path, "meshdata_json")
        core.finalize()
        return json.load(open(path))

    with_o = _mesh_save(True, "with.json")
    without_o = _mesh_save(False, "without.json")

    labels = {c["owner"] for c in with_o["meshEntityContainers"]}
    assert {"myface", "myvertex", "myedge"} <= labels
    # owners add only containers — fragments and node count unchanged
    assert without_o["meshEntityContainers"] == []
    assert len(with_o["nodes"]) == len(without_o["nodes"])
    assert len(with_o["fragments"]) == len(without_o["fragments"])


# ── T5 — foreign STEP edge owner still works (regression) ───────────────────

def test_foreign_step_edge_owner_exports_container(fixtures, tmp_path):
    step = fixtures["cylhertz"]["step"]
    cfg = {
        "mesh": {"elementType": "tet4", "elementSize": 8.0},
        "owners": [{"kind": "edge",
                    "samples": [[0.0, 0.0, -_RADIUS], [0.0, 20.0, -_RADIUS]],
                    "owner": "contact-line"}],
        "output": {"format": "json"},   # mesh_step_model's MeshData JSON key
    }
    cfg_path = str(tmp_path / "cfg.yaml")
    yaml.safe_dump(cfg, open(cfg_path, "w"))
    out = str(tmp_path / "out.json")
    res = _run("mesh_step_model.py", step, cfg_path, "-o", out)
    assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]
    conts = _containers(out, "contact-line")
    assert conts and all(c["nodeIds"] for c in conts)


# ── T6 — loud on an unresolved owner (R5 mode b) ────────────────────────────

def test_loud_on_unresolved_edge_owner(tmp_path, caplog):
    core = AppCore()
    core.set_model(_cyl_model(), "cylblock")
    core.set_edge_owners([("E9999", "ghost")])   # stale/unknown E#
    core.mesh({"mesh_type": "tet4", "element_size": 8.0})
    out = str(tmp_path / "out.json")
    with caplog.at_level(logging.WARNING):
        core.save_mesh(out, "meshdata_json")     # selection_anchors warns here
    core.finalize()
    assert "ghost" in caplog.text                # loud, names the owner
    assert _containers(out, "ghost") == []       # dropped, not crashed
