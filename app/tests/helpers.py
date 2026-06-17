"""Shared, resolver-independent helpers for the entity-identification tests.

The oracle is geometric and computed directly from gmsh / CADModelData — it
never trusts entity tags/PIDs, which are the thing under test.
"""
import cadquery as cq
import gmsh
import numpy as np

from converter import assembly_to_modeldata, part_to_modeldata
from viewer.model_viewer import create_polydatas_per_part


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def cadmodeldata(model):
    """CADModelData dict for a Workplane (part) or Assembly."""
    md = (assembly_to_modeldata(model) if isinstance(model, cq.Assembly)
          else part_to_modeldata(model, name="m"))
    return md.to_dict()


def cad_counts(md):
    """(vertices, edges, faces) summed across all models in the envelope."""
    v = e = f = 0
    for m in md["models"]:
        v += len(m.get("vertexList") or [])
        e += len(m.get("edgeList") or [])
        f += len(m.get("faceList") or [])
    return (v, e, f)


def gmsh_entity_counts(step_path):
    """(points, curves, surfaces) gmsh assigns when importing ``step_path``."""
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("counts")
    try:
        gmsh.merge(step_path)
        gmsh.model.occ.synchronize()
        return tuple(len(gmsh.model.getEntities(d)) for d in range(3))
    finally:
        gmsh.finalize()


def picker_vertex_coords(md):
    """{picker_pid: world (x,y,z)} as the GUI vertex picker would number them
    (global, CAD-traversal order via create_polydatas_per_part)."""
    out = {}
    for _label, pd in create_polydatas_per_part(md, with_face_index=True):
        fd = pd.field_data
        if "vertex_pids" not in fd:
            continue
        pids = [str(v) for v in fd["vertex_pids"]]
        pts = np.asarray(fd["vertex_points"]).reshape(-1, 3)
        for pid, p in zip(pids, pts):
            out[pid] = tuple(float(c) for c in p)
    return out
