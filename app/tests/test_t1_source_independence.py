"""T1 — source independence (Feature R1).

Author anchors directly from one STEP file and resolve them against a different
file of the *same* geometry, different provenance: NIST ctc_01 AP203 with-PMI vs
geometry-only (verified same face count + bounding box; AP242 is a *different*
geometry, not a flavor of the same part). Resolution must land on the
geometrically matching face regardless of which file it came from.
"""
import os

import gmsh

from helpers import gmsh_session
from mesher.resolver import GeometricResolver

_DIST_TOL = 1e-3  # absolute (NIST parts ~hundreds of mm)


def _face_anchors(step):
    out = []
    with gmsh_session(step):
        for _, t in gmsh.model.getEntities(2):
            out.append((tuple(gmsh.model.occ.getCenterOfMass(2, t)),
                        gmsh.model.occ.getMass(2, t)))
    return out


def test_anchors_resolve_across_files_of_same_geometry(nist_dir):
    with_pmi = os.path.join(nist_dir, "AP203 with PMI",
                            "nist_ctc_01_asme1_ap203.stp")
    geom_only = os.path.join(nist_dir, "AP203 geometry only",
                             "nist_ctc_01_asme1_rd.stp")
    anchors = _face_anchors(with_pmi)
    assert anchors

    with gmsh_session(geom_only):
        r = GeometricResolver()
        coms = {e["tag"]: e["com"] for e in r._index[2]}
        for com, area in anchors:
            tags = r.resolve_face(com, area=area)        # may raise -> fail
            # the resolved face(s) sit at the queried location
            assert any(sum((a - b) ** 2 for a, b in zip(coms[t], com)) ** 0.5
                       <= _DIST_TOL for t in tags), (
                f"resolved {tags} not at anchor centroid {com}")


def test_manifest_authored_anchors_resolve_across_files(nist_dir):
    """The manifest/CLI authoring path (Implementation P2): anchors built from
    one file's manifest resolve on the other file of the same geometry."""
    with_pmi = os.path.join(nist_dir, "AP203 with PMI",
                            "nist_ctc_01_asme1_ap203.stp")
    geom_only = os.path.join(nist_dir, "AP203 geometry only",
                             "nist_ctc_01_asme1_rd.stp")
    with gmsh_session(with_pmi):
        manifest = [(e["com"], e["meas"])
                    for e in GeometricResolver().describe_entities()
                    if e["dim"] == 2]
    assert manifest
    with gmsh_session(geom_only):
        r = GeometricResolver()
        for com, area in manifest:
            r.resolve_face(com, area=area)  # must resolve, not raise
