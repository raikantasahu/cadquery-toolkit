"""CADModelData -> tessellated geometry and selection anchors (GTK-free).

Builds pyvista PolyData per part from a CADModelData envelope and resolves a
picked F#/V# PID to a geometric anchor for the geometric resolver. Depends on
numpy + pyvista only (no gi/Gtk, no rendering), so it is usable headlessly by
the mesher core, the CLIs, and the tests as well as by the GTK viewer.

Deliberately NOT re-exported from model/__init__.py, so ``from model import
CADModelData`` stays free of pyvista/vtk (a layering-guard test enforces this).
"""

import logging

import numpy as np
import pyvista as pv
from typing import Any, Dict, List, Optional

from model.CADModelData import _ci_get

logger = logging.getLogger(__name__)


# ── Helpers for reading CAD_ModelData ────────────────────────────────────────
# _ci_get (case-insensitive dict read) is shared with the schema module.


def _identity_matrix() -> List[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _matmul4(a: List[float], b: List[float]) -> List[float]:
    """Multiply two row-major 4x4 matrices given as flat 16-element lists."""
    A = np.asarray(a, dtype=np.float64).reshape(4, 4)
    B = np.asarray(b, dtype=np.float64).reshape(4, 4)
    return (A @ B).flatten().tolist()


def _transform_points(points: np.ndarray, matrix: List[float]) -> np.ndarray:
    """Apply a row-major 4x4 affine transform to an (N,3) point array."""
    M = np.asarray(matrix, dtype=np.float64).reshape(4, 4)
    R = M[:3, :3]
    t = M[:3, 3]
    return points @ R.T + t


def _edge_polyline(edge: Dict[str, Any], pid: str, part_label: str):
    """(k, 3) local-space points of one edge's discretized polyline, or None if
    the edge carries too few points to form a polyline.

    The points are the ``edge.discretize`` samples the converter already stored
    (``vertexLocations``). A degenerate/empty edge is skipped *loudly* (naming
    the edge + part) rather than silently dropped — it would otherwise vanish
    from the picker with no trace (loud-safety-net convention)."""
    vlocs = _ci_get(edge, "vertexLocations") or []
    if len(vlocs) < 6 or len(vlocs) % 3 != 0:
        logger.warning(
            "edge %s on part %r has %d coordinate(s) (need a multiple of 3 and "
            "at least 2 points); skipping it — it will not be pickable.",
            pid, part_label, len(vlocs))
        return None
    return np.asarray(vlocs, dtype=np.float64).reshape(-1, 3)


def _edge_samples(points: np.ndarray, max_samples: int = 5) -> List[tuple]:
    """A few representative points along an edge polyline for the resolver:
    always both endpoints, plus evenly spaced interior points (deduped). Enough
    for ``resolve_edge``'s projection self-check on a curved edge, few enough to
    stay cheap."""
    n = len(points)
    if n <= max_samples:
        idx = range(n)
    else:
        idx = sorted({round(j * (n - 1) / (max_samples - 1))
                      for j in range(max_samples)})
    return [tuple(float(c) for c in points[i]) for i in idx]


def _emit_face(
    face: Dict[str, Any],
    transform: List[float],
    all_vertices: List[List[float]],
    all_faces: List[int],
    vertex_offset: List[int],
    cell_face_index: Optional[List[int]] = None,
    face_index: int = -1,
) -> None:
    """Append the triangles of one face to the running PolyData buffers.

    If ``cell_face_index`` is provided, ``face_index`` is appended once
    per emitted triangle so picking can map a clicked cell back to its
    parent CAD face. ``face_index`` references a parallel list of
    persistent IDs maintained by the caller.
    """
    vertex_locations = _ci_get(face, "vertexLocations") or []
    connectivity = _ci_get(face, "connectivity") or []

    if not vertex_locations or not connectivity:
        return

    num_vertices = len(vertex_locations) // 3
    pts = np.asarray(vertex_locations, dtype=np.float64).reshape(num_vertices, 3)
    pts_world = _transform_points(pts, transform)
    all_vertices.extend(pts_world.tolist())

    num_triangles = len(connectivity) // 3
    base = vertex_offset[0]
    for i in range(num_triangles):
        all_faces.extend([
            3,
            base + connectivity[i * 3],
            base + connectivity[i * 3 + 1],
            base + connectivity[i * 3 + 2],
        ])
    if cell_face_index is not None:
        cell_face_index.extend([face_index] * num_triangles)
    vertex_offset[0] += num_vertices


def _iter_envelope(data: Dict[str, Any]):
    """Yield ``(model, component_name, world_transform)`` for every model in the
    CAD_ModelData envelope, DFS pre-order, composing parent transforms.

    A part referenced by multiple Components is yielded once per instance:
    ``visited`` rebinds per recursion path (not globally) so a shared PART is
    re-emitted under each placement. Falls back to a flat single-model dict with
    the identity transform. This is the single traversal shared by
    create_polydata_from_model_data, enumerate_part_labels, and
    create_polydatas_per_part.
    """
    models = _ci_get(data, "models")
    if not (isinstance(models, list) and models):
        yield data, None, _identity_matrix()
        return
    root = int(_ci_get(data, "rootIndex", 0) or 0)
    if not 0 <= root < len(models):
        raise ValueError(
            f"rootIndex {root} out of range (0..{len(models) - 1})")

    def _walk(index, transform, visited, component_name):
        if index in visited:
            return
        visited = visited | {index}
        yield models[index], component_name, transform
        for component in _ci_get(models[index], "childComponents") or []:
            child = int(_ci_get(component, "childIndex", 0) or 0)
            if not 0 <= child < len(models):
                continue
            local = (_ci_get(component, "transformToParent")
                     or _identity_matrix())
            yield from _walk(child, _matmul4(transform, local), visited,
                             _ci_get(component, "componentName"))

    yield from _walk(root, _identity_matrix(), set(), None)


def _label_for(model: Dict[str, Any], component_name,
               counts: Dict[str, int]) -> str:
    """Per-part display label with a ``#N`` suffix for repeated names. Prefer the
    per-instance component name (instanced parts share one model whose own name
    can't tell the instances apart)."""
    name = str(component_name
               or _ci_get(model, "componentName")
               or _ci_get(model, "modelName")
               or "part")
    counts[name] = counts.get(name, 0) + 1
    n = counts[name]
    return name if n == 1 else f"{name} #{n}"


def _emit_part(model, transform, face_counter, vertex_counter, edge_counter,
               with_face_index):
    """Build one PolyData from a single model's faces (world space), or None if
    it has no geometry. ``face_counter``/``vertex_counter``/``edge_counter`` are
    boxed ints for global F#/V#/E# numbering across parts (traversal order)."""
    face_list = _ci_get(model, "faceList") or []
    if not face_list:
        return None

    all_vertices: List[List[float]] = []
    all_faces: List[int] = []
    vertex_offset: List[int] = [0]
    cell_face_index: Optional[List[int]] = [] if with_face_index else None
    face_pids: Optional[List[str]] = [] if with_face_index else None

    for face in face_list:
        face_index = -1
        if face_pids is not None:
            face_index = len(face_pids)
            face_pids.append(f"F{face_counter[0]}")
            face_counter[0] += 1
        _emit_face(face, transform, all_vertices, all_faces, vertex_offset,
                   cell_face_index=cell_face_index, face_index=face_index)

    if not all_vertices:
        return None

    mesh = pv.PolyData(np.array(all_vertices, dtype=np.float64),
                       np.array(all_faces, dtype=np.int64))
    mesh.compute_normals(inplace=True)
    if with_face_index and cell_face_index is not None:
        mesh.cell_data["face_index"] = np.asarray(
            cell_face_index, dtype=np.int32)
        mesh.field_data["face_pids"] = np.asarray(face_pids, dtype=object)
        # Topological vertices (corner points) for the vertex picker, numbered
        # globally V# in the same traversal order as faces.
        vtx_pids: List[str] = []
        vtx_xyz: List[List[float]] = []
        for vtx in _ci_get(model, "vertexList") or []:
            loc = _ci_get(vtx, "location")
            if not loc or len(loc) != 3:
                continue
            vtx_pids.append(f"V{vertex_counter[0]}")
            vertex_counter[0] += 1
            vtx_xyz.append([float(loc[0]), float(loc[1]), float(loc[2])])
        if vtx_xyz:
            pts_world = _transform_points(
                np.asarray(vtx_xyz, dtype=np.float64), transform)
            mesh.field_data["vertex_points"] = pts_world.flatten()
            mesh.field_data["vertex_pids"] = np.asarray(vtx_pids, dtype=object)

        # Topological edges (discretized polylines) for the edge picker,
        # numbered globally E# in the same traversal order. Variable-length
        # polylines are packed into one flat point buffer with a parallel
        # offsets array (start index per edge, length n_edges + 1) so each edge
        # slices out unambiguously: edge i is edge_points[offsets[i]:offsets[i+1]].
        part_label = str(_ci_get(model, "componentName")
                         or _ci_get(model, "modelName") or "part")
        edge_pids: List[str] = []
        edge_offsets: List[int] = [0]
        edge_xyz: List[List[float]] = []
        for edge in _ci_get(model, "edgeList") or []:
            pid = f"E{edge_counter[0]}"
            pts = _edge_polyline(edge, pid, part_label)
            if pts is None:
                continue
            edge_counter[0] += 1
            edge_pids.append(pid)
            edge_xyz.extend(pts.tolist())
            edge_offsets.append(len(edge_xyz))
        if edge_pids:
            pts_world = _transform_points(
                np.asarray(edge_xyz, dtype=np.float64), transform)
            mesh.field_data["edge_points"] = pts_world.flatten()
            mesh.field_data["edge_offsets"] = np.asarray(
                edge_offsets, dtype=np.int64)
            mesh.field_data["edge_pids"] = np.asarray(edge_pids, dtype=object)
    return mesh


def create_polydata_from_model_data(
    data: Dict[str, Any], with_face_index: bool = False,
) -> pv.PolyData:
    """Convert a CAD_ModelData dict to PyVista PolyData.

    Accepts either format produced by this project:

    1. **Envelope** (multi-model assembly):
       ``{"rootIndex": int, "models": [...]}``. Each model has its own
       ``faceList`` (in its local frame) and a ``childComponents`` list
       describing nested placements via ``transformToParent``. We walk the
       tree starting at ``rootIndex`` and accumulate all faces in world
       space, applying composed transforms along the way.

    2. **Flat single-model** (legacy / single-PART output):
       a top-level dict with a ``faceList`` directly on it. Faces are
       used as-is (identity transform).

    Both PascalCase and camelCase property names are accepted.

    If ``with_face_index`` is True, the returned PolyData gets a
    ``face_index`` cell-data array (one int per triangle) and a
    ``face_pids`` field-data array (the parallel list of persistent IDs,
    indexed by ``face_index``). Used by the face-picker.

    Raises:
        ValueError: If no valid geometry is found in the data.
    """
    all_vertices: List[List[float]] = []
    all_faces: List[int] = []
    vertex_offset: List[int] = [0]  # boxed so helpers can mutate it

    cell_face_index: Optional[List[int]] = [] if with_face_index else None
    face_pids: Optional[List[str]] = [] if with_face_index else None

    for model, _component_name, transform in _iter_envelope(data):
        for face in _ci_get(model, "faceList") or []:
            face_index = -1
            if face_pids is not None:
                pid = _ci_get(face, "persistentID")
                face_index = len(face_pids)
                face_pids.append(
                    str(pid) if pid is not None else f"_{face_index}")
            _emit_face(
                face, transform, all_vertices, all_faces, vertex_offset,
                cell_face_index=cell_face_index, face_index=face_index)

    if not all_vertices:
        raise ValueError("No valid geometry found in data")

    vertices = np.array(all_vertices, dtype=np.float64)
    faces = np.array(all_faces, dtype=np.int64)

    mesh = pv.PolyData(vertices, faces)
    mesh.compute_normals(inplace=True)
    if with_face_index and cell_face_index is not None:
        mesh.cell_data["face_index"] = np.asarray(
            cell_face_index, dtype=np.int32,
        )
        mesh.field_data["face_pids"] = np.asarray(face_pids, dtype=object)
    return mesh


def enumerate_part_labels(data: Dict[str, Any]) -> List[str]:
    """Return per-part labels in the same DFS order as create_polydatas_per_part.

    Each label is the leaf model's componentName/modelName with a ``#N``
    suffix for repeats. Lightweight (no triangulation) so callers can
    use it to build ``entity_owners["P{n}"]`` mappings that line up
    with the mesher's per-volume MeshFragments.

    Returns an empty list when ``data`` has no parts with geometry.
    """
    labels: List[str] = []
    counts: Dict[str, int] = {}
    for model, component_name, _transform in _iter_envelope(data):
        if _ci_get(model, "faceList"):
            labels.append(_label_for(model, component_name, counts))
    return labels


def create_polydatas_per_part(
    data: Dict[str, Any], with_face_index: bool = False,
) -> List[tuple]:
    """Build one PolyData per leaf part instance.

    Walks the envelope and emits a separate PolyData every time a model
    with a non-empty ``faceList`` is reached (in world space, with
    composed parent transforms). This lets the viewer add each part as
    its own actor so users can hide/show parts independently.

    If ``with_face_index`` is True, each PolyData carries a ``face_index``
    cell-data array (one int per triangle) and a ``face_pids`` field-data
    array of persistent IDs. PIDs are numbered globally across all parts
    in traversal order (``F0``, ``F1``, …) so they line up with the
    mesher's flat Gmsh-surface-tag enumeration after STEP import.

    Returns a list of ``(label, pv.PolyData)`` pairs in traversal order.
    Labels come from the leaf model's ``componentName``/``modelName``,
    with a ``#N`` suffix when the same name appears more than once.

    Raises:
        ValueError: If no valid geometry is found in the data.
    """
    parts: List[tuple] = []
    counts: Dict[str, int] = {}
    # Faces, topological vertices, and edges are numbered globally in traversal
    # order (F0/F1.. , V0/V1.. , E0/E1..) so they line up with the mesher's flat
    # Gmsh tag enumeration after STEP import.
    face_counter = [0]
    vertex_counter = [0]
    edge_counter = [0]

    for model, component_name, transform in _iter_envelope(data):
        mesh = _emit_part(model, transform, face_counter, vertex_counter,
                          edge_counter, with_face_index)
        if mesh is not None:
            parts.append((_label_for(model, component_name, counts), mesh))

    if not parts:
        raise ValueError("No valid geometry found in data")

    return parts


def anchor_for_pick(data: Dict[str, Any], pid: str):
    """Geometric anchor for a picked entity PID, for the geometric resolver.

    Bridges the GUI picker / CLI listing (which return ``F#``/``V#``/``E#``
    PIDs) to the source-agnostic resolver: returns a ``{'kind': ..., ...}``
    anchor built from the referenced entity's geometry (vertex coordinate +
    owning part; face area-weighted centroid + area + a few facet samples; edge
    sample points along its polyline), so identity rides on geometry, not on the
    PID. Returns ``None`` if the PID is not found.
    """
    for part_index, (_label, pd) in enumerate(
            create_polydatas_per_part(data, with_face_index=True)):
        fd = pd.field_data
        if pid.startswith("V") and "vertex_pids" in fd:
            pids = [str(v) for v in fd["vertex_pids"]]
            if pid in pids:
                p = np.asarray(fd["vertex_points"]).reshape(-1, 3)[
                    pids.index(pid)]
                return {"kind": "vertex", "at": tuple(float(c) for c in p),
                        "part": part_index}
        if pid.startswith("F") and "face_pids" in fd:
            fpids = [str(v) for v in fd["face_pids"]]
            if pid in fpids:
                mask = np.asarray(pd.cell_data["face_index"]) == fpids.index(pid)
                centers = pd.cell_centers().points[mask]
                areas = pd.compute_cell_sizes(
                    length=False, area=True, volume=False).cell_data["Area"][mask]
                total = float(areas.sum())
                if total <= 0:
                    return None
                centroid = (centers * areas[:, None]).sum(axis=0) / total
                step = max(1, len(centers) // 4)
                return {
                    "kind": "face",
                    "centroid": tuple(float(c) for c in centroid),
                    "area": total,
                    "facet_samples": [tuple(float(c) for c in s)
                                      for s in centers[::step][:4]],
                }
        if pid.startswith("E") and "edge_pids" in fd:
            epids = [str(v) for v in fd["edge_pids"]]
            if pid in epids:
                i = epids.index(pid)
                pts = np.asarray(fd["edge_points"]).reshape(-1, 3)
                offs = np.asarray(fd["edge_offsets"])
                polyline = pts[offs[i]:offs[i + 1]]
                return {"kind": "edge", "samples": _edge_samples(polyline)}
    return None


def edge_lines_polydata(edge_points, edge_offsets, edge_pids) -> pv.PolyData:
    """Pickable line PolyData from the flat edge buffers ``_emit_part`` surfaces.

    One VTK polyline cell per edge, tagged with ``cell_data["edge_index"]`` (the
    edge ordinal, parallel to the face picker's ``face_index``) and
    ``field_data["edge_pids"]``, so a picked cell maps back to its ``E#``:
    ``edge_pids[cell_data["edge_index"][picked_cell]]``. GTK-free so the viewer's
    edge picker and the headless tests build it the same way.
    """
    pts = np.asarray(edge_points, dtype=np.float64).reshape(-1, 3)
    offs = np.asarray(edge_offsets, dtype=np.int64)
    lines: List[int] = []
    edge_index: List[int] = []
    for i in range(len(offs) - 1):
        a, b = int(offs[i]), int(offs[i + 1])
        if b - a < 2:
            continue  # _emit_part already guarantees >= 2 points; be defensive
        lines.append(b - a)
        lines.extend(range(a, b))
        edge_index.append(i)
    poly = pv.PolyData(pts, lines=np.asarray(lines, dtype=np.int64))
    poly.cell_data["edge_index"] = np.asarray(edge_index, dtype=np.int32)
    poly.field_data["edge_pids"] = np.asarray(
        [str(p) for p in edge_pids], dtype=object)
    return poly
