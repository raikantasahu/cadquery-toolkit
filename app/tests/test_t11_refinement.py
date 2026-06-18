"""T11 (refinement) — local/contact refinement anchors via the shared resolver.

Refinement resolves its coordinate anchor through GeometricResolver (same path
as owners/cap face). Verify it actually densifies the mesh near the anchor, for
both contact scope (all bodies at the pole) and local scope (one part).
"""
import gmsh
import numpy as np

from mesher import create_mesh
from mesher.gmsh_mesher import RefinementSpec

POLE = np.array([0.0, 0.0, -10.0])


def _nodes_within(radius):
    coords = np.asarray(gmsh.model.mesh.getNodes()[1]).reshape(-1, 3)
    return int((((coords - POLE) ** 2).sum(1) ** 0.5 < radius).sum())


def _count(model, refinements):
    mesher, _ = create_mesh(model, "tet4", 8.0, model_name="h",
                            refinements=refinements)
    try:
        return _nodes_within(8.0)
    finally:
        mesher.finalize()


def test_contact_refinement_densifies_near_pole(fixtures):
    model = fixtures["hertz"]["model"]
    coarse = _count(model, None)
    refined = _count(model, [RefinementSpec(
        at=(0.0, 0.0, -10.0), fine_size=1.0, radius=8.0, scope="contact")])
    assert refined > 3 * coarse, (coarse, refined)


def test_local_refinement_on_one_part(fixtures):
    model = fixtures["hertz"]["model"]
    coarse = _count(model, None)
    # part_index 1 = block (sphere is 0); resolver confines the field to it.
    refined = _count(model, [RefinementSpec(
        at=(0.0, 0.0, -10.0), fine_size=1.0, radius=8.0, scope="local",
        part_index=1)])
    assert refined > coarse, (coarse, refined)
