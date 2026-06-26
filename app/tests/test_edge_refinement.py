"""Edge-Mesh-Controls (F3) P1 — edge-anchored mesh refinement (CurvesList field).

Headless core tests: a `RefinementSpec` edge variant drives a gmsh
`Distance`-over-`CurvesList` field, refining the mesh along the *whole* contact
line — the curve analog of the existing vertex (`PointsList`) refinement. CLI/GUI
plumbing is P2/P3. See docs/plans/Edge-Mesh-Controls/.
"""
import json
import os
import subprocess
import sys

import gmsh
import pytest
import yaml

from helpers import cadmodeldata
from mesher import create_mesh, MeshValidationError, RefinementSpec
from model.tessellation import anchor_for_pick, create_polydatas_per_part
from models.assemblies import get_assembly_function

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RADIUS = 10.0
_CONTACT_COM = (0.0, 10.0, -_RADIUS)   # midpoint of the contact line, y in [0,20]
# Samples along the contact line (x=0, z=-R); resolve_edge finds both bodies'
# coincident curves through them.
_CONTACT_SAMPLES = [(0.0, y, -_RADIUS) for y in (0.0, 5.0, 10.0, 15.0, 20.0)]
_FINE, _RAD, _EL = 0.5, 2.0, 8.0


def _model():
    return get_assembly_function("hertzian_cylinder_on_block_quarter_symmetry")()


def _dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _contact_curves():
    """gmsh curve tags whose centre of mass is the contact-line midpoint — one
    per touching body (the coincident contact lines)."""
    return [t for _d, t in gmsh.model.getEntities(1)
            if _dist(gmsh.model.occ.getCenterOfMass(1, t), _CONTACT_COM) < 1e-3]


def _curve_node_spacings(curve_tag):
    """Consecutive spacings of the mesh nodes on a curve, ordered along it (the
    contact line runs in +y, so order by y — equivalent to the parametric order
    the plan describes, simpler for a straight line)."""
    _tags, coords, _ = gmsh.model.mesh.getNodes(1, curve_tag, includeBoundary=True)
    pts = sorted((tuple(coords[i:i + 3]) for i in range(0, len(coords), 3)),
                 key=lambda p: p[1])
    return [_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def _edge_spec(scope="contact", **kw):
    return RefinementSpec(edge_samples=_CONTACT_SAMPLES, fine_size=_FINE,
                          radius=_RAD, scope=scope, **kw)


def _contact_edge_pid(md):
    """The E# of a contact-line edge (samples all on x=0, z=-R), as the CLI sees it."""
    for _label, pd in create_polydatas_per_part(md, with_face_index=True):
        for pid in (str(v) for v in pd.field_data.get("edge_pids", [])):
            s = anchor_for_pick(md, pid)["samples"]
            if all(abs(x) < 1e-6 and abs(z + _RADIUS) < 1e-6 for (x, _y, z) in s):
                return pid
    return None


def _meshdata_node_count(path):
    return len(json.load(open(path))["nodes"])


# ── T1 — finer mesh along the curve (keystone) ──────────────────────────────

def test_edge_refinement_finer_along_curve():
    mesher, stats = create_mesh(_model(), "tet4", _EL, refinements=[_edge_spec()])
    curves = _contact_curves()
    assert len(curves) == 2
    spacings = _curve_node_spacings(curves[0])
    n_with, mean_spacing = stats["element_count"], sum(spacings) / len(spacings)
    nodes_with = len(spacings) + 1
    mesher.finalize()

    mesher0, stats0 = create_mesh(_model(), "tet4", _EL)
    nodes_without = len(_curve_node_spacings(_contact_curves()[0])) + 1
    n_without = stats0["element_count"]
    mesher0.finalize()

    assert n_with > n_without                       # refinement added elements
    assert nodes_with > 3 * nodes_without           # the line is far finer
    assert 0.5 * _FINE <= mean_spacing <= 2.0 * _FINE  # ~fine_size, whole length


# ── T2 — contact scope refines both bodies ──────────────────────────────────

def test_contact_scope_refines_both_bodies():
    mesher, _ = create_mesh(_model(), "tet4", _EL, refinements=[_edge_spec()])
    curves = _contact_curves()
    assert len(curves) == 2
    for c in curves:
        sp = _curve_node_spacings(c)
        assert len(sp) > 20                          # finely subdivided
        assert sum(sp) / len(sp) <= 2.0 * _FINE      # ~fine_size along the line
    mesher.finalize()


# ── T3 — local scope refines one body only ──────────────────────────────────

def test_local_scope_refines_one_body():
    mesher, _ = create_mesh(_model(), "tet4", _EL,
                            refinements=[_edge_spec(scope="local", part_index=0)])
    counts = [len(_curve_node_spacings(c)) + 1 for c in _contact_curves()]
    mesher.finalize()
    assert len(counts) == 2
    # exactly one body's contact curve is refined; the other stays coarse
    assert sum(n > 20 for n in counts) == 1, counts
    assert sum(n < 10 for n in counts) == 1, counts


# ── T4 — composes with relativeSagTolerance ─────────────────────────────────

def test_edge_refinement_composes_with_sag():
    mesher, _ = create_mesh(_model(), "tet4", _EL,
                            relative_sag_tolerance=0.05, refinements=[_edge_spec()])
    sp = _curve_node_spacings(_contact_curves()[0])
    mesher.finalize()
    assert sum(sp) / len(sp) <= 2.0 * _FINE          # edge band still fine


# ── T5 — registry CLI: refine by edgePid ────────────────────────────────────

def test_registry_cli_edge_refinement(tmp_path):
    epid = _contact_edge_pid(cadmodeldata(_model()))
    assert epid

    def run(refine, name):
        mesh = {"elementType": "tet4", "elementSize": _EL}
        if refine:
            mesh["refinements"] = [{"scope": "contact", "edgePid": epid,
                                    "fineSize": _FINE, "radius": _RAD}]
        cfg = {"mesh": mesh, "output": {"format": "meshdata_json"}}
        cfg_path = str(tmp_path / f"{name}.yaml")
        yaml.safe_dump(cfg, open(cfg_path, "w"))
        out = str(tmp_path / f"{name}.json")
        res = subprocess.run(
            [sys.executable, "app_cli.py",
             "hertzian_cylinder_on_block_quarter_symmetry",
             "--kind", "assembly", "-c", cfg_path, "-o", out],
            cwd=APP_DIR, capture_output=True, text=True)
        assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]
        return _meshdata_node_count(out)

    assert run(True, "ref") > 1.2 * run(False, "plain")   # edgePid densified it


# ── T6 — foreign STEP: refine by edge samples ───────────────────────────────

def test_foreign_step_edge_refinement(fixtures, tmp_path):
    step = fixtures["cylhertz"]["step"]

    def run(refine, name):
        mesh = {"elementType": "tet4", "elementSize": _EL}
        if refine:
            mesh["contactRefinement"] = {
                "samples": [[0.0, 0.0, -_RADIUS], [0.0, 20.0, -_RADIUS]],
                "fineSize": _FINE, "radius": _RAD}
        cfg = {"mesh": mesh, "output": {"format": "json"}}
        cfg_path = str(tmp_path / f"{name}.yaml")
        yaml.safe_dump(cfg, open(cfg_path, "w"))
        out = str(tmp_path / f"{name}.json")
        res = subprocess.run(
            [sys.executable, "mesh_step_model.py", step, cfg_path, "-o", out],
            cwd=APP_DIR, capture_output=True, text=True)
        assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]
        return _meshdata_node_count(out)

    assert run(True, "ref") > 1.2 * run(False, "plain")


# ── T7 — unresolvable edge refinement aborts loudly ─────────────────────────

def test_unresolvable_edge_refinement_aborts():
    far = [(1000.0, 1000.0, 1000.0), (1001.0, 1000.0, 1000.0)]
    spec = RefinementSpec(edge_samples=far, fine_size=_FINE, radius=_RAD,
                          scope="contact")
    with pytest.raises(MeshValidationError):
        create_mesh(_model(), "tet4", _EL, refinements=[spec])
