"""T0 — 1:1 mapping assumption (precondition for Feature R4).

gmsh must preserve the CAD topology one-to-one for the feature's contract to
hold. Assert CADModelData (V,E,F) == gmsh (points,curves,surfaces) per fixture;
a mismatch fails loudly (it means gmsh split/merged entities for that model).
``bolted`` covers part instancing — counted per instance (cad_counts expands
childComponents) it is 1:1, proving the converter's dedup is lossless and the
earlier "interpenetration breaks 1:1" was a definitions-vs-instances miscount.
"""
import pytest

from helpers import cad_counts, cadmodeldata, gmsh_entity_counts


@pytest.mark.parametrize("name", ["hertz", "hemisphere", "twocubes", "bolted"])
def test_cad_gmsh_topology_one_to_one(fixtures, name):
    fx = fixtures[name]
    cad = cad_counts(cadmodeldata(fx["model"]))
    gm = gmsh_entity_counts(fx["step"])
    assert cad == gm, (
        f"{name}: CAD (V,E,F)={cad} != gmsh (pt,cv,sf)={gm} — gmsh split or "
        f"merged entities; the 1:1 contract does not hold for this model.")
