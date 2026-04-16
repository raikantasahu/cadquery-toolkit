"""
meshdata_reader - Load MeshData (JSON or XML) into a PyVista UnstructuredGrid.

Reader counterpart of :mod:`mesher.export.meshdata_json_exporter` and
:mod:`mesher.export.meshdata_xml_exporter`.  Converts the MeshData schema
(nodes + fragments + boundary entities) into a volumetric PyVista mesh.

MeshData files preserve Gmsh's native element node ordering; for Hex20
and Hex27 that ordering differs from VTK's, so we reorder those node
lists on the way out to match what PyVista expects.
"""

import json
from xml.etree.ElementTree import parse as _xml_parse

import numpy as np
import pyvista as pv


# MeshData element type name → VTK cell type code (3D elements only).
_ELEMENT_TYPE_TO_VTK = {
    "Tet4": 10,
    "Hex8": 12,
    "Wedge6": 13,
    "Pyramid5": 14,
    "Tet10": 24,
    "Hex20": 25,
    "Hex27": 29,
}

# Gmsh→VTK node reordering for second-order hexes.  MeshData stores
# Gmsh's native order; the same reorder is applied in gmsh_mesher.py
# when going straight from a live Gmsh session to PyVista.
_NODE_ORDER_GMSH_TO_VTK = {
    "Hex20": [0, 1, 2, 3, 4, 5, 6, 7,
              8, 11, 13, 9, 16, 18, 19, 17, 10, 12, 14, 15],
    "Hex27": [0, 1, 2, 3, 4, 5, 6, 7,
              8, 11, 13, 9, 16, 18, 19, 17, 10, 12, 14, 15,
              22, 23, 21, 24, 20, 25, 26],
}


def meshdata_to_pyvista(data: dict) -> pv.UnstructuredGrid:
    """Convert a MeshData dict (JSON shape) to a PyVista UnstructuredGrid.

    Args:
        data: Dict with ``nodes`` (list of ``{"id", "location":[x,y,z]}``)
            and ``fragments`` (list of
            ``{"elementType", "owner", "elements":[{"id", "nodes":[...]}]}``)
            — the shape produced by
            :func:`mesher.export.meshdata_json_exporter.save_as_meshdata_json`.

    Returns:
        pv.UnstructuredGrid containing the volumetric mesh.

    Raises:
        ValueError: If the dict has no nodes, or no supported volumetric
            elements.
    """
    raw_nodes = data.get("nodes") or []
    if not raw_nodes:
        raise ValueError("MeshData has no nodes")

    points = np.empty((len(raw_nodes), 3), dtype=np.float64)
    tag_to_index: dict = {}
    for i, n in enumerate(raw_nodes):
        nid = int(n["id"])
        loc = n["location"]
        points[i] = (float(loc[0]), float(loc[1]), float(loc[2]))
        tag_to_index[nid] = i

    cells: list = []
    celltypes: list = []

    for frag in data.get("fragments", []):
        type_name = frag.get("elementType")
        vtk_type = _ELEMENT_TYPE_TO_VTK.get(type_name)
        if vtk_type is None:
            continue
        reorder = _NODE_ORDER_GMSH_TO_VTK.get(type_name)

        for elem in frag.get("elements", []):
            indices = [tag_to_index[int(n)] for n in elem["nodes"]]
            if reorder is not None:
                indices = [indices[j] for j in reorder]
            cells.append(len(indices))
            cells.extend(indices)
            celltypes.append(vtk_type)

    if not celltypes:
        raise ValueError("MeshData has no supported volumetric elements")

    cells_arr = np.array(cells, dtype=np.int64)
    celltypes_arr = np.array(celltypes, dtype=np.uint8)
    return pv.UnstructuredGrid(cells_arr, celltypes_arr, points)


def meshdata_xml_to_dict(path: str) -> dict:
    """Parse a MeshData XML file into the same dict shape as MeshData JSON.

    The returned dict can be fed directly to :func:`meshdata_to_pyvista`.
    Only the fields needed for visualisation (id, owner, nodes, fragments)
    are populated — boundary edges/faces and entity containers are ignored.
    """
    root = _xml_parse(path).getroot()

    nodes = []
    nodes_el = root.find("Nodes")
    if nodes_el is not None:
        for n in nodes_el.findall("N"):
            x, y, z = n.attrib["location"].split()
            nodes.append({
                "id": int(n.attrib["id"]),
                "location": [float(x), float(y), float(z)],
            })

    fragments = []
    for frag_el in root.findall("Fragment"):
        elements = [
            {
                "id": int(e.attrib["id"]),
                "nodes": [int(t) for t in e.attrib["nodes"].split()],
            }
            for e in frag_el.findall("E")
        ]
        fragments.append({
            "elementType": frag_el.attrib.get("elementType", ""),
            "owner": frag_el.attrib.get("owner", ""),
            "elements": elements,
        })

    return {
        "id": int(root.attrib.get("id", 0)),
        "owner": root.attrib.get("owner", ""),
        "nodes": nodes,
        "fragments": fragments,
    }
