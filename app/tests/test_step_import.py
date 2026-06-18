"""STEP-Import-GUI P1 — the data path behind the GTK chooser.

Reading an external STEP and feeding it to AppCore must work exactly like a
built model: convert (param-less), pick by F#/V#, mesh, save with owners. This
is the whole feature minus the file chooser (GTK, manual-smoke only).
"""
import json
import os

from app_core import AppCore
from importer import step_importer
from model.tessellation import create_polydatas_per_part


def _first_face_pid(md):
    for _label, pd in create_polydatas_per_part(md, with_face_index=True):
        fp = pd.field_data.get("face_pids", [])
        if len(fp):
            return str(fp[0])
    return None


def test_imported_step_meshes_and_owner_attaches(fixtures, tmp_path):
    # Read a STEP file (a part) the same way the GUI panel will, then drive the
    # core exactly as a built model would — locks the param-less
    # part_to_modeldata(parameters=None) path.
    model = step_importer.read(fixtures["hemisphere"]["step"])
    core = AppCore()
    core.set_model(model, "hemi-imported")

    md = core.model_data()
    face_pid = _first_face_pid(md)
    assert face_pid, "imported part should expose F# face PIDs"
    core.set_face_owners([(face_pid, "imported-face")])

    stats = core.mesh({"mesh_type": "tet4", "element_size": 8.0})
    assert stats["element_count"] > 0
    out = str(tmp_path / "imported.json")
    core.save_mesh(out, "meshdata_json")
    core.finalize()

    conts = {c["owner"]: c for c in json.load(open(out))["meshEntityContainers"]}
    assert "imported-face" in conts and conts["imported-face"]["nodeIds"]


def test_real_external_step_reads_and_converts(nist_dir):
    # A genuine foreign STEP (NIST) flows through read -> set_model -> model_data
    # via the GUI's core path (no meshing here — keep it fast).
    model = step_importer.read(
        os.path.join(nist_dir, "nist_ctc_01_asme1_ap242-e1.stp"))
    core = AppCore()
    core.set_model(model, "ctc_01")
    md = core.model_data()
    faces = sum(len(m.get("faceList") or []) for m in md["models"])
    assert faces > 0
