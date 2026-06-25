"""Edge-Identity-and-Picking P1 — edges surfaced + the E# -> anchor bridge.

Headless, pure-data tests (no display, no gmsh): edges are surfaced on the
per-part geometry with stable contiguous E# ids (T0), anchor_for_pick bridges an
E# to an edge anchor (T1), the ids are repeatable (T3), and the headless
inventory lists them (T5). The resolve round trip is test_edge_resolve.py (T2).

See docs/plans/Edge-Identity-and-Picking/.
"""
import os
import subprocess
import sys

import numpy as np

from helpers import cadmodeldata
from models.parts import get_part_function
from models.assemblies import get_assembly_function
from model.tessellation import anchor_for_pick, create_polydatas_per_part

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _box_md():
    """F-box: a single-solid box — 12 edges, 8 vertices, 6 faces."""
    return cadmodeldata(get_part_function("box")())


def _cyl_md():
    """F-quarter: the line-contact assembly (cylinder-quarter + block)."""
    return cadmodeldata(
        get_assembly_function("hertzian_cylinder_on_block_quarter_symmetry")())


def _edge_pids(pd):
    return [str(v) for v in pd.field_data.get("edge_pids", [])]


# ── T0 — tessellation surfaces edges ────────────────────────────────────────

def test_box_edges_surfaced():
    parts = create_polydatas_per_part(_box_md(), with_face_index=True)
    assert len(parts) == 1
    _label, pd = parts[0]
    fd = pd.field_data

    pids = _edge_pids(pd)
    assert pids == [f"E{i}" for i in range(12)], "box has 12 contiguous edges"

    # flat point buffer + offsets slice each polyline unambiguously
    pts = np.asarray(fd["edge_points"]).reshape(-1, 3)
    offs = np.asarray(fd["edge_offsets"])
    assert offs[0] == 0 and offs[-1] == len(pts)
    assert len(offs) == len(pids) + 1
    assert all(offs[i + 1] - offs[i] >= 2 for i in range(len(pids))), \
        "every edge polyline has >= 2 points"

    # additive: face/vertex arrays still present and the id namespaces disjoint
    assert len(fd.get("face_pids", [])) == 6
    assert len(fd.get("vertex_pids", [])) == 8
    assert all(p.startswith("E") for p in pids)


def test_assembly_edges_global_contiguous():
    parts = create_polydatas_per_part(_cyl_md(), with_face_index=True)
    assert len(parts) == 2, "cylinder-quarter + foundation-quarter"
    all_pids = [p for _l, pd in parts for p in _edge_pids(pd)]
    assert all_pids, "edges surfaced on the assembly"
    # E# numbered globally across parts in traversal order, no gaps/dupes
    assert all_pids == [f"E{i}" for i in range(len(all_pids))]


# ── T1 — anchor_for_pick bridges E# to an edge anchor ───────────────────────

def test_edge_anchor_shape_and_on_edge():
    for md in (_box_md(), _cyl_md()):
        for _label, pd in create_polydatas_per_part(md, with_face_index=True):
            fd = pd.field_data
            pts = np.asarray(fd["edge_points"]).reshape(-1, 3)
            offs = np.asarray(fd["edge_offsets"])
            for i, pid in enumerate(_edge_pids(pd)):
                a = anchor_for_pick(md, pid)
                assert a and a["kind"] == "edge"
                samples = a["samples"]
                assert len(samples) >= 2
                # each sample is one of the edge's discretized polyline points
                poly = pts[offs[i]:offs[i + 1]]
                for s in samples:
                    d = np.linalg.norm(poly - np.asarray(s), axis=1).min()
                    assert d < 1e-9, (pid, s)


def test_unknown_edge_pid_misses():
    md = _box_md()
    assert anchor_for_pick(md, "E9999") is None


# ── T3 — identity is stable / repeatable ────────────────────────────────────

def test_edge_ids_repeatable():
    a = create_polydatas_per_part(_cyl_md(), with_face_index=True)
    b = create_polydatas_per_part(_cyl_md(), with_face_index=True)
    for (_la, pa), (_lb, pb) in zip(a, b):
        assert _edge_pids(pa) == _edge_pids(pb)
        np.testing.assert_array_equal(
            np.asarray(pa.field_data["edge_points"]),
            np.asarray(pb.field_data["edge_points"]))


# ── T5 — headless edge inventory (app_cli --list-entities) ──────────────────

def test_list_entities_lists_edges():
    res = subprocess.run(
        [sys.executable, "app_cli.py",
         "hertzian_cylinder_on_block_quarter_symmetry",
         "--kind", "assembly", "--list-entities"],
        cwd=APP_DIR, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr[-800:]
    # edges listed alongside the faces/vertices already printed
    assert "E0" in res.stdout and "near" in res.stdout
    assert "centroid" in res.stdout and "at " in res.stdout  # F/V intact

    listed = {tok for line in res.stdout.splitlines()
              for tok in (line.strip().split(":", 1)[0],)
              if tok.startswith("E") and tok[1:].isdigit()}
    n_edges = sum(len(create_polydatas_per_part(
        _cyl_md(), with_face_index=True)[i][1].field_data.get("edge_pids", []))
        for i in range(2))
    assert len(listed) == n_edges
