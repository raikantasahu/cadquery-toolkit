"""
gmsh_mesher.py - Volumetric mesh generation using Gmsh

Generates 3D (volumetric) meshes from CadQuery models using the Gmsh
meshing engine. Supports first- and second-order tetrahedral and
hexahedral element types.

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
import math
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
    11: 24,  # 10-node tetrahedron (second order)
    17: 25,  # 20-node hexahedron (second order, serendipity)
    12: 29,  # 27-node hexahedron (second order, complete)
}

# Gmsh-to-VTK node reordering for second-order hex elements.
# Gmsh and VTK number mid-edge and mid-face nodes differently.
# Only element types that need reordering are listed here.
_GMSH_TO_VTK_NODE_ORDER = {
    # 20-node hex: corners identical, mid-edge nodes reordered
    17: [0, 1, 2, 3, 4, 5, 6, 7,
         8, 11, 13, 9, 16, 18, 19, 17, 10, 12, 14, 15],
    # 27-node hex: same mid-edge reorder, plus mid-face nodes reordered
    12: [0, 1, 2, 3, 4, 5, 6, 7,
         8, 11, 13, 9, 16, 18, 19, 17, 10, 12, 14, 15,
         22, 23, 21, 24, 20, 25, 26],
}

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


# Reverse mapping: JSON element type name → VTK cell type
_NAME_TO_VTK = {name: _GMSH_TO_VTK[code] for code, name in _GMSH_TO_NAME.items()}


def mesh_json_to_pyvista(data: dict) -> pv.UnstructuredGrid:
    """Convert a mesh JSON dict (nodes/elements) to a PyVista UnstructuredGrid.

    This is the reader counterpart of ``GmshMesher.save_as_json``.

    Args:
        data: Dict with 'nodes' mapping node-id strings to [x,y,z] and
              'elements' listing dicts with 'type' and 'nodes' keys.

    Returns:
        pv.UnstructuredGrid containing the volumetric mesh.
    """
    raw_nodes = data['nodes']
    node_ids = sorted(raw_nodes.keys(), key=lambda k: int(k))
    tag_to_index = {nid: idx for idx, nid in enumerate(node_ids)}
    points = np.array([raw_nodes[nid] for nid in node_ids], dtype=np.float64)

    cells = []
    celltypes = []
    for elem in data['elements']:
        vtk_type = _NAME_TO_VTK.get(elem['type'])
        if vtk_type is None:
            continue
        indices = [tag_to_index[str(n)] for n in elem['nodes']]
        cells.append(len(indices))
        cells.extend(indices)
        celltypes.append(vtk_type)

    cells = np.array(cells, dtype=np.int64)
    celltypes = np.array(celltypes, dtype=np.uint8)

    return pv.UnstructuredGrid(cells, celltypes, points)


def sag_tol_to_elements_per_circle(relative_sag_tol: float,
                                   min_n: int = 8) -> float:
    """Map a relative sag tolerance S = δ/R to Mesh.MeshSizeFromCurvature.

    For a circle of radius R sampled by N equal chords, the max sag is
    δ = R(1 − cos(π/N)). Solving for N gives N = π / arccos(1 − S).
    Result is rounded up and clamped to ``min_n`` to avoid degenerate meshes.

    Returns 0.0 when ``relative_sag_tol`` is non-positive (Gmsh treats 0 as
    disabling curvature-driven sizing).
    """
    if relative_sag_tol <= 0:
        return 0.0
    # Clamp to avoid arccos domain issues if S ≥ 1.
    argument = max(-1.0, min(1.0, 1.0 - relative_sag_tol))
    n = math.pi / math.acos(argument)
    return float(max(min_n, math.ceil(n)))


class MeshType(enum.Enum):
    """Supported volumetric mesh element types."""
    TET4 = "tet4"
    TET10 = "tet10"
    HEX8 = "hex8"
    HEX20 = "hex20"
    HEX27 = "hex27"


_MESH_TYPE_MAP = {
    "tet4": MeshType.TET4,
    "tet10": MeshType.TET10,
    "hex8": MeshType.HEX8,
    "hex20": MeshType.HEX20,
    "hex27": MeshType.HEX27,
}


def create_mesh(model, mesh_type_str, element_size, model_name="model",
                relative_sag_tolerance=None):
    """Generate a volumetric mesh and return the mesher with statistics.

    Args:
        model: A CadQuery Workplane result.
        mesh_type_str: Mesh type key ("tet4", "tet10", "hex8", "hex20", or "hex27").
        element_size: Target element size.
        model_name: Name used for the Gmsh model.
        relative_sag_tolerance: Optional curvature-driven refinement tolerance
            S = δ/R. See ``GmshMesher.generate``.

    Returns:
        Tuple of (GmshMesher, stats_dict). The mesher holds the generated
        mesh and must be consumed by save_mesh() or finalize().
    """
    mesh_type = _MESH_TYPE_MAP[mesh_type_str]
    mesher = GmshMesher(model, model_name=model_name)
    stats = mesher.generate(mesh_type, element_size,
                            relative_sag_tolerance=relative_sag_tolerance)
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


def gmsh_to_pyvista() -> pv.UnstructuredGrid:
    """Extract the current Gmsh model mesh as a PyVista UnstructuredGrid.

    Reads nodes and 3D elements from the active Gmsh session, maps Gmsh
    element types to VTK cell types, and applies node reordering where
    needed (hex20/hex27).

    Must be called while Gmsh is initialized and a mesh has been generated
    or loaded (before ``gmsh.finalize()``).

    Returns:
        pv.UnstructuredGrid containing the volumetric mesh.
    """
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    coords = np.array(coords).reshape(-1, 3)

    tag_to_index = {int(tag): idx for idx, tag in enumerate(node_tags)}

    elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=3)

    cells = []
    celltypes = []

    for etype, node_tags_per_type in zip(elem_types, elem_node_tags):
        vtk_type = _GMSH_TO_VTK.get(int(etype))
        if vtk_type is None:
            continue

        props = gmsh.model.mesh.getElementProperties(int(etype))
        nodes_per_elem = props[3]
        node_order = _GMSH_TO_VTK_NODE_ORDER.get(int(etype))

        node_arr = np.array(node_tags_per_type, dtype=np.int64)
        num_elems = len(node_arr) // nodes_per_elem

        for i in range(num_elems):
            elem_nodes = node_arr[i * nodes_per_elem:(i + 1) * nodes_per_elem]
            indices = [tag_to_index[int(t)] for t in elem_nodes]
            if node_order is not None:
                indices = [indices[j] for j in node_order]
            cells.append(len(indices))
            cells.extend(indices)
            celltypes.append(vtk_type)

    cells = np.array(cells, dtype=np.int64)
    celltypes = np.array(celltypes, dtype=np.uint8)

    return pv.UnstructuredGrid(cells, celltypes, coords)


def generate_pyvista_mesh(model, mesh_type_str, element_size,
                          model_name="model",
                          relative_sag_tolerance=None):
    """Generate a volumetric mesh and return it as a PyVista UnstructuredGrid.

    Args:
        model: A CadQuery Workplane result.
        mesh_type_str: Mesh type key ("tet4", "tet10", "hex8", "hex20", or "hex27").
        element_size: Target element size.
        model_name: Name used for the Gmsh model.
        relative_sag_tolerance: Optional curvature-driven refinement tolerance
            S = δ/R. See ``GmshMesher.generate``.

    Returns:
        pv.UnstructuredGrid containing the volumetric mesh.
    """
    mesher, _ = create_mesh(model, mesh_type_str, element_size, model_name,
                            relative_sag_tolerance=relative_sag_tolerance)
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
                 element_size: float = 5.0,
                 relative_sag_tolerance: float = None) -> dict:
        """
        Generate a volumetric mesh.

        Args:
            mesh_type: Element type (TET4, TET10, HEX8, HEX20, or HEX27).
            element_size: Target element size (upper bound).
            relative_sag_tolerance: Optional curvature-driven refinement.
                S = δ/R, the max allowed sag-to-radius ratio on curved faces.
                When set, enables Gmsh's MeshSizeFromCurvature with N =
                π / arccos(1 − S) elements per 2π radians and relaxes the
                minimum-size clamp so tight curves can actually refine.

        Returns:
            Dictionary with mesh statistics: node_count, element_count,
            element_types.
        """
        gmsh.initialize()
        self._initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(self.model_name)

        self._import_geometry()
        self._configure_mesh(mesh_type, element_size, relative_sag_tolerance)

        gmsh.model.mesh.generate(3)

        return self._collect_mesh_info(mesh_type)

    def get_pyvista_mesh(self) -> pv.UnstructuredGrid:
        """
        Extract the generated mesh as a PyVista UnstructuredGrid.

        Must be called after generate() and before finalize()/save().

        Returns:
            pv.UnstructuredGrid containing the volumetric mesh.
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")

        return gmsh_to_pyvista()

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
        """Write the generated mesh to a JSON file.

        Delegates to :func:`mesher.export.json_exporter.save_as_json`.
        Does NOT finalize Gmsh.
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")
        from .export.json_exporter import save_as_json
        save_as_json(filename, title=title or self.model_name)

    def save_as_meshdata_xml(self, filename: str, mesh_id: int = 1,
                             owner: str = None,
                             entity_owners: dict = None) -> None:
        """Write the generated mesh to a MeshData XML file.

        Delegates to :func:`mesher.export.meshdata_xml_exporter.save_as_meshdata_xml`.
        Does NOT finalize Gmsh.
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")
        from .export.meshdata_xml_exporter import save_as_meshdata_xml
        save_as_meshdata_xml(
            filename, mesh_id=mesh_id,
            owner=owner or self.model_name,
            entity_owners=entity_owners,
        )

    def save_as_meshdata_json(self, filename: str, mesh_id: int = 1,
                              owner: str = None,
                              entity_owners: dict = None) -> None:
        """Write the generated mesh to a MeshData JSON file.

        Delegates to :func:`mesher.export.meshdata_json_exporter.save_as_meshdata_json`.
        Does NOT finalize Gmsh.
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")
        from .export.meshdata_json_exporter import save_as_meshdata_json
        save_as_meshdata_json(
            filename, mesh_id=mesh_id,
            owner=owner or self.model_name,
            entity_owners=entity_owners,
        )

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
                        element_size: float,
                        relative_sag_tolerance: float = None) -> None:
        """Configure Gmsh meshing options based on mesh type and element size."""
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", element_size)

        if relative_sag_tolerance and relative_sag_tolerance > 0:
            n = sag_tol_to_elements_per_circle(relative_sag_tolerance)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", n)
            # Relax the minimum-size clamp so tight curves can refine below
            # element_size * 0.5. Gmsh treats 0 as "no lower bound".
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", 0.0)
        else:
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", element_size * 0.5)

        if mesh_type == MeshType.TET4:
            # Default Delaunay tetrahedral meshing, no recombination
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 0)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 0)
        elif mesh_type == MeshType.TET10:
            # Second-order tetrahedral meshing (10-node tets)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 0)
            gmsh.option.setNumber("Mesh.ElementOrder", 2)
            gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 0)
        elif mesh_type == MeshType.HEX8:
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DLevel", 2)
            # Subdivide tets into hexes to guarantee all-hex output
            gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 2)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 0)
        elif mesh_type == MeshType.HEX20:
            # Second-order serendipity hexahedral meshing (20-node hexes)
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DLevel", 2)
            gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 2)
            gmsh.option.setNumber("Mesh.ElementOrder", 2)
            # Serendipity: drop face/body center nodes (27-node → 20-node)
            gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 1)
        elif mesh_type == MeshType.HEX27:
            # Second-order complete hexahedral meshing (27-node hexes)
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DAll", 1)
            gmsh.option.setNumber("Mesh.Recombine3DLevel", 2)
            gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 2)
            gmsh.option.setNumber("Mesh.ElementOrder", 2)
            gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 0)

    def _collect_mesh_info(self, mesh_type: MeshType = None) -> dict:
        """Collect and return mesh statistics (3D elements only).

        Args:
            mesh_type: The requested mesh type, used to detect whether the
                expected element type was actually produced.
        """
        node_tags, _, _ = gmsh.model.mesh.getNodes()
        element_types, _, _ = gmsh.model.mesh.getElements(dim=3)

        # Expected gmsh element type codes per mesh type
        _expected_codes = {
            MeshType.TET4: {4},
            MeshType.TET10: {11},
            MeshType.HEX8: {5},
            MeshType.HEX20: {17},
            MeshType.HEX27: {12},
        }
        expected = _expected_codes.get(mesh_type, set())

        type_names = []
        total_elements = 0
        found_expected = False
        for etype in element_types:
            name, _, _, num_nodes, _, _ = gmsh.model.mesh.getElementProperties(etype)
            # Count elements of this type across all entities
            tags, _ = gmsh.model.mesh.getElementsByType(etype)
            count = len(tags)
            total_elements += count
            type_names.append(f"{name} ({count})")
            if int(etype) in expected:
                found_expected = True

        stats = {
            "node_count": len(node_tags),
            "element_count": total_elements,
            "element_types": ", ".join(type_names) if type_names else "None",
        }

        if mesh_type and expected and not found_expected and total_elements > 0:
            stats["warning"] = (
                f"Requested {mesh_type.value} elements but none were produced. "
                f"Got: {stats['element_types']}"
            )

        return stats
