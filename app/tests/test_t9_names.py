"""T9 — names are not relied on; resolution is geometry only (Feature R9).

gmsh does not surface usable per-entity STEP names (only a non-discriminating
shape label), so the resolver ignores names entirely: the manifest carries no
name, and every entity of a file whose STEP entities DO carry names resolves
purely by geometry.
"""
import os

import gmsh

from helpers import gmsh_session
from mesher.resolver import GeometricResolver


def test_resolution_is_geometry_only(nist_dir):
    step = os.path.join(nist_dir, "nist_ctc_01_asme1_ap242-e1.stp")
    with gmsh_session(step):
        r = GeometricResolver()
        # the manifest exposes no name field at all
        assert all("name" not in e for e in r.describe_entities())
        # every face resolves by geometry alone (no name input exists)
        for _, t in gmsh.model.getEntities(2):
            com = gmsh.model.occ.getCenterOfMass(2, t)
            area = gmsh.model.occ.getMass(2, t)
            assert t in r.resolve_face(com, area=area), \
                f"face {t} did not resolve by geometry"
