"""T5 — loud on failure / ambiguity (Feature R4/R6), at the resolver level.

resolve_* raises EntityResolutionError rather than silently returning nothing or
mis-attributing. (The "two references → one entity" conflict is a build_owner_map
concern, P3.)
"""
import gmsh
import pytest

from helpers import gmsh_session
from mesher.resolver import EntityResolutionError, GeometricResolver


def test_no_entity_at_coordinate_raises(fixtures):
    with gmsh_session(fixtures["hertz"]["step"]):
        r = GeometricResolver()
        far = (1e6, 1e6, 1e6)
        with pytest.raises(EntityResolutionError):
            r.resolve_vertex(far)
        with pytest.raises(EntityResolutionError):
            r.resolve_face(far, area=1.0)


def test_part_qualified_miss_raises(fixtures):
    """A vertex coordinate that exists, but not on the named part, is loud."""
    with gmsh_session(fixtures["hertz"]["step"]):
        r = GeometricResolver()
        vols = [t for _, t in gmsh.model.getEntities(3)]
        # The sphere apex (0,0,0) is a sphere-only vertex; on the OTHER volume
        # resolution must RAISE (not fall back to a near vertex elsewhere).
        apex = (0.0, 0.0, 0.0)
        owning = []
        for v in vols:
            try:
                r.resolve_vertex(apex, volume=v)
                owning.append(v)
            except EntityResolutionError:
                pass
        assert len(owning) == 1, f"apex should be on exactly one part: {owning}"
        other = (set(vols) - set(owning)).pop()
        with pytest.raises(EntityResolutionError):
            r.resolve_vertex(apex, volume=other)


def test_face_extent_mismatch_raises(fixtures):
    """A correct centroid but a wrong (too-large) reference area is rejected by
    the self-check rather than silently accepted."""
    with gmsh_session(fixtures["hertz"]["step"]):
        r = GeometricResolver()
        _, t = gmsh.model.getEntities(2)[0]
        com = gmsh.model.occ.getCenterOfMass(2, t)
        real = gmsh.model.occ.getMass(2, t)
        with pytest.raises(EntityResolutionError):
            r.resolve_face(com, area=real * 100.0)
