"""AppCore — GTK-free controller (Core-UI-Separation Phase 1).

Exercises the headless core the GUI/CLI will share: model build/convert, anchor
resolution, owner wiring through to a saved mesh, and model export.
"""
import json
import os

import pytest

from app_core import AppCore, AppError
from helpers import cad_counts
from model.tessellation import create_polydatas_per_part


def _first_pids(md):
    face_pid = vtx_pid = None
    for _label, pd in create_polydatas_per_part(md, with_face_index=True):
        fd = pd.field_data
        if face_pid is None and len(fd.get("face_pids", [])):
            face_pid = str(fd["face_pids"][0])
        if vtx_pid is None and len(fd.get("vertex_pids", [])):
            vtx_pid = str(fd["vertex_pids"][0])
    return face_pid, vtx_pid


def test_set_model_then_model_data(fixtures):
    core = AppCore()
    core.set_model(fixtures["hertz"]["model"], "hertz")
    assert all(c > 0 for c in cad_counts(core.model_data()))
    # cached: second call returns the same object
    assert core.model_data() is core.model_data()


def test_set_model_short_circuits_on_unchanged_reset(fixtures):
    """Re-setting the SAME model object (the imported-STEP panel does this on
    every menu action) preserves the CADModelData cache; a different model or a
    changed name invalidates it."""
    core = AppCore()
    model = fixtures["hertz"]["model"]
    core.set_model(model, "hertz")
    md = core.model_data()

    # Same object + same name: cache survives (no rebuild).
    core.set_model(model, "hertz")
    assert core.model_data() is md

    # A changed name is a real change: cache is rebuilt.
    core.set_model(model, "renamed")
    assert core.model_data() is not md

    # A different model object: cache is rebuilt.
    other = fixtures["twocubes"]["model"]
    rebuilt = core.model_data()
    core.set_model(other, "twocubes")
    assert core.model_data() is not rebuilt


def test_build_model_from_registry():
    core = AppCore()
    core.build_model("hemisphere_sector", {}, kind="part")
    assert core.model_data()["models"]


def test_no_model_raises():
    core = AppCore()
    with pytest.raises(AppError):
        core.model_data()
    with pytest.raises(AppError):
        core.mesh({"mesh_type": "tet4", "element_size": 8.0})


def test_anchors_resolve(fixtures):
    core = AppCore()
    core.set_model(fixtures["hertz"]["model"], "hertz")
    face_pid, vtx_pid = _first_pids(core.model_data())
    assert core.face_anchor(face_pid)["kind"] == "face"
    coord, part_index = core.vertex_anchor(vtx_pid)
    assert len(coord) == 3 and isinstance(part_index, int)


def test_mesh_and_save_wires_owners(fixtures, tmp_path):
    core = AppCore()
    core.set_model(fixtures["hertz"]["model"], "hertz")
    face_pid, vtx_pid = _first_pids(core.model_data())
    core.set_face_owners([(face_pid, "myface")])
    core.set_vertex_owners([(vtx_pid, "myvertex")])

    stats = core.mesh({"mesh_type": "tet4", "element_size": 8.0})
    assert stats["element_count"] > 0
    out = str(tmp_path / "m.json")
    core.save_mesh(out, "meshdata_json")
    core.finalize()

    data = json.load(open(out))
    conts = {c["owner"]: c for c in data["meshEntityContainers"]}
    assert "myface" in conts and conts["myface"]["nodeIds"]
    assert "myvertex" in conts and conts["myvertex"]["nodeIds"]


def test_export_model(tmp_path):
    core = AppCore()
    core.build_model("hemisphere_sector", {}, kind="part")
    step = str(tmp_path / "h.step")
    core.export_model(step, "step")
    assert os.path.getsize(step) > 0
    cmd = str(tmp_path / "h.json")
    core.export_model(cmd, "cadmodeldata")
    assert os.path.getsize(cmd) > 0
