"""T11 (GUI bridge) — picked-PID -> geometric anchor -> resolves correctly.

The GUI picker returns F#/V# PIDs; anchor_for_pick converts each to a geometric
anchor, which the resolver maps to the correct mesh entity. This is the
GTK-free core of the GUI adapter (app_gtk is then a thin caller).
"""
import gmsh

from helpers import cadmodeldata, dist, gmsh_session
from mesher.resolver import GeometricResolver
from model.tessellation import anchor_for_pick


def test_picked_face_and_vertex_anchors_resolve(fixtures):
    model = fixtures["hertz"]["model"]
    md = cadmodeldata(model)
    # picker PIDs are global F#/V# in CAD-traversal order
    from model.tessellation import create_polydatas_per_part
    face_pids, vtx_pids = [], []
    for _label, pd in create_polydatas_per_part(md, with_face_index=True):
        fd = pd.field_data
        face_pids += [str(v) for v in fd.get("face_pids", [])]
        vtx_pids += [str(v) for v in fd.get("vertex_pids", [])]

    with gmsh_session(fixtures["hertz"]["step"]):
        r = GeometricResolver()

        # every picked face's anchor resolves to the geometrically-nearest face.
        # (The picker centroid is tessellation-based / approximate, so compare by
        # nearest OCC centroid rather than exact equality.)
        coms2 = {e["tag"]: e["com"] for e in r._index[2]}
        for pid in face_pids:
            a = anchor_for_pick(md, pid)
            assert a and a["kind"] == "face"
            tags = r.resolve_face(a["centroid"], area=a["area"],
                                  facet_samples=a.get("facet_samples"))
            nearest = min(coms2, key=lambda t: dist(coms2[t], a["centroid"]))
            assert nearest in tags, pid

        # every picked vertex's anchor resolves to a vertex at that coordinate,
        # on the picked part (coincident contact vertices stay distinguished)
        for pid in vtx_pids:
            a = anchor_for_pick(md, pid)
            assert a and a["kind"] == "vertex"
            tags = r.resolve_vertex(
                a["at"], volume=gmsh.model.getEntities(3)[a["part"]][1])
            coms = {e["tag"]: e["com"] for e in r._index[0]}
            assert tags and all(dist(coms[t], a["at"]) < 1e-6 for t in tags), pid
