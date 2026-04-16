"""
meshdata_xml_exporter - Save a Gmsh mesh to the RSA.Mesh MeshData XML format.

Output structure matches the format consumed by ``MeshXmlReader.cs``.
Must be called while Gmsh is initialized and a mesh has been generated.
"""

from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

from .meshdata import collect


def save_as_meshdata_xml(filename: str, mesh_id: int = 1,
                         owner: str = "model",
                         entity_owners: dict = None) -> None:
    """
    Write the current Gmsh mesh to a MeshData XML file.

    Args:
        filename: Output file path (should end with .xml).
        mesh_id: Integer id for the ``<Mesh>`` element.
        owner: Owner string for the ``<Mesh>`` element.
        entity_owners: Mapping from CADModelData PersistentID to owner
            string.  See :func:`meshdata.collect` for details.
    """
    data = collect(mesh_id=mesh_id, owner=owner, entity_owners=entity_owners)

    root = Element("Mesh", id=str(data.mesh_id), owner=data.owner)

    # --- Nodes ---
    nodes_el = SubElement(root, "Nodes", count=str(len(data.nodes)))
    for n in data.nodes:
        loc = f"{n.x:g} {n.y:g} {n.z:g}"
        SubElement(nodes_el, "N", id=str(n.id), location=loc)

    # --- Fragments ---
    for frag in data.fragments:
        frag_el = SubElement(
            root, "Fragment",
            elementType=frag.element_type, owner=frag.owner,
            count=str(len(frag.elements)),
        )
        for elem in frag.elements:
            node_str = " ".join(str(n) for n in elem.nodes)
            SubElement(frag_el, "E", id=str(elem.id), nodes=node_str)

    # --- BoundaryEdges ---
    if data.boundary_edges:
        be_el = SubElement(
            root, "BoundaryEdges", count=str(len(data.boundary_edges)),
        )
        for edge in data.boundary_edges:
            node_str = " ".join(str(n) for n in edge.nodes)
            SubElement(be_el, "E", id=str(edge.id), nodes=node_str)

    # --- BoundaryFaces ---
    if data.boundary_faces:
        bf_el = SubElement(
            root, "BoundaryFaces", count=str(len(data.boundary_faces)),
        )
        for face in data.boundary_faces:
            node_str = " ".join(str(n) for n in face.nodes)
            SubElement(bf_el, "F", id=str(face.id), nodes=node_str)

    # --- MeshEntityContainers ---
    for c in data.containers:
        attrs = {
            "owner": c.owner,
            "containerKey": str(c.container_key),
            "numNodes": str(len(c.node_ids)),
            "numEdges": str(len(c.edge_ids)),
            "numFaces": str(len(c.face_ids)),
            "nodeIds": " ".join(str(n) for n in c.node_ids),
        }
        if c.edge_ids:
            attrs["edgeIds"] = " ".join(str(e) for e in c.edge_ids)
        if c.face_ids:
            attrs["faceIds"] = " ".join(str(f) for f in c.face_ids)
        SubElement(root, "MeshEntityContainer", **attrs)

    indent(root, space="  ")
    tree = ElementTree(root)
    tree.write(filename, xml_declaration=True, encoding="unicode")
