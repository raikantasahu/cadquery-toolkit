"""T9 — names are an optional aid, never required or trusted (Feature R9).

NIST AP242 files populate entity names, but non-discriminatingly (every face is
"Shapes/SOLID"). Passing that name must not break or mislead resolution — it is
area-validated, fails (it maps to all faces), and geometry decides.
"""
import os

import gmsh

from helpers import gmsh_session
from mesher.resolver import GeometricResolver


def test_nondiscriminating_name_does_not_mislead(nist_dir):
    step = os.path.join(nist_dir, "nist_ctc_01_asme1_ap242-e1.stp")
    with gmsh_session(step):
        r = GeometricResolver()
        # confirm the names really are non-discriminating
        names = {e["name"] for e in r._index[2] if e["name"]}
        assert names, "expected populated (if non-discriminating) names"

        for _, t in gmsh.model.getEntities(2):
            com = gmsh.model.occ.getCenterOfMass(2, t)
            area = gmsh.model.occ.getMass(2, t)
            name = gmsh.model.getEntityName(2, t)  # e.g. "Shapes/SOLID"
            # passing the useless name must still resolve correctly by geometry
            assert t in r.resolve_face(com, area=area, name=name), \
                f"face {t} mis-resolved when given non-discriminating name {name!r}"
