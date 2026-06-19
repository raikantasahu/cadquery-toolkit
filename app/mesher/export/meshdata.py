"""
meshdata - Collect MeshData from the active Gmsh session.

Extracts nodes, fragments, boundary edges/faces, and entity containers
into a plain dict structure that format-specific exporters (XML, JSON)
can serialize.

Must be called while Gmsh is initialized and a mesh has been generated.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import gmsh

logger = logging.getLogger(__name__)

# Schema identifier + version stamped at the top of every MeshData file
# (JSON key/value, XML root attributes). Bump VERSION when the on-disk
# layout changes in a way readers need to discriminate.
SCHEMA = "rsa.mesh"
VERSION = 1

# Gmsh element type codes to MeshData element type names (PascalCase,
# matching the C# ElementType enum in RSA.Mesh).
GMSH_TO_ELEMENT_TYPE = {
    4: "Tet4",
    5: "Hex8",
    6: "Wedge6",
    7: "Pyramid5",
    11: "Tet10",
    17: "Hex20",
    12: "Hex27",
}


@dataclass
class MeshNode:
    id: int
    x: float
    y: float
    z: float


@dataclass
class MeshElement:
    id: int
    nodes: List[int]


@dataclass
class MeshFragment:
    element_type: str
    owner: str
    elements: List[MeshElement]


@dataclass
class BoundaryEdge:
    id: int
    nodes: List[int]


@dataclass
class BoundaryFace:
    id: int
    nodes: List[int]


@dataclass
class EntityContainer:
    owner: str
    container_key: int
    node_ids: List[int]
    edge_ids: List[int] = field(default_factory=list)
    face_ids: List[int] = field(default_factory=list)


@dataclass
class MeshData:
    """All data extracted from a Gmsh session in MeshData schema form."""
    mesh_id: int
    owner: str
    nodes: List[MeshNode]
    fragments: List[MeshFragment]
    boundary_edges: List[BoundaryEdge]
    boundary_faces: List[BoundaryFace]
    containers: List[EntityContainer]


def _parse_container_key(owner_str: str) -> int:
    """Extract the trailing integer from an owner string."""
    m = re.search(r"(\d+)$", owner_str)
    return int(m.group(1)) if m else 0


def _newell_normal(face_nodes, pos):
    """Area-weighted face normal (Newell's method) for the given winding."""
    nx = ny = nz = 0.0
    k = len(face_nodes)
    for i in range(k):
        x0, y0, z0 = pos[face_nodes[i]]
        x1, y1, z1 = pos[face_nodes[(i + 1) % k]]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return nx, ny, nz


def _volume_adjacency(pos):
    """Map each node -> volume-element indices on it, plus element centroids.

    A boundary face's parent volume element is the one shared by all its nodes;
    orienting the face away from that element's centroid gives an outward normal
    independent of whatever winding the mesher emitted.
    """
    node_to_elems: Dict[int, List[int]] = {}
    centroids: List[Tuple[float, float, float]] = []
    for _dim, vol_tag in gmsh.model.getEntities(dim=3):
        etypes, _, enodes_list = gmsh.model.mesh.getElements(3, vol_tag)
        for etype, enodes in zip(etypes, enodes_list):
            npe = gmsh.model.mesh.getElementProperties(int(etype))[3]
            for i in range(len(enodes) // npe):
                en = [int(t) for t in enodes[i * npe:(i + 1) * npe]]
                idx = len(centroids)
                centroids.append((
                    sum(pos[t][0] for t in en) / npe,
                    sum(pos[t][1] for t in en) / npe,
                    sum(pos[t][2] for t in en) / npe,
                ))
                for t in en:
                    node_to_elems.setdefault(t, []).append(idx)
    return node_to_elems, centroids


_PID_LETTER = {0: "V", 1: "E", 2: "F", 3: "P"}


def _make_owner_fn(entity_owners, owner_by_tag):
    """Build the ``(dim, tag) -> owner`` lookup shared by the collectors.

    Prefer the geometry-resolved ``(dim, tag)`` map (built by GeometricResolver
    from geometric selections); fall back to the legacy PersistentID scheme
    (F#/V#/P# == gmsh tag-1) only when no resolved map is supplied. The resolved
    map is correct across STEP sources; the legacy offset is not (see
    docs/plans/Geometric-Entity-Identification/).
    """
    def _owner(dim, tag, default=None):
        if (dim, tag) in owner_by_tag:
            return owner_by_tag[(dim, tag)]
        return entity_owners.get(f"{_PID_LETTER[dim]}{tag - 1}", default)
    return _owner


def _collect_nodes():
    """All mesh nodes + a ``{tag: (x, y, z)}`` position map."""
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes = []
    pos: Dict[int, Tuple[float, float, float]] = {}
    for i, tag in enumerate(node_tags):
        p = (float(coords[3 * i]), float(coords[3 * i + 1]),
             float(coords[3 * i + 2]))
        pos[int(tag)] = p
        nodes.append(MeshNode(id=int(tag), x=p[0], y=p[1], z=p[2]))
    return nodes, pos


def _collect_fragments(owner_fn):
    """One MeshFragment per (gmsh volume, element type).

    Splitting per volume lets an assembly mesh carry one fragment per Part. The
    owner comes from ``owner_fn(3, tag)``; a volume without a mapping falls back
    to a generated ``part_{n+1}`` label (1-based iteration order) so parts can
    still be told apart in the output. Element ids are global and sequential.
    """
    fragments = []
    global_elem_id = 1
    for n, (_dim, vol_tag) in enumerate(gmsh.model.getEntities(dim=3)):
        frag_owner = owner_fn(3, vol_tag, f"part_{n + 1}")
        elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(3, vol_tag)
        for etype, enodes in zip(elem_types, elem_node_tags):
            type_name = GMSH_TO_ELEMENT_TYPE.get(int(etype))
            if type_name is None:
                continue
            nodes_per_elem = gmsh.model.mesh.getElementProperties(int(etype))[3]
            num_elems = len(enodes) // nodes_per_elem
            elements = []
            for i in range(num_elems):
                start = i * nodes_per_elem
                elements.append(MeshElement(
                    id=global_elem_id,
                    nodes=[int(t) for t in enodes[start:start + nodes_per_elem]],
                ))
                global_elem_id += 1
            fragments.append(MeshFragment(
                element_type=type_name, owner=frag_owner, elements=elements,
            ))
    return fragments


def _collect_boundary_edges():
    """BoundaryEdge list + ``{curve_tag: [edge_id, ...]}`` (global ids)."""
    edges_per_curve: Dict[int, List[int]] = {}
    all_boundary_edges: List[BoundaryEdge] = []
    global_edge_id = 1
    for _, curve_tag in gmsh.model.getEntities(dim=1):
        curve_edge_ids = []
        etypes, _, enodes_list = gmsh.model.mesh.getElements(1, curve_tag)
        for etype_1d, enodes_1d in zip(etypes, enodes_list):
            npe = gmsh.model.mesh.getElementProperties(int(etype_1d))[3]
            num = len(enodes_1d) // npe
            for i in range(num):
                start = i * npe
                all_boundary_edges.append(BoundaryEdge(
                    id=global_edge_id,
                    nodes=[int(t) for t in enodes_1d[start:start + npe]],
                ))
                curve_edge_ids.append(global_edge_id)
                global_edge_id += 1
        edges_per_curve[curve_tag] = curve_edge_ids
    return all_boundary_edges, edges_per_curve


def _orient_face_outward(face_nodes, npf, node_to_elems, vol_centroids, pos):
    """Reorder a linear boundary face so its winding points outward.

    Tests the face-winding normal against the centroid of the volume element
    sharing all the face's nodes; reverses the winding (keeping the first
    corner) if it points inward. Returns ``(nodes, flipped)``; ``flipped`` is
    False (nodes unchanged) when the face shares no single parent element.
    """
    common = set(node_to_elems.get(face_nodes[0], ()))
    for fn in face_nodes[1:]:
        common.intersection_update(node_to_elems.get(fn, ()))
    if not common:
        return face_nodes, False
    cx, cy, cz = vol_centroids[next(iter(common))]
    nx, ny, nz = _newell_normal(face_nodes, pos)
    fcx = sum(pos[t][0] for t in face_nodes) / npf
    fcy = sum(pos[t][1] for t in face_nodes) / npf
    fcz = sum(pos[t][2] for t in face_nodes) / npf
    if (nx * (fcx - cx) + ny * (fcy - cy) + nz * (fcz - cz)) < 0:
        return [face_nodes[0]] + face_nodes[:0:-1], True
    return face_nodes, False


def _warn_on_flips(flipped_by_surface):
    """Loudly report any inward boundary faces the exporter had to reorient."""
    if not flipped_by_surface:
        return
    total = sum(flipped_by_surface.values())
    surfs = ", ".join(str(s) for s in sorted(flipped_by_surface))
    logger.warning(
        "MESH DEFECT: re-oriented %d inward-pointing boundary face(s) to "
        "outward on surface tag(s) %s. The mesher emitted inward face "
        "windings — fix this at the source (e.g. the side faces in "
        "ExtrudedHexBuilder); the exporter flip is only a safety net.",
        total, surfs)


def _collect_boundary_faces(pos):
    """BoundaryFace list + ``{surf_tag: [face_id, ...]}``, oriented outward.

    Boundary faces must point outward; any inward-wound linear face is
    reoriented (see :func:`_orient_face_outward`). This is a safety net only — a
    correctly built volume mesh needs zero flips, so any flip is logged loudly
    (:func:`_warn_on_flips`) as a mesher defect to fix at the source rather than
    silently patched here. Only linear faces (3-node tri, 4-node quad) can be
    reversed by a plain winding flip; higher-order node ordering is untouched.
    """
    node_to_elems, vol_centroids = _volume_adjacency(pos)
    flipped_by_surface: Dict[int, int] = {}
    faces_per_surface: Dict[int, List[int]] = {}
    all_boundary_faces: List[BoundaryFace] = []
    global_face_id = 1
    for _, surf_tag in gmsh.model.getEntities(dim=2):
        surf_face_ids = []
        ftypes, _, fnodes_list = gmsh.model.mesh.getElements(2, surf_tag)
        for ftype, fnodes in zip(ftypes, fnodes_list):
            npf = gmsh.model.mesh.getElementProperties(int(ftype))[3]
            linear = int(ftype) in (2, 3)
            num = len(fnodes) // npf
            for i in range(num):
                start = i * npf
                face_nodes = [int(t) for t in fnodes[start:start + npf]]
                if linear and node_to_elems:
                    face_nodes, flipped = _orient_face_outward(
                        face_nodes, npf, node_to_elems, vol_centroids, pos)
                    if flipped:
                        flipped_by_surface[surf_tag] = (
                            flipped_by_surface.get(surf_tag, 0) + 1)
                all_boundary_faces.append(BoundaryFace(
                    id=global_face_id, nodes=face_nodes,
                ))
                surf_face_ids.append(global_face_id)
                global_face_id += 1
        faces_per_surface[surf_tag] = surf_face_ids
    _warn_on_flips(flipped_by_surface)
    return all_boundary_faces, faces_per_surface


def _collect_containers(owner_fn, edges_per_curve, faces_per_surface):
    """MeshEntityContainers for every owned vertex/edge/face entity.

    An entity becomes a container only when ``owner_fn`` returns a name for it
    (unowned entities are skipped). Edge/face containers use includeBoundary so
    their bounding vertices'/edges' nodes are included, not just interior ones.
    """
    containers: List[EntityContainer] = []

    for _, vtx_tag in gmsh.model.getEntities(dim=0):
        owner_str = owner_fn(0, vtx_tag)
        if owner_str is None:
            continue
        vtx_node_tags, _, _ = gmsh.model.mesh.getNodes(0, vtx_tag)
        containers.append(EntityContainer(
            owner=owner_str,
            container_key=_parse_container_key(owner_str),
            node_ids=sorted(int(n) for n in vtx_node_tags),
        ))

    for _, curve_tag in gmsh.model.getEntities(dim=1):
        owner_str = owner_fn(1, curve_tag)
        if owner_str is None:
            continue
        curve_node_tags, _, _ = gmsh.model.mesh.getNodes(
            1, curve_tag, includeBoundary=True)
        containers.append(EntityContainer(
            owner=owner_str,
            container_key=_parse_container_key(owner_str),
            node_ids=sorted({int(n) for n in curve_node_tags}),
            edge_ids=edges_per_curve.get(curve_tag, []),
        ))

    for _, surf_tag in gmsh.model.getEntities(dim=2):
        owner_str = owner_fn(2, surf_tag)
        if owner_str is None:
            continue
        surf_node_tags, _, _ = gmsh.model.mesh.getNodes(
            2, surf_tag, includeBoundary=True)
        bounding = gmsh.model.getBoundary([(2, surf_tag)], oriented=False)
        surf_edge_ids = []
        for _, btag in bounding:
            surf_edge_ids.extend(edges_per_curve.get(abs(btag), []))
        surf_edge_ids.sort()
        containers.append(EntityContainer(
            owner=owner_str,
            container_key=_parse_container_key(owner_str),
            node_ids=sorted({int(n) for n in surf_node_tags}),
            edge_ids=surf_edge_ids,
            face_ids=faces_per_surface.get(surf_tag, []),
        ))
    return containers


def collect(mesh_id: int = 1, owner: str = "model",
            entity_owners: Optional[Dict[str, str]] = None,
            owner_by_tag: Optional[Dict[Tuple[int, int], str]] = None
            ) -> MeshData:
    """
    Collect all mesh data from the active Gmsh session.

    Orchestrates the focused collectors below — nodes, per-volume fragments,
    boundary edges, (outward-oriented) boundary faces, and owned entity
    containers — assembling them into a MeshData (Architecture-Review T2.4: each
    concern is its own helper rather than one monolithic function).

    Args:
        mesh_id: Integer id for the mesh.
        owner: Owner string for the mesh and its fragments.
        entity_owners: Optional mapping from CADModelData PersistentID to owner
            string, e.g. ``{"V0": "Vertex 1001", "E0": "Edge 2001",
            "F0": "Face 3001", "P0": "lap_plate_1"}``. Gmsh entity tags are
            converted to PersistentIDs via the offset (tag 1 -> V0/E0/F0/P0).
            V/E/F entries become MeshEntityContainers (entities without a mapping
            are skipped). P entries name the per-volume MeshFragments; volumes
            without a P mapping fall back to ``"part_{n+1}"`` (1-based iteration
            order).
        owner_by_tag: Optional geometry-resolved ``{(dim, tag): owner}`` map,
            preferred over ``entity_owners`` when supplied (see
            :func:`_make_owner_fn`).

    Returns:
        MeshData with all collected data.
    """
    owner_fn = _make_owner_fn(entity_owners or {}, owner_by_tag or {})

    nodes, pos = _collect_nodes()
    fragments = _collect_fragments(owner_fn)
    boundary_edges, edges_per_curve = _collect_boundary_edges()
    boundary_faces, faces_per_surface = _collect_boundary_faces(pos)
    containers = _collect_containers(
        owner_fn, edges_per_curve, faces_per_surface)

    return MeshData(
        mesh_id=mesh_id,
        owner=owner,
        nodes=nodes,
        fragments=fragments,
        boundary_edges=boundary_edges,
        boundary_faces=boundary_faces,
        containers=containers,
    )
