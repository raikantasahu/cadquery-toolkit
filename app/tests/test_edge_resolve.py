"""Edge-Identity-and-Picking P1 — T2 keystone: referenced E# resolves correctly.

A referenced edge's anchor (sample points along its polyline) maps through the
geometric resolver to the matching mesh curve(s) — the source-independent
identity contract both F2 (edge owners) and F3 (edge mesh controls) build on.
The coincident contact line of the line-contact assembly must resolve to exactly
one curve per touching body. A bad reference must fail loudly.

Mirrors test_t11_gui_bridge.py (the face/vertex bridge) for edges.
See docs/plans/Edge-Identity-and-Picking/.
"""
import gmsh
import numpy as np
import pytest

from helpers import cadmodeldata, gmsh_session
from mesher.resolver import EntityResolutionError, GeometricResolver
from model.tessellation import anchor_for_pick, create_polydatas_per_part

# The line-contact assembly's contact line sits at x=0, z=-cylinder_radius.
_CONTACT_RADIUS = 10.0


def _edge_pids(md):
    pids = []
    for _label, pd in create_polydatas_per_part(md, with_face_index=True):
        pids += [str(v) for v in pd.field_data.get("edge_pids", [])]
    return pids


def _all_samples_on_contact_line(samples):
    return all(abs(x) < 1e-6 and abs(z + _CONTACT_RADIUS) < 1e-6
               for (x, _y, z) in samples)


def test_referenced_edges_resolve_to_matching_curves(fixtures):
    model = fixtures["cylhertz"]["model"]
    md = cadmodeldata(model)
    pids = _edge_pids(md)
    assert pids

    with gmsh_session(fixtures["cylhertz"]["step"]):
        r = GeometricResolver()
        contact_pids = []
        for pid in pids:
            a = anchor_for_pick(md, pid)
            assert a and a["kind"] == "edge"
            tags = r.resolve_edge(a["samples"])
            assert tags, pid
            # every returned curve actually passes through the sample points
            # (the samples are discretized points lying on the edge)
            for t in tags:
                for s in a["samples"]:
                    cp, _ = gmsh.model.getClosestPoint(1, t, list(s))
                    assert sum((c - x) ** 2 for c, x in zip(cp, s)) ** 0.5 < 1e-2
            if _all_samples_on_contact_line(a["samples"]):
                contact_pids.append((pid, tags))

        # The contact line is a CAD edge on BOTH bodies (cylinder + block), so
        # it is surfaced twice and each reference resolves to the two coincident
        # curves — one per touching body (Geometric-Entity-Identification R5).
        assert len(contact_pids) == 2, "contact edge surfaced on both bodies"
        for pid, tags in contact_pids:
            assert len(tags) == 2, (pid, tags)


def test_surfaced_edges_are_in_assembly_space(fixtures):
    """Placed-part assembly: every surfaced edge lands on a gmsh curve, which is
    in assembly/world space (from the baked STEP). Guards the per-part ->
    assembly transform for edges specifically: the bolted joint places its parts
    off-identity (translation + a 180deg rotation), so an edge left in part-local
    space would sit far from its world curve and fail here. (cylhertz can't catch
    this — its parts are placed at identity, so part space == assembly space.)"""
    md = cadmodeldata(fixtures["bolted"]["model"])
    with gmsh_session(fixtures["bolted"]["step"]):
        curves = [t for _d, t in gmsh.model.getEntities(1)]
        assert curves
        checked = 0
        for _label, pd in create_polydatas_per_part(md, with_face_index=True):
            fd = pd.field_data
            pts = np.asarray(fd.get("edge_points", [])).reshape(-1, 3)
            offs = np.asarray(fd.get("edge_offsets", []))
            for i, pid in enumerate(str(v) for v in fd.get("edge_pids", [])):
                seg = pts[offs[i]:offs[i + 1]]
                mid = seg[len(seg) // 2]
                d = min(
                    sum((c - x) ** 2 for c, x in
                        zip(gmsh.model.getClosestPoint(1, t, list(mid))[0], mid))
                    ** 0.5
                    for t in curves)
                assert d < 0.1, (pid, tuple(mid), d)
                checked += 1
        assert checked, "no edges surfaced on the placed assembly"


def test_unresolvable_reference_is_loud(fixtures):
    with gmsh_session(fixtures["cylhertz"]["step"]):
        r = GeometricResolver()
        far = [(1000.0, 1000.0, 1000.0), (1001.0, 1000.0, 1000.0)]
        with pytest.raises(EntityResolutionError):
            r.resolve_edge(far)
