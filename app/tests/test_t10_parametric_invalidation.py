"""T10 — parametric invalidation (Feature §Decisions, R6).

The feature's explicit decision: when an app parametric model is re-evaluated
with different parameters the geometry moves, and any reference made against the
*old* geometry is considered invalid — the user re-picks. There is deliberately
no best-effort re-resolution against the new geometry.

This test pins that contract. A vertex, edge, and face reference made against
the model at one parameter value, replayed against the moved geometry, must fail
LOUDLY (EntityResolutionError, Feature R6) rather than silently snapping to
whatever entity now happens to sit nearby; and the same reference re-made against
the new geometry resolves correctly (re-make works). The geometry is moved well
beyond the resolver's adaptive tolerance, so a silent snap would be a real bug,
not a tolerance accident.
"""
import cadquery as cq
import pytest

from exporter.step_exporter import export as step_export
from helpers import gmsh_session
from mesher.resolver import EntityResolutionError, GeometricResolver


def _bar_step(tmp_path, length):
    """App parametric part: a length x 1 x 1 bar spanning x in [0, length], so
    its +x face (with that face's corners and edges) sits at the plane x=length.
    Exported to STEP just as the app would."""
    a = cq.Assembly()
    a.add(
        cq.Workplane("XY").box(length, 1, 1).translate((length / 2.0, 0.5, 0.5)),
        name="bar",
    )
    path = str(tmp_path / f"bar_{length}.step")
    step_export(a, path)
    return path


def _anchors_at(x):
    """The three reference kinds, all pinned to the +x face at plane x=`x`:
    a corner vertex, a bounding edge, and the face centroid+area."""
    return {
        "vertex": (x, 0.0, 0.0),
        "edge": [(x, i / 4.0, 0.0) for i in range(5)],   # (x,0,0) -> (x,1,0)
        "face": {"centroid": (x, 0.5, 0.5), "area": 1.0},
    }


def _resolve_all(r, a):
    """Resolve every reference kind; raises if any does not resolve."""
    r.resolve_vertex(a["vertex"])
    r.resolve_edge(a["edge"])
    r.resolve_face(a["face"]["centroid"], area=a["face"]["area"])


def test_parametric_references_invalidate_loudly(tmp_path):
    stale = _anchors_at(2.0)   # references made against the length=2 geometry
    fresh = _anchors_at(3.0)   # the same references re-made against length=3

    # Positive control: the references resolve against the geometry they were
    # made on, so a failure below is the parameter change, not a bad anchor.
    with gmsh_session(_bar_step(tmp_path, 2.0)):
        _resolve_all(GeometricResolver(), stale)

    # Re-evaluate the model at length=3: the +x face (and its corners/edges)
    # moved by 1.0 in x -- far beyond the resolver's tolerance.
    with gmsh_session(_bar_step(tmp_path, 3.0)):
        r = GeometricResolver()

        # Stale references are flagged loudly -- never snapped to a near entity.
        with pytest.raises(EntityResolutionError):
            r.resolve_vertex(stale["vertex"])
        with pytest.raises(EntityResolutionError):
            r.resolve_edge(stale["edge"])
        with pytest.raises(EntityResolutionError):
            r.resolve_face(stale["face"]["centroid"], area=stale["face"]["area"])

        # Re-made references against the new geometry resolve correctly: the
        # remedy is to re-pick, and re-picking works.
        _resolve_all(r, fresh)
