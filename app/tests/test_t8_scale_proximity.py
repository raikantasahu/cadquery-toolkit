"""T8 — scale- and proximity-awareness (Feature R10).

Resolution adapts to model scale, distinguishes densely packed real-world
features (NIST part round-trip), and handles near-misses within tolerance.
"""
import os

import gmsh
import pytest

from exporter.step_exporter import export
from helpers import gmsh_session
from mesher.resolver import EntityResolutionError, GeometricResolver
from models.parts import get_part_function


@pytest.mark.parametrize("radius", [0.01, 10000.0])
def test_scale_robustness(tmp_path, radius):
    model = get_part_function("hemisphere_sector")(radius=radius,
                                                    sweep_angle=90.0)
    step = str(tmp_path / f"hemi_{radius}.step")
    export(model, step)
    with gmsh_session(step):
        r = GeometricResolver()
        for _, t in gmsh.model.getEntities(2):
            com = gmsh.model.occ.getCenterOfMass(2, t)
            area = gmsh.model.occ.getMass(2, t)
            assert t in r.resolve_face(com, area=area), \
                f"face {t} not resolved at scale radius={radius}"


def test_proximity_dense_features(nist_dir):
    """Every face of a real NIST part (dense features) resolves to itself, not
    a near neighbour. Also a perf sanity (≈117 faces)."""
    step = os.path.join(nist_dir, "nist_ctc_01_asme1_ap242-e1.stp")
    with gmsh_session(step):
        r = GeometricResolver()
        for _, t in gmsh.model.getEntities(2):
            com = gmsh.model.occ.getCenterOfMass(2, t)
            area = gmsh.model.occ.getMass(2, t)
            got = r.resolve_face(com, area=area)
            assert t in got, f"face {t} not resolved (got {got})"


def test_near_miss(fixtures):
    with gmsh_session(fixtures["hertz"]["step"]):
        r = GeometricResolver()
        _, t = gmsh.model.getEntities(0)[0]
        xyz = list(gmsh.model.getValue(0, t, []))
        within = [xyz[0] + r._tol * 0.5, xyz[1], xyz[2]]
        assert t in r.resolve_vertex(within), "within-tolerance miss"
        beyond = [xyz[0] + 1e6, xyz[1], xyz[2]]
        with pytest.raises(EntityResolutionError):
            r.resolve_vertex(beyond)
