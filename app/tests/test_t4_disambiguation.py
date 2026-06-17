"""T4 — coincident-entity disambiguation (Feature R5).

On the Hertz assembly the contact pole (0,0,-10) is a vertex on BOTH the sphere
and the block. Unqualified resolution returns both; qualified by owning volume
returns exactly the one on that part.
"""
import gmsh

from helpers import gmsh_session
from mesher.resolver import GeometricResolver

POLE = (0.0, 0.0, -10.0)


def test_contact_vertex_disambiguation(fixtures):
    with gmsh_session(fixtures["hertz"]["step"]):
        r = GeometricResolver()
        vols = [t for _, t in gmsh.model.getEntities(3)]
        assert len(vols) == 2

        both = r.resolve_vertex(POLE)
        assert len(both) == 2, f"expected both bodies' pole vertices, got {both}"

        per_vol = {v: r.resolve_vertex(POLE, volume=v) for v in vols}
        # each volume yields exactly one, and they are different vertices
        assert all(len(t) == 1 for t in per_vol.values()), per_vol
        assert per_vol[vols[0]] != per_vol[vols[1]]
        # together they are the unqualified set
        assert set(per_vol[vols[0]]) | set(per_vol[vols[1]]) == set(both)
