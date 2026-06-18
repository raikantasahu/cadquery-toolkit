"""CADModelData -> tessellated geometry and selection anchors (GTK-free).

Builds pyvista PolyData per part from a CADModelData envelope and resolves a
picked F#/V# PID to a geometric anchor for the geometric resolver. Depends on
numpy + pyvista only (no gi/Gtk, no rendering), so it is usable headlessly by
the mesher core, the CLIs, and the tests as well as by the GTK viewer.

Deliberately NOT re-exported from model/__init__.py, so ``from model import
CADModelData`` stays free of pyvista/vtk (a layering-guard test enforces this).
"""

import numpy as np
import pyvista as pv
from typing import Any, Dict, List, Optional


# ── Helpers for reading CAD_ModelData ────────────────────────────────────────


def _ci_get(d: Dict[str, Any], name: str, default: Any = None) -> Any:
    """Case-insensitive dict lookup.

    Lets us read both camelCase (Python writer) and PascalCase (C# writer)
    CAD_ModelData JSON without caring which side produced it.
    """
    if name in d:
        return d[name]
    lower = name.lower()
    for k, v in d.items():
        if k.lower() == lower:
            return v
    return default


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


def _walk_envelope(
    models: List[Dict[str, Any]],
    model_index: int,
    parent_transform: List[float],
    all_vertices: List[List[float]],
    all_faces: List[int],
    vertex_offset: List[int],
    visited: set,
    cell_face_index: Optional[List[int]] = None,
    face_pids: Optional[List[str]] = None,
) -> None:
    """Recursively emit faces from one model and its children, in world space.

    `parent_transform` is the world-space placement of this model. Each
    Component holds a child's local-to-parent transform; we compose with the
    parent to obtain the child's world transform.

    If ``cell_face_index``/``face_pids`` are provided, each emitted face
    is appended to ``face_pids`` (verbatim PID string from CAD_ModelData)
    and every triangle stamped with that face's index in ``face_pids``.
    """
    if model_index in visited:
        # True cycle: this model is its own ancestor on the current
        # recursion path. The envelope is acyclic by construction, but
        # guard anyway to avoid infinite recursion on malformed input.
        return
    # Rebind to a new set local to this call so sibling traversals don't
    # inherit each other's "seen" markers — required for shared sub-models
    # (a single PART referenced by multiple Component instances).
    visited = visited | {model_index}

    model = models[model_index]

    for face in _ci_get(model, "faceList") or []:
        face_index = -1
        if face_pids is not None:
            pid = _ci_get(face, "persistentID")
            face_index = len(face_pids)
            face_pids.append(str(pid) if pid is not None else f"_{face_index}")
        _emit_face(
            face, parent_transform, all_vertices, all_faces, vertex_offset,
            cell_face_index=cell_face_index, face_index=face_index,
        )

    for component in _ci_get(model, "childComponents") or []:
        child_index = int(_ci_get(component, "childIndex", 0) or 0)
        if child_index < 0 or child_index >= len(models):
            continue
        child_local = _ci_get(component, "transformToParent") or _identity_matrix()
        child_world = _matmul4(parent_transform, child_local)
        _walk_envelope(
            models,
            child_index,
            child_world,
            all_vertices,
            all_faces,
            vertex_offset,
            visited,
            cell_face_index=cell_face_index,
            face_pids=face_pids,
        )


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

    models = _ci_get(data, "models")
    if isinstance(models, list) and models:
        root_index = int(_ci_get(data, "rootIndex", 0) or 0)
        if root_index < 0 or root_index >= len(models):
            raise ValueError(
                f"rootIndex {root_index} out of range (0..{len(models) - 1})"
            )
        _walk_envelope(
            models,
            root_index,
            _identity_matrix(),
            all_vertices,
            all_faces,
            vertex_offset,
            visited=set(),
            cell_face_index=cell_face_index,
            face_pids=face_pids,
        )
    else:
        # Flat single-model fallback.
        identity = _identity_matrix()
        for face in _ci_get(data, "faceList") or []:
            face_index = -1
            if face_pids is not None:
                pid = _ci_get(face, "persistentID")
                face_index = len(face_pids)
                face_pids.append(
                    str(pid) if pid is not None else f"_{face_index}"
                )
            _emit_face(
                face, identity, all_vertices, all_faces, vertex_offset,
                cell_face_index=cell_face_index, face_index=face_index,
            )

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
    label_counts: Dict[str, int] = {}

    def _label_for(model: Dict[str, Any], component_name: Any = None) -> str:
        # Prefer the per-instance component name from the parent's
        # childComponents entry; instanced (deduped) parts share one model
        # whose own name can't tell the instances apart.
        name = (
            component_name
            or _ci_get(model, "componentName")
            or _ci_get(model, "modelName")
            or "part"
        )
        name = str(name)
        label_counts[name] = label_counts.get(name, 0) + 1
        n = label_counts[name]
        return name if n == 1 else f"{name} #{n}"

    def _walk(models, model_index, visited, component_name=None):
        if model_index in visited:
            return
        visited = visited | {model_index}
        model = models[model_index]
        if _ci_get(model, "faceList"):
            labels.append(_label_for(model, component_name))
        for component in _ci_get(model, "childComponents") or []:
            child_index = int(_ci_get(component, "childIndex", 0) or 0)
            if child_index < 0 or child_index >= len(models):
                continue
            _walk(
                models, child_index, visited,
                _ci_get(component, "componentName"),
            )

    models = _ci_get(data, "models")
    if isinstance(models, list) and models:
        root_index = int(_ci_get(data, "rootIndex", 0) or 0)
        if 0 <= root_index < len(models):
            _walk(models, root_index, visited=set())
    elif _ci_get(data, "faceList"):
        labels.append(_label_for(data))

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
    label_counts: Dict[str, int] = {}
    global_face_counter = [0]
    # Topological vertices are numbered globally in the same traversal order
    # as faces (V0, V1, …) so they line up with the mesher's flat Gmsh
    # vertex-tag enumeration after STEP import — the same assumption faces
    # rely on via global_face_counter.
    global_vertex_counter = [0]

    def _label_for(model: Dict[str, Any], component_name: Any = None) -> str:
        # Prefer the per-instance component name from the parent's
        # childComponents entry; instanced (deduped) parts share one model
        # whose own name can't tell the instances apart.
        name = (
            component_name
            or _ci_get(model, "componentName")
            or _ci_get(model, "modelName")
            or "part"
        )
        name = str(name)
        label_counts[name] = label_counts.get(name, 0) + 1
        n = label_counts[name]
        return name if n == 1 else f"{name} #{n}"

    def _emit_part(
        model: Dict[str, Any], transform: List[float],
        component_name: Any = None,
    ) -> None:
        face_list = _ci_get(model, "faceList") or []
        if not face_list:
            return

        all_vertices: List[List[float]] = []
        all_faces: List[int] = []
        vertex_offset: List[int] = [0]
        cell_face_index: Optional[List[int]] = [] if with_face_index else None
        face_pids: Optional[List[str]] = [] if with_face_index else None

        for face in face_list:
            face_index = -1
            if face_pids is not None:
                face_index = len(face_pids)
                face_pids.append(f"F{global_face_counter[0]}")
                global_face_counter[0] += 1
            _emit_face(
                face, transform, all_vertices, all_faces, vertex_offset,
                cell_face_index=cell_face_index, face_index=face_index,
            )

        if not all_vertices:
            return

        vertices = np.array(all_vertices, dtype=np.float64)
        faces = np.array(all_faces, dtype=np.int64)
        mesh = pv.PolyData(vertices, faces)
        mesh.compute_normals(inplace=True)
        if with_face_index and cell_face_index is not None:
            mesh.cell_data["face_index"] = np.asarray(
                cell_face_index, dtype=np.int32,
            )
            mesh.field_data["face_pids"] = np.asarray(face_pids, dtype=object)
            # Stash this part's topological vertices (corner points, not the
            # tessellation vertices above) so the vertex picker can render and
            # pick them. Points are flattened (N*3,) and reshaped on read; the
            # parallel vertex_pids give N and the global V{n} ids.
            vtx_pids: List[str] = []
            vtx_xyz: List[List[float]] = []
            for vtx in _ci_get(model, "vertexList") or []:
                loc = _ci_get(vtx, "location")
                if not loc or len(loc) != 3:
                    continue
                vtx_pids.append(f"V{global_vertex_counter[0]}")
                global_vertex_counter[0] += 1
                vtx_xyz.append([float(loc[0]), float(loc[1]), float(loc[2])])
            if vtx_xyz:
                pts_world = _transform_points(
                    np.asarray(vtx_xyz, dtype=np.float64), transform,
                )
                mesh.field_data["vertex_points"] = pts_world.flatten()
                mesh.field_data["vertex_pids"] = np.asarray(
                    vtx_pids, dtype=object,
                )

        parts.append((_label_for(model, component_name), mesh))

    def _walk(models, model_index, transform, visited, component_name=None):
        if model_index in visited:
            return
        visited = visited | {model_index}
        model = models[model_index]
        _emit_part(model, transform, component_name)
        for component in _ci_get(model, "childComponents") or []:
            child_index = int(_ci_get(component, "childIndex", 0) or 0)
            if child_index < 0 or child_index >= len(models):
                continue
            child_local = (
                _ci_get(component, "transformToParent") or _identity_matrix()
            )
            child_world = _matmul4(transform, child_local)
            _walk(
                models, child_index, child_world, visited,
                _ci_get(component, "componentName"),
            )

    models = _ci_get(data, "models")
    if isinstance(models, list) and models:
        root_index = int(_ci_get(data, "rootIndex", 0) or 0)
        if root_index < 0 or root_index >= len(models):
            raise ValueError(
                f"rootIndex {root_index} out of range (0..{len(models) - 1})"
            )
        _walk(models, root_index, _identity_matrix(), visited=set())
    else:
        _emit_part(data, _identity_matrix())

    if not parts:
        raise ValueError("No valid geometry found in data")

    return parts


def anchor_for_pick(data: Dict[str, Any], pid: str):
    """Geometric anchor for a picked entity PID, for the geometric resolver.

    Bridges the GUI picker (which returns ``F#``/``V#`` PIDs) to the
    source-agnostic resolver: returns a ``{'kind': ..., ...}`` anchor built from
    the picked entity's geometry (vertex coordinate + owning part; face
    area-weighted centroid + area + a few facet samples), so identity rides on
    geometry, not on the PID. Returns ``None`` if the PID is not found.
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
    return None
