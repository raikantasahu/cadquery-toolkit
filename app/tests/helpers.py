"""Shared, resolver-independent helpers for the entity-identification tests.

The oracle is geometric and computed directly from gmsh / CADModelData — it
never trusts entity tags/PIDs, which are the thing under test.
"""
import contextlib

import cadquery as cq
import gmsh
import numpy as np

from converter import assembly_to_modeldata, part_to_modeldata
from model.tessellation import create_polydatas_per_part


@contextlib.contextmanager
def gmsh_session(step_path):
    """Import ``step_path`` into a fresh gmsh model; finalize on exit."""
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("session")
    try:
        gmsh.merge(step_path)
        gmsh.model.occ.synchronize()
        yield
    finally:
        gmsh.finalize()


def edge_samples(tag, n=5):
    """``n`` world points along curve ``tag`` (endpoints + interior)."""
    lo, hi = gmsh.model.getParametrizationBounds(1, tag)
    ts = [lo[0] + (hi[0] - lo[0]) * i / (n - 1) for i in range(n)]
    return [tuple(gmsh.model.getValue(1, tag, [t])) for t in ts]


def face_samples(tag, n=3):
    """A small grid of world points on surface ``tag``."""
    lo, hi = gmsh.model.getParametrizationBounds(2, tag)
    pts = []
    for i in range(n):
        for j in range(n):
            u = lo[0] + (hi[0] - lo[0]) * (i + 1) / (n + 1)
            v = lo[1] + (hi[1] - lo[1]) * (j + 1) / (n + 1)
            pts.append(tuple(gmsh.model.getValue(2, tag, [u, v])))
    return pts


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def cadmodeldata(model):
    """CADModelData dict for a Workplane (part) or Assembly."""
    md = (assembly_to_modeldata(model) if isinstance(model, cq.Assembly)
          else part_to_modeldata(model, name="m"))
    return md.to_dict()


def _part_counts(m):
    return (len(m.get("vertexList") or []), len(m.get("edgeList") or []),
            len(m.get("faceList") or []))


def cad_counts(md):
    """(vertices, edges, faces) over INSTANCES, to match gmsh's flattened solids.

    CADModelData dedups identical part *definitions* (a part placed N times is
    stored once and referenced by N ``childComponents`` with per-instance
    transforms — product-structure instancing). gmsh, importing the flattened
    STEP, sees N solids. So count per instance: each childComponent contributes
    its referenced part's entities. A single part (no childComponents) sums its
    own model(s).
    """
    models = md["models"]
    root = models[md.get("rootIndex", 0)]
    comps = root.get("childComponents") or []
    if comps:
        v = e = f = 0
        for c in comps:
            idx = c.get("childIndex", c.get("childModelIndex"))
            pv, pe, pf = _part_counts(models[idx])
            v += pv
            e += pe
            f += pf
        return (v, e, f)
    v = e = f = 0
    for m in models:
        pv, pe, pf = _part_counts(m)
        v += pv
        e += pe
        f += pf
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
