"""Red baseline — the confirmed entity-identification bug (T3 / T11 vertex case).

On a multi-part assembly the GUI picker numbers vertices in CAD-traversal order,
which does NOT match gmsh's STEP-import order, so a picked vertex owner attaches
its container to the WRONG gmsh vertex. This test asserts the *correct* behavior
(the container's node sits at the picked vertex's location) and is therefore
expected to FAIL today; it must flip to passing once the geometric resolver is
wired in (Implementation P3). `strict=True` makes an unexpected pass a failure,
so the marker can't be left stale.
"""
import json

import pytest

from helpers import cadmodeldata, dist, picker_vertex_coords
from mesher import create_mesh, save_mesh_meshdata_json


@pytest.mark.xfail(
    strict=True,
    reason="Geometric Entity Identification not yet implemented (P3): picker "
           "V# != gmsh tag on assemblies. See "
           "docs/plans/Geometric-Entity-Identification/.",
)
def test_picked_vertex_owner_lands_on_picked_vertex(fixtures, tmp_path):
    model = fixtures["hertz"]["model"]
    md = cadmodeldata(model)

    # The block's contact-pole vertex at (0,0,-10). Both bodies have a vertex
    # there; the block's is the higher picker index (sphere pole is lower).
    target = (0.0, 0.0, -10.0)
    at_target = [pid for pid, c in picker_vertex_coords(md).items()
                 if dist(c, target) < 1e-6]
    assert at_target, "expected a picked vertex at the contact pole"
    picked_pid = max(at_target, key=lambda s: int(s[1:]))  # block's vertex

    mesher, _ = create_mesh(model, "tet4", 8.0, model_name="hertz")
    out = str(tmp_path / "hertz.json")
    try:
        save_mesh_meshdata_json(
            mesher, out, entity_owners={picked_pid: "block-contact"})
    finally:
        mesher.finalize()

    data = json.load(open(out))
    nodes = {n["id"]: tuple(n["location"]) for n in data["nodes"]}
    containers = [c for c in data["meshEntityContainers"]
                  if c["owner"] == "block-contact"]
    assert containers, "no container emitted for the picked block vertex"
    node_locs = [nodes[i] for i in containers[0]["nodeIds"]]

    # Correct behavior: the owner container's node is AT the picked vertex.
    assert any(dist(loc, target) < 1e-6 for loc in node_locs), (
        f"container node(s) {node_locs} are not at the picked vertex {target} "
        f"(today they land on the wrong gmsh vertex — the bug)")
