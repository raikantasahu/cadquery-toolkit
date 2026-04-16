"""
json_exporter - Save a Gmsh mesh to the cantilever_beam.json format.

Nodes as {id: [x, y, z]}, elements with type/material, and a default
isotropic material entry.  Must be called while Gmsh is initialized and
a mesh has been generated.
"""

import json

import gmsh

# Gmsh element type codes to JSON element type names (3D elements only)
_GMSH_TO_NAME = {
    4: "tet4",
    5: "hex8",
    6: "wedge6",
    7: "pyramid5",
    11: "tet10",
    17: "hex20",
    12: "hex27",
}


def save_as_json(filename: str, title: str = "model") -> None:
    """
    Write the current Gmsh mesh to a JSON file.

    Args:
        filename: Output file path (should end with .json).
        title: Title string for the mesh data.
    """
    # Nodes
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes = {}
    for i, tag in enumerate(node_tags):
        x, y, z = coords[3 * i], coords[3 * i + 1], coords[3 * i + 2]
        nodes[str(int(tag))] = [float(x), float(y), float(z)]

    # 3D elements
    elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(dim=3)
    elements = []
    elem_id = 1
    for etype, enodes in zip(elem_types, elem_node_tags):
        type_name = _GMSH_TO_NAME.get(int(etype))
        if type_name is None:
            continue
        props = gmsh.model.mesh.getElementProperties(int(etype))
        nodes_per_elem = props[3]
        num_elems = len(enodes) // nodes_per_elem
        for i in range(num_elems):
            start = i * nodes_per_elem
            end = start + nodes_per_elem
            element_nodes = [int(n) for n in enodes[start:end]]
            elements.append({
                "id": elem_id,
                "type": type_name,
                "nodes": element_nodes,
                "material": 1,
            })
            elem_id += 1

    with open(filename, "w") as f:
        f.write("{\n")
        f.write(f'  "title": {json.dumps(title)},\n')

        f.write('  "nodes": {\n')
        node_items = list(nodes.items())
        for i, (nid, coords) in enumerate(node_items):
            comma = "," if i < len(node_items) - 1 else ""
            f.write(f"    {json.dumps(nid)}: {json.dumps(coords)}{comma}\n")
        f.write("  },\n")

        f.write('  "elements": [\n')
        for i, elem in enumerate(elements):
            comma = "," if i < len(elements) - 1 else ""
            f.write(f"    {json.dumps(elem)}{comma}\n")
        f.write("  ],\n")

        f.write('  "materials": [\n')
        f.write('    {"id": 1, "type": "isotropic", "E": 200e9, "nu": 0.3}\n')
        f.write("  ]\n")
        f.write("}\n")
