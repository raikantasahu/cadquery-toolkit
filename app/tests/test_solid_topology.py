"""Volume->face topology in the FreeCAD converter (Tier 3 correctness fix).

_extract_solids used to give every solid ALL the part's faces ("assume all faces
belong to the solid"). For a multi-solid part that's wrong — each solid owns only
its own faces. Verify the partition; and that a single solid still owns all.
"""
import cadquery as cq

from converter import part_to_modeldata


def _root_model(cq_obj):
    md = part_to_modeldata(cq_obj, name="m").to_dict()
    return md["models"][md.get("rootIndex", 0)]


def test_multisolid_faces_partition_by_solid():
    # two disjoint unit boxes -> 2 solids, 12 faces, 6 per solid
    model = _root_model(
        cq.Workplane("XY").pushPoints([(0, 0), (5, 0)]).box(1, 1, 1))
    n_faces = len(model["faceList"])
    vols = model["volumeList"]
    assert len(vols) == 2

    seen = []
    for v in vols:
        fl = v["faceList"]
        assert len(fl) == 6              # its own faces, not all 12
        seen += fl
    assert len(seen) == len(set(seen))           # disjoint across solids
    assert sorted(seen) == list(range(n_faces))  # together cover every face


def test_single_solid_owns_all_its_faces():
    model = _root_model(cq.Workplane("XY").box(2, 3, 4))
    vols = model["volumeList"]
    assert len(vols) == 1
    assert vols[0]["faceList"] == list(range(len(model["faceList"])))
