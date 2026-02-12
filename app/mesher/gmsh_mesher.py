"""
gmsh_mesher.py - Volumetric mesh generation using Gmsh

Generates 3D (volumetric) meshes from CadQuery models using the Gmsh
meshing engine. Supports tetrahedral, hexahedral, and mixed element types.

Requirements:
    pip install gmsh>=4.11.0

Usage:
    import cadquery as cq
    from mesher import GmshMesher, MeshType

    result = cq.Workplane("XY").box(10, 10, 10)
    mesher = GmshMesher(result, model_name="MyBox")
    stats = mesher.generate(MeshType.TET4, element_size=2.0)
    mesher.save("mybox.msh")
"""

import enum
import json
import tempfile
import os

import numpy as np
import pyvista as pv

try:
    import gmsh
    HAS_GMSH = True
except ImportError:
    HAS_GMSH = False

# Gmsh element type codes to VTK cell type mapping (3D elements only)
_GMSH_TO_VTK = {
    4: 10,   # 4-node tetrahedron
    5: 12,   # 8-node hexahedron
    6: 13,   # 6-node wedge (prism)
    7: 14,   # 5-node pyramid
}

# Gmsh element type codes to JSON element type names (3D elements only)
_GMSH_TO_NAME = {
    4: "tet4",
    5: "hex8",
    6: "wedge6",
    7: "pyramid5",
}


class MeshType(enum.Enum):
    """Supported volumetric mesh element types."""
    TET4 = "tet4"
    HEX8 = "hex8"
    MIXED = "mixed"


_MESH_TYPE_MAP = {
    "tet4": MeshType.TET4,
    "hex8": MeshType.HEX8,
    "mixed": MeshType.MIXED,
}


def create_mesh(model, mesh_type_str, element_size, model_name="model"):
    """Generate a volumetric mesh and return the mesher with statistics.

    Args:
        model: A CadQuery Workplane result.
        mesh_type_str: Mesh type key ("tet4", "hex8", or "mixed").
        element_size: Target element size.
        model_name: Name used for the Gmsh model.

    Returns:
        Tuple of (GmshMesher, stats_dict). The mesher holds the generated
        mesh and must be consumed by save_mesh() or finalize().
    """
    mesh_type = _MESH_TYPE_MAP[mesh_type_str]
    mesher = GmshMesher(model, model_name=model_name)
    stats = mesher.generate(mesh_type, element_size)
    return mesher, stats


def save_mesh(mesher, filename):
    """Save a generated mesh to a .msh file.

    Args:
        mesher: A GmshMesher instance returned by create_mesh().
        filename: Output file path (should end with .msh).
    """
    mesher.save(filename)


def save_mesh_json(mesher, filename, title=None):
    """Save a generated mesh to a JSON file.

    Args:
        mesher: A GmshMesher instance returned by create_mesh().
        filename: Output file path (should end with .json).
        title: Optional title for the mesh data.
    """
    mesher.save_as_json(filename, title=title)


def generate_pyvista_mesh(model, mesh_type_str, element_size,
                          model_name="model"):
    """Generate a volumetric mesh and return it as a PyVista UnstructuredGrid.

    Args:
        model: A CadQuery Workplane result.
        mesh_type_str: Mesh type key ("tet4", "hex8", or "mixed").
        element_size: Target element size.
        model_name: Name used for the Gmsh model.

    Returns:
        pv.UnstructuredGrid containing the volumetric mesh.
    """
    mesher, _ = create_mesh(model, mesh_type_str, element_size, model_name)
    ugrid = mesher.get_pyvista_mesh()
    mesher.finalize()
    return ugrid


class GmshMesher:
    """
    Generates volumetric meshes from CadQuery objects using Gmsh.

    Args:
        cadquery_object: A CadQuery Workplane result.
        model_name: Name used for the Gmsh model.
    """

    def __init__(self, cadquery_object, model_name: str = "model"):
        if not HAS_GMSH:
            raise RuntimeError(
                "Gmsh is not installed. Install it with: pip install gmsh"
            )
        self.cq_object = cadquery_object
        self.model_name = model_name
        self._initialized = False

    def generate(self, mesh_type: MeshType = MeshType.TET4,
                 element_size: float = 5.0) -> dict:
        """
        Generate a volumetric mesh.

        Args:
            mesh_type: Element type (TET4, HEX8, or MIXED).
            element_size: Target element size.

        Returns:
            Dictionary with mesh statistics: node_count, element_count,
            element_types.
        """
        gmsh.initialize()
        self._initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(self.model_name)

        self._import_geometry()
        self._configure_mesh(mesh_type, element_size)

        gmsh.model.mesh.generate(3)

        return self._collect_mesh_info()

    def get_pyvista_mesh(self) -> pv.UnstructuredGrid:
        """
        Extract the generated mesh as a PyVista UnstructuredGrid.

        Must be called after generate() and before finalize()/save().

        Returns:
            pv.UnstructuredGrid containing the volumetric mesh.
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")

        # Get all nodes
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        coords = np.array(coords).reshape(-1, 3)

        # Build node-tag-to-index mapping (gmsh tags can be non-contiguous)
        tag_to_index = {int(tag): idx for idx, tag in enumerate(node_tags)}

        # Get 3D elements only
        elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=3)

        cells = []
        celltypes = []

        for etype, node_tags_per_type in zip(elem_types, elem_node_tags):
            vtk_type = _GMSH_TO_VTK.get(int(etype))
            if vtk_type is None:
                continue

            props = gmsh.model.mesh.getElementProperties(int(etype))
            nodes_per_elem = props[3]

            node_arr = np.array(node_tags_per_type, dtype=np.int64)
            num_elems = len(node_arr) // nodes_per_elem

            for i in range(num_elems):
                elem_nodes = node_arr[i * nodes_per_elem:(i + 1) * nodes_per_elem]
                indices = [tag_to_index[int(t)] for t in elem_nodes]
                cells.append(len(indices))
                cells.extend(indices)
                celltypes.append(vtk_type)

        cells = np.array(cells, dtype=np.int64)
        celltypes = np.array(celltypes, dtype=np.uint8)

        return pv.UnstructuredGrid(cells, celltypes, coords)

    def finalize(self) -> None:
        """Finalize Gmsh without saving. Use for view-only flows."""
        if self._initialized:
            gmsh.finalize()
            self._initialized = False

    def save(self, filename: str) -> None:
        """
        Write the generated mesh to a .msh file.

        Does NOT finalize Gmsh — the mesh stays available for further
        saves or viewing. Call finalize() when done.

        Args:
            filename: Output file path (should end with .msh).
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")
        gmsh.write(filename)

    def save_as_json(self, filename: str, title: str = None) -> None:
        """
        Write the generated mesh to a JSON file.

        Output structure matches the cantilever_beam.json format:
        nodes as {id: [x, y, z]}, elements with type/material, and
        a default isotropic material entry.

        Does NOT finalize Gmsh.

        Args:
            filename: Output file path (should end with .json).
            title: Optional title string. Defaults to the model name.
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")

        # Nodes
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        nodes = {}
        for i, tag in enumerate(node_tags):
            x, y, z = coords[3 * i], coords[3 * i + 1], coords[3 * i + 2]
            nodes[str(int(tag))] = [float(x), float(y), float(z)]

        # 3D elements
        elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=3)
        elements = []
        elem_id = 1
        for etype, etags, enodes in zip(elem_types, elem_tags, elem_node_tags):
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
            f.write(f'  "title": {json.dumps(title or self.model_name)},\n')

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

    def _import_geometry(self) -> None:
        """Export CadQuery object to a temporary STEP file and import into Gmsh."""
        import cadquery as cq

        with tempfile.NamedTemporaryFile(
            suffix=".step", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            cq.exporters.export(self.cq_object, tmp_path, cq.exporters.ExportTypes.STEP)
            gmsh.merge(tmp_path)
            gmsh.model.occ.synchronize()
        finally:
            os.unlink(tmp_path)

    def _configure_mesh(self, mesh_type: MeshType,
                        element_size: float) -> None:
        """Configure Gmsh meshing options based on mesh type and element size."""
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", element_size * 0.5)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", element_size)

        if mesh_type == MeshType.TET4:
            # Default Delaunay tetrahedral meshing, no recombination
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
        elif mesh_type == MeshType.HEX8:
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DLevel", 2)
        elif mesh_type == MeshType.MIXED:
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DLevel", 0)

    def _collect_mesh_info(self) -> dict:
        """Collect and return mesh statistics."""
        node_tags, _, _ = gmsh.model.mesh.getNodes()
        element_types, _, _ = gmsh.model.mesh.getElements()

        # Map Gmsh element type codes to names
        type_names = []
        total_elements = 0
        for etype in element_types:
            name, _, _, num_nodes, _, _ = gmsh.model.mesh.getElementProperties(etype)
            # Count elements of this type across all entities
            tags, _ = gmsh.model.mesh.getElementsByType(etype)
            count = len(tags)
            total_elements += count
            type_names.append(f"{name} ({count})")

        return {
            "node_count": len(node_tags),
            "element_count": total_elements,
            "element_types": ", ".join(type_names),
        }
