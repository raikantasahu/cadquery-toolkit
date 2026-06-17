"""T3 / T11 (owner-container core) — entity identity via the geometric resolver.

This was the P0 red baseline (picker V# -> wrong gmsh vertex on assemblies).
P3 routes owner containers through the resolver via geometric selections, so a
picked vertex/face owner lands on the correct gmsh entity — including the two
coincident contact-pole vertices, which must resolve to DIFFERENT nodes (one per
body). Formerly xfail; now passes.
"""
import json

import gmsh

from helpers import dist
from mesher import create_mesh, save_mesh_meshdata_json
from mesher.resolver import EntityResolutionError

POLE = (0.0, 0.0, -10.0)


def test_owner_containers_resolve_to_correct_entities(fixtures, tmp_path):
    model = fixtures["hertz"]["model"]
    mesher, _ = create_mesh(model, "tet4", 8.0, model_name="hertz")
    try:
        r = mesher._resolver
        # Identify the two volumes: the block owns the bottom corner (0,0,-40).
        block_vol = sphere_vol = None
        for _, v in gmsh.model.getEntities(3):
            try:
                r.resolve_vertex((0.0, 0.0, -40.0), volume=v)
                block_vol = v
            except EntityResolutionError:
                sphere_vol = v
        assert block_vol and sphere_vol and block_vol != sphere_vol

        selections = [
            ({"kind": "vertex", "at": POLE, "volume": block_vol},
             "block-contact"),
            ({"kind": "vertex", "at": POLE, "volume": sphere_vol},
             "sphere-contact"),
            ({"kind": "face", "centroid": (15.0, 15.0, -40.0), "area": 900.0},
             "fixed-bottom"),
        ]
        out = str(tmp_path / "hertz.json")
        save_mesh_meshdata_json(mesher, out, selections=selections)
    finally:
        mesher.finalize()

    data = json.load(open(out))
    nodes = {n["id"]: tuple(n["location"]) for n in data["nodes"]}
    conts = {c["owner"]: c for c in data["meshEntityContainers"]}

    # Both contact-pole owners exist; each container's node sits AT the pole, but
    # they are DIFFERENT nodes (one per body) — the coincident-vertex
    # disambiguation that the picker-V# path got wrong.
    bc = conts["block-contact"]["nodeIds"]
    sc = conts["sphere-contact"]["nodeIds"]
    assert bc and sc and set(bc).isdisjoint(sc)
    for nid in bc + sc:
        assert dist(nodes[nid], POLE) < 1e-6

    # The face owner attaches to the block's bottom face (all nodes at z=-40).
    fb = conts["fixed-bottom"]["nodeIds"]
    assert fb and all(abs(nodes[n][2] + 40.0) < 1e-6 for n in fb)
