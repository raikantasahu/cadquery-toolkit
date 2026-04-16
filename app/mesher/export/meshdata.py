"""
meshdata - Collect MeshData from the active Gmsh session.

Extracts nodes, fragments, boundary edges/faces, and entity containers
into a plain dict structure that format-specific exporters (XML, JSON)
can serialize.

Must be called while Gmsh is initialized and a mesh has been generated.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import gmsh

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


def collect(mesh_id: int = 1, owner: str = "model",
            entity_owners: Optional[Dict[str, str]] = None) -> MeshData:
    """
    Collect all mesh data from the active Gmsh session.

    Args:
        mesh_id: Integer id for the mesh.
        owner: Owner string for the mesh and its fragments.
        entity_owners: Optional mapping from CADModelData PersistentID
            to owner string, e.g. ``{"V0": "Vertex 1001",
            "E0": "Edge 2001", "F0": "Face 3001"}``.  Gmsh entity
            tags are converted to PersistentIDs via the offset
            (tag 1 → V0/E0/F0).  Entities without a mapping are skipped.

    Returns:
        MeshData with all collected data.
    """
    entity_owners = entity_owners or {}

    # --- Nodes ---
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes = []
    for i, tag in enumerate(node_tags):
        nodes.append(MeshNode(
            id=int(tag),
            x=float(coords[3 * i]),
            y=float(coords[3 * i + 1]),
            z=float(coords[3 * i + 2]),
        ))

    # --- Fragments (one per Gmsh 3D element type) ---
    elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(dim=3)
    fragments = []
    global_elem_id = 1

    for etype, enodes in zip(elem_types, elem_node_tags):
        type_name = GMSH_TO_ELEMENT_TYPE.get(int(etype))
        if type_name is None:
            continue
        props = gmsh.model.mesh.getElementProperties(int(etype))
        nodes_per_elem = props[3]
        num_elems = len(enodes) // nodes_per_elem

        elements = []
        for i in range(num_elems):
            start = i * nodes_per_elem
            end = start + nodes_per_elem
            elements.append(MeshElement(
                id=global_elem_id,
                nodes=[int(n) for n in enodes[start:end]],
            ))
            global_elem_id += 1
        fragments.append(MeshFragment(
            element_type=type_name, owner=owner, elements=elements,
        ))

    # --- Boundary edges per geometric curve ---
    edges_per_curve: Dict[int, List[int]] = {}
    all_boundary_edges: List[BoundaryEdge] = []
    global_edge_id = 1

    for _, curve_tag in gmsh.model.getEntities(dim=1):
        curve_edge_ids = []
        etypes, _, enodes_list = gmsh.model.mesh.getElements(1, curve_tag)
        for etype_1d, enodes_1d in zip(etypes, enodes_list):
            props = gmsh.model.mesh.getElementProperties(int(etype_1d))
            npe = props[3]
            num = len(enodes_1d) // npe
            for i in range(num):
                start = i * npe
                edge_nodes = [int(n) for n in enodes_1d[start:start + npe]]
                all_boundary_edges.append(BoundaryEdge(
                    id=global_edge_id, nodes=edge_nodes,
                ))
                curve_edge_ids.append(global_edge_id)
                global_edge_id += 1
        edges_per_curve[curve_tag] = curve_edge_ids

    # --- Boundary faces per geometric surface ---
    faces_per_surface: Dict[int, List[int]] = {}
    all_boundary_faces: List[BoundaryFace] = []
    global_face_id = 1

    for _, surf_tag in gmsh.model.getEntities(dim=2):
        surf_face_ids = []
        ftypes, _, fnodes_list = gmsh.model.mesh.getElements(2, surf_tag)
        for ftype, fnodes in zip(ftypes, fnodes_list):
            props = gmsh.model.mesh.getElementProperties(int(ftype))
            npf = props[3]
            num = len(fnodes) // npf
            for i in range(num):
                start = i * npf
                face_nodes = [int(n) for n in fnodes[start:start + npf]]
                all_boundary_faces.append(BoundaryFace(
                    id=global_face_id, nodes=face_nodes,
                ))
                surf_face_ids.append(global_face_id)
                global_face_id += 1
        faces_per_surface[surf_tag] = surf_face_ids

    # --- Entity containers ---
    containers: List[EntityContainer] = []

    # Vertex containers (dim=0)
    for _, vtx_tag in gmsh.model.getEntities(dim=0):
        pid = f"V{vtx_tag - 1}"
        owner_str = entity_owners.get(pid)
        if owner_str is None:
            continue
        vtx_node_tags, _, _ = gmsh.model.mesh.getNodes(0, vtx_tag)
        containers.append(EntityContainer(
            owner=owner_str,
            container_key=_parse_container_key(owner_str),
            node_ids=sorted(int(n) for n in vtx_node_tags),
        ))

    # Edge containers (dim=1)
    for _, curve_tag in gmsh.model.getEntities(dim=1):
        pid = f"E{curve_tag - 1}"
        owner_str = entity_owners.get(pid)
        if owner_str is None:
            continue
        curve_node_tags, _, _ = gmsh.model.mesh.getNodes(1, curve_tag)
        containers.append(EntityContainer(
            owner=owner_str,
            container_key=_parse_container_key(owner_str),
            node_ids=sorted(int(n) for n in curve_node_tags),
            edge_ids=edges_per_curve.get(curve_tag, []),
        ))

    # Face containers (dim=2)
    for _, surf_tag in gmsh.model.getEntities(dim=2):
        pid = f"F{surf_tag - 1}"
        owner_str = entity_owners.get(pid)
        if owner_str is None:
            continue
        surf_node_tags, _, _ = gmsh.model.mesh.getNodes(2, surf_tag)
        bounding = gmsh.model.getBoundary([(2, surf_tag)], oriented=False)
        surf_edge_ids = []
        for _, btag in bounding:
            surf_edge_ids.extend(edges_per_curve.get(abs(btag), []))
        surf_edge_ids.sort()

        containers.append(EntityContainer(
            owner=owner_str,
            container_key=_parse_container_key(owner_str),
            node_ids=sorted(int(n) for n in surf_node_tags),
            edge_ids=surf_edge_ids,
            face_ids=faces_per_surface.get(surf_tag, []),
        ))

    return MeshData(
        mesh_id=mesh_id,
        owner=owner,
        nodes=nodes,
        fragments=fragments,
        boundary_edges=all_boundary_edges,
        boundary_faces=all_boundary_faces,
        containers=containers,
    )
