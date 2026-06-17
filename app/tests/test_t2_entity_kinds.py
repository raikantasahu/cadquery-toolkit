"""T2 — all entity kinds resolve (Feature R2).

Round-trip oracle: for each gmsh entity, build its anchor from gmsh geometry,
resolve, and assert the resolution includes that entity. Independent of tags
(the anchor is geometry; we only check the resolved tag's geometry matches).
"""
import gmsh
import pytest

from helpers import edge_samples, face_samples, gmsh_session
from mesher.resolver import GeometricResolver


@pytest.mark.parametrize("name", ["hertz", "hemisphere"])
def test_round_trip_all_kinds(fixtures, name):
    with gmsh_session(fixtures[name]["step"]):
        r = GeometricResolver()

        # Vertices
        for _, t in gmsh.model.getEntities(0):
            xyz = gmsh.model.getValue(0, t, [])
            assert t in r.resolve_vertex(xyz), f"vertex {t} did not round-trip"

        # Edges (multi-sample). Skip degenerate zero-length seam/pole edges —
        # OCC revolve artifacts collapsed to a point, not pickable entities.
        for _, t in gmsh.model.getEntities(1):
            if gmsh.model.occ.getMass(1, t) < 1e-7:
                continue
            assert t in r.resolve_edge(edge_samples(t)), \
                f"edge {t} did not round-trip"

        # Faces (centroid + area + facet samples)
        for _, t in gmsh.model.getEntities(2):
            com = gmsh.model.occ.getCenterOfMass(2, t)
            area = gmsh.model.occ.getMass(2, t)
            got = r.resolve_face(com, area=area, facet_samples=face_samples(t))
            assert t in got, f"face {t} did not round-trip (got {got})"

        # Parts (volume centroid)
        for _, t in gmsh.model.getEntities(3):
            com = gmsh.model.occ.getCenterOfMass(3, t)
            assert t in r.resolve_part(com), f"part {t} did not round-trip"
