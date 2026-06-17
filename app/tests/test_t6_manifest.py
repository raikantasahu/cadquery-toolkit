"""T6 — discoverability / manifest (Feature R7).

The manifest must be valid ground truth (per-dim counts == gmsh's; descriptors
match gmsh's own geometry queries), references authored from it must resolve,
and the CLI must surface it.
"""
import os
import subprocess
import sys

import gmsh

from helpers import dist, gmsh_session
from mesher.resolver import GeometricResolver

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NIST = "nist_ctc_01_asme1_ap242-e1.stp"


def test_manifest_is_valid_ground_truth_and_resolves(nist_dir):
    step = os.path.join(nist_dir, _NIST)
    with gmsh_session(step):
        r = GeometricResolver()
        manifest = r.describe_entities()

        # per-dimension counts equal gmsh's
        for d in range(4):
            n_gmsh = len(gmsh.model.getEntities(d))
            n_man = sum(1 for e in manifest if e["dim"] == d)
            assert n_man == n_gmsh, f"dim {d}: manifest {n_man} != gmsh {n_gmsh}"

        # each descriptor matches gmsh's own geometry query
        for e in manifest:
            d, t = e["dim"], e["tag"]
            com = (tuple(gmsh.model.getValue(0, t, [])) if d == 0
                   else tuple(gmsh.model.occ.getCenterOfMass(d, t)))
            assert dist(e["com"], com) <= 1e-6, f"{d}:{t} centroid drift"
            if d >= 1:
                assert abs(e["meas"] - gmsh.model.occ.getMass(d, t)) \
                    <= 1e-6 * max(1.0, e["meas"])

        # references authored purely from the manifest resolve to that entity
        for e in (x for x in manifest if x["dim"] == 2):
            assert e["tag"] in r.resolve_face(e["com"], area=e["meas"]), \
                f"manifest-authored face {e['tag']} did not resolve to itself"


def test_list_entities_cli(nist_dir):
    step = os.path.join(nist_dir, _NIST)
    res = subprocess.run(
        [sys.executable, "mesh_step_model.py", step, "--list-entities"],
        cwd=APP_DIR, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr[-800:]
    out = res.stdout
    assert "vertex" in out and "edge" in out and "face" in out
    assert "at [" in out and "area=" in out
