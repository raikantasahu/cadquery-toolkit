"""
meshdata_json_exporter - Save a Gmsh mesh to the MeshData JSON format.

Same structure as the MeshData XML but serialized as JSON.
Must be called while Gmsh is initialized and a mesh has been generated.
"""

import json

from .meshdata import collect


def save_as_meshdata_json(filename: str, mesh_id: int = 1,
                          owner: str = "model",
                          entity_owners: dict = None) -> None:
    """
    Write the current Gmsh mesh to a MeshData JSON file.

    Args:
        filename: Output file path (should end with .json).
        mesh_id: Integer id for the mesh.
        owner: Owner string for the mesh.
        entity_owners: Mapping from CADModelData PersistentID to owner
            string.  See :func:`meshdata.collect` for details.
    """
    data = collect(mesh_id=mesh_id, owner=owner, entity_owners=entity_owners)

    mesh = {
        "id": data.mesh_id,
        "owner": data.owner,
        "nodes": [
            {"id": n.id, "location": [n.x, n.y, n.z]}
            for n in data.nodes
        ],
        "fragments": [
            {
                "elementType": frag.element_type,
                "owner": frag.owner,
                "elements": [
                    {"id": elem.id, "nodes": elem.nodes}
                    for elem in frag.elements
                ],
            }
            for frag in data.fragments
        ],
        "boundaryEdges": [
            {"id": edge.id, "nodes": edge.nodes}
            for edge in data.boundary_edges
        ],
        "boundaryFaces": [
            {"id": face.id, "nodes": face.nodes}
            for face in data.boundary_faces
        ],
        "meshEntityContainers": [
            _container_to_dict(c) for c in data.containers
        ],
    }

    with open(filename, "w") as f:
        json.dump(mesh, f, indent=2)
        f.write("\n")


def _container_to_dict(c):
    d = {
        "owner": c.owner,
        "containerKey": c.container_key,
        "nodeIds": c.node_ids,
    }
    if c.edge_ids:
        d["edgeIds"] = c.edge_ids
    if c.face_ids:
        d["faceIds"] = c.face_ids
    return d
