"""
gmsh_mesher.py - Volumetric mesh generation using Gmsh

Generates 3D (volumetric) meshes from CadQuery models using the Gmsh
meshing engine. Supports first- and second-order tetrahedral and
hexahedral element types.

Requirements:
    pip install gmsh>=4.11.0

Usage:
    import cadquery as cq
    from mesher import create_mesh, MeshConfig, MeshType, GmshMesher

    result = cq.Workplane("XY").box(10, 10, 10)
    # Friendly facade (string type + scalars):
    mesher, stats = create_mesh(result, "tet4", 2.0, model_name="MyBox")
    # ...or the typed contract directly:
    mesher = GmshMesher(result, model_name="MyBox")
    stats = mesher.generate(MeshConfig(MeshType.TET4, element_size=2.0))
    mesher.save("mybox.msh")
"""

import enum
import math
import tempfile
import os
from collections import namedtuple
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pyvista as pv

try:
    import gmsh
    HAS_GMSH = True
except ImportError:
    HAS_GMSH = False


class MeshValidationError(RuntimeError):
    """Raised when a generated mesh fails a validity check (e.g. inverted
    elements). Callers should surface the message to the user rather than
    emit a known-invalid mesh."""

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

# Gmsh-to-VTK node reordering for second-order elements.
# Gmsh and VTK number mid-edge and mid-face nodes differently.
# Only element types that need reordering are listed here.
_GMSH_TO_VTK_NODE_ORDER = {
    # 10-node tet: corners + first four mid-edges identical; Gmsh orders
    # the last two mid-edges as (2,3),(1,3) but VTK wants (1,3),(2,3).
    11: [0, 1, 2, 3, 4, 5, 6, 7, 9, 8],
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

# Same Gmsh→VTK node reordering as above, keyed by JSON element type name.
_NAME_TO_VTK_NODE_ORDER = {
    _GMSH_TO_NAME[code]: order
    for code, order in _GMSH_TO_VTK_NODE_ORDER.items()
}


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
        node_order = _NAME_TO_VTK_NODE_ORDER.get(elem['type'])
        if node_order is not None:
            indices = [indices[j] for j in node_order]
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


MESH_TYPES = {
    "tet4": MeshType.TET4,
    "tet10": MeshType.TET10,
    "hex8": MeshType.HEX8,
    "hex20": MeshType.HEX20,
    "hex27": MeshType.HEX27,
}


@dataclass
class ExtrusionSpec:
    """Compound configuration for extruded hex meshing.

    Describes how to build structured hexes by quad-meshing a *cap face* and
    extruding it through the part's thickness, instead of the indirect
    tet-subdivision path. The two settings always travel together:

        cap_face:   PersistentID of the face to extrude from (e.g. ``"F4"``), in
                    the same ``F{n}`` scheme the face picker uses (gmsh surface
                    tag ``n + 1``). The mesher does NOT pick it — it is an input.
        num_layers: number of hex layers through the thickness.

    In-plane quad size comes from ``element_size`` and curved cap-edge fidelity
    from ``relative_sag_tolerance`` (applied locally to the cap), so a full
    extruded-hex job is ``ExtrusionSpec`` + those two scalars.
    """
    cap_face: str = None              # legacy PersistentID ("F4"); or use:
    num_layers: int = 1
    cap_face_at: tuple = None         # cap-face centroid (geometric, preferred)
    cap_face_area: float = None       # optional area for the self-check


@dataclass
class RefinementSpec:
    """Local mesh refinement around an anchor coordinate (tet/recombine path).

    Anchored by COORDINATE, not by a vertex id. An assembly's vertex picker
    numbers vertices in CAD traversal order, which does NOT match gmsh's import
    order, so an id is not a portable anchor across the two — a coordinate is.
    The UI still picks a vertex; its world location becomes ``at``.

    The element size ramps from ``fine_size`` at ``at`` up to the global
    ``element_size`` by ``radius`` away (a gmsh Distance+Threshold field).
    ``scope`` decides which parts it acts on:

        scope="local"   : refine ONLY one part. ``part_index`` (0-based, in gmsh
                          volume order = assembly order) selects it; if None,
                          the part owning the nearest model vertex is used. The
                          field is wrapped in a gmsh Restrict bound to that
                          volume so other parts keep the global size.
        scope="contact" : refine EVERY part near ``at`` — anchored on all model
                          points at that location (one per touching body, e.g.
                          a contact point) and applied globally.

    Fields:
        at:         (x, y, z) anchor coordinate (world space).
        fine_size:  element size at the anchor (Threshold SizeMin).
        radius:     distance over which size relaxes back to ``element_size``
                    (Threshold DistMax / SizeMax).
        scope:      "local" or "contact".
        part_index: 0-based volume to confine local refinement to (optional).
    """
    at: tuple
    fine_size: float
    radius: float
    scope: str = "contact"
    part_index: Optional[int] = None


@dataclass
class MeshConfig:
    """The mesher's unified, typed mesh configuration (Architecture-Review
    T2.2). Replaces the loose scalar+spec argument list ``generate`` used to
    take, so every consumer (GUI, app_cli, mesh_step_model, create_mesh) builds
    the same typed object. References are already resolved to typed specs by the
    caller — ``ExtrusionSpec`` (cap by PID or coordinate) and ``RefinementSpec``
    (anchor coordinate) — so this is source-agnostic.

    Fields:
        mesh_type:              element type (TET4/TET10/HEX8/HEX20/HEX27).
        element_size:           target element size (upper bound).
        relative_sag_tolerance: optional curvature-driven refinement (δ/R).
        extrusion:              optional ExtrusionSpec (-> structured hex8).
        refinements:            local/contact RefinementSpec list (tet/recombine).
    """
    mesh_type: MeshType = MeshType.TET4
    element_size: float = 5.0
    relative_sag_tolerance: Optional[float] = None
    extrusion: Optional["ExtrusionSpec"] = None
    refinements: List["RefinementSpec"] = field(default_factory=list)


# Topology for an extrusion, resolved from the cap face on the original solid.
#   vol        : the solid's volume tag
#   opp        : the opposite (target) face tag
#   d, q, m    : unit extrude direction, opposite-plane point, opposite normal
#   corr_edge  : {cap_edge_tag: (side_face_tag, opposite_edge_tag)}
#   corr_vert  : {cap_vertex_tag: (side_edge_tag, opposite_vertex_tag)}
_ExtrudeTopo = namedtuple(
    "_ExtrudeTopo", "vol opp d q m corr_edge corr_vert")


def create_mesh(model, mesh_type_str, element_size, model_name="model",
                relative_sag_tolerance=None, extrusion=None, refinements=None):
    """Generate a volumetric mesh and return the mesher with statistics.

    Args:
        model: A CadQuery Workplane result.
        mesh_type_str: Mesh type key ("tet4", "tet10", "hex8", "hex20", or "hex27").
        element_size: Target element size.
        model_name: Name used for the Gmsh model.
        relative_sag_tolerance: Optional curvature-driven refinement tolerance
            S = δ/R. See ``GmshMesher.generate``.
        extrusion: Optional ``ExtrusionSpec`` for extruded hex8. See
            ``GmshMesher.generate``.

    Returns:
        Tuple of (GmshMesher, stats_dict). The mesher holds the generated
        mesh and must be consumed by save_mesh() or finalize().
    """
    mesher = GmshMesher(model, model_name=model_name)
    config = MeshConfig(
        mesh_type=MESH_TYPES[mesh_type_str], element_size=element_size,
        relative_sag_tolerance=relative_sag_tolerance,
        extrusion=extrusion, refinements=refinements or [])
    stats = mesher.generate(config)
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


def save_mesh_meshdata_json(mesher, filename, owner=None,
                            entity_owners=None, selections=None):
    """Save a generated mesh to a MeshData JSON file.

    Args:
        mesher: A GmshMesher instance returned by create_mesh().
        filename: Output file path (should end with .json).
        owner: Optional owner string for the mesh envelope.
        selections: Geometric ``(anchor, owner[, required])`` entries resolved to
            entities via the geometric resolver (the source-agnostic owner path).
        entity_owners: Legacy ``{persistent_id: owner_string}`` fallback; each
            entry becomes one MeshEntityContainer in the output.
    """
    mesher.save_as_meshdata_json(
        filename, owner=owner, entity_owners=entity_owners,
        selections=selections,
    )


def save_mesh_meshdata_xml(mesher, filename, owner=None, entity_owners=None):
    """Save a generated mesh to a MeshData XML file.

    Args:
        mesher: A GmshMesher instance returned by create_mesh().
        filename: Output file path (should end with .xml).
        owner: Optional owner string for the mesh envelope.
        entity_owners: Optional ``{persistent_id: owner_string}`` mapping
            (e.g. ``{"F0": "Face 1"}``); each entry becomes one
            MeshEntityContainer in the output.
    """
    mesher.save_as_meshdata_xml(
        filename, owner=owner, entity_owners=entity_owners,
    )


def gmsh_to_pyvista() -> pv.UnstructuredGrid:
    """Extract the current Gmsh model mesh as a PyVista UnstructuredGrid.

    Reads nodes and 3D elements from the active Gmsh session, maps Gmsh
    element types to VTK cell types, and applies node reordering where
    needed (tet10/hex20/hex27).

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
        self._resolver = None   # GeometricResolver, built after geometry import

    def generate(self, config: "MeshConfig") -> dict:
        """
        Generate a volumetric mesh from a unified ``MeshConfig`` (T2.2).

        ``config`` carries the element type, target size, optional curvature
        tolerance (S = δ/R), and already-resolved ``ExtrusionSpec`` /
        ``RefinementSpec`` objects. Extrusion produces structured HEX8 (the
        ``mesh_type`` is then ignored) and is mutually exclusive with
        refinements. Use ``create_mesh`` for the string/scalar facade.

        Returns:
            Dictionary with mesh statistics: node_count, element_count,
            element_types.
        """
        gmsh.initialize()
        self._initialized = True
        # On success the session stays open so the caller can save/collect; on
        # ANY failure (e.g. the MeshValidationError the hex-validity gate
        # raises) tear it down rather than leak an initialized global session +
        # half-built model onto the next generate(). finalize() is idempotent,
        # so a caller's own error handling stays a no-op.
        try:
            return self._run_generate(
                config.mesh_type, config.element_size,
                config.relative_sag_tolerance, config.extrusion,
                config.refinements)
        except Exception:
            self.finalize()
            raise

    def _run_generate(self, mesh_type: MeshType, element_size: float,
                      relative_sag_tolerance, extrusion,
                      refinements) -> dict:
        """Build the mesh in the already-initialized gmsh session.

        Split out of :meth:`generate` so the init + finalize-on-error wrapper
        there stays small; this is the body that runs between them.
        """
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(self.model_name)

        if extrusion is not None:
            if mesh_type != MeshType.HEX8:
                raise MeshValidationError(
                    f"extrusion produces hex8 — set mesh_type=hex8 (got "
                    f"'{mesh_type.value}').")
            if refinements:
                raise MeshValidationError(
                    "local/contact refinement is not supported with extruded "
                    "hex; use a tet or recombined-hex mesh type.")
            return self._generate_extruded(
                extrusion, element_size, relative_sag_tolerance)

        self._import_geometry()
        self._configure_mesh(mesh_type, element_size, relative_sag_tolerance,
                             refinements)
        self._apply_refinement_fields(refinements, element_size)

        gmsh.model.mesh.generate(3)
        self._assert_hex_valid(mesh_type)

        return self._collect_mesh_info(mesh_type)

    def _generate_extruded(self, extrusion: "ExtrusionSpec",
                        element_size: float,
                        relative_sag_tolerance: float = None) -> dict:
        """Structured HEX8 by quad-meshing a cap face and extruding it.

        Locates the user-specified cap face, resolves the extrusion topology
        (opposite face + cap↔opposite face/edge/vertex correspondence), 2D-quad-
        meshes the cap, then builds ``num_layers`` uniform layers explicitly and
        assigns them — fully classified — back onto the ORIGINAL solid's
        entities (see :meth:`_build_extruded_mesh`). Keeping the original solid
        is what lets ``collect()`` emit boundary faces/edges and F/E/V entity
        containers keyed to the part's PersistentIDs.

        For a true prism the extruded mesh reproduces the solid; for a
        non-prismatic pick :meth:`_extrusion_topology` raises (the cap face is an
        input, not detected). occ.extrude is avoided because its ``numElements``
        is only a soft hint gmsh's 3D mesher ignores (non-uniform layering).
        """
        self._import_geometry()
        cap_tag = self._cap_tag(extrusion)
        topo = self._extrusion_topology(cap_tag)

        # Mesh the cap with quads (+ optional sag), then clear every other
        # entity so only the cap mesh survives — classified on the ORIGINAL cap
        # face/edges/vertices, ready to sweep onto the rest of the solid.
        gmsh.option.setNumber("Mesh.Algorithm", 11)   # quasi-structured quad
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", element_size)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        if relative_sag_tolerance and relative_sag_tolerance > 0:
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", 0.0)
            self._apply_cap_sag_field(cap_tag, element_size,
                                      relative_sag_tolerance)
        else:
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", element_size)
        gmsh.model.mesh.setRecombine(2, cap_tag)
        gmsh.model.mesh.generate(2)
        self._clear_non_cap_mesh(cap_tag)

        self._build_extruded_mesh(
            cap_tag, topo, max(1, int(extrusion.num_layers)))

        self._assert_hex_valid(MeshType.HEX8)
        return self._collect_mesh_info(MeshType.HEX8)

    @staticmethod
    def _boundary_tags(dim: int, tag: int) -> list:
        """abs() tags of the (dim-1) boundary entities of (dim, tag)."""
        return [abs(t) for _, t in
                gmsh.model.getBoundary([(dim, tag)], oriented=False)]

    def _clear_non_cap_mesh(self, cap_tag: int) -> None:
        """Clear the mesh from every entity except the cap and its boundary.

        After meshing the whole solid, keep only the cap's mesh (classified on
        the original cap face + its edges + vertices) and empty all other
        surfaces/curves/points, so the extruded mesh can be built onto them.
        Clearing a face leaves its boundary curves/points untouched, so the
        cap's shared boundary survives.
        """
        cap_edges = set(self._boundary_tags(2, cap_tag))
        # Recursive boundary so a closed edge's seam vertex (e.g. a hole circle)
        # is kept, not cleared (it carries a cap mesh node).
        cap_verts = set(abs(t) for dim, t in gmsh.model.getBoundary(
            [(2, cap_tag)], oriented=False, recursive=True) if dim == 0)
        clear = [(2, t) for _, t in gmsh.model.getEntities(2) if t != cap_tag]
        clear += [(1, t) for _, t in gmsh.model.getEntities(1)
                  if t not in cap_edges]
        clear += [(0, t) for _, t in gmsh.model.getEntities(0)
                  if t not in cap_verts]
        gmsh.model.mesh.clear(clear)

    def _build_extruded_mesh(self, cap_tag: int, topo: "_ExtrudeTopo",
                             n: int) -> None:
        """Sweep the cap mesh into n layers, classified onto the solid entities.

        For each cap node, build a column of n+1 levels projected along ``d``
        onto the opposite-face plane (the far level lands exactly on the face).
        Each new node is added to the right ORIGINAL entity by the cap node's
        classification: a cap face-interior node sweeps to the volume (mid
        levels) and the opposite face (top); a cap edge node to the side face
        and the opposite edge; a cap vertex to the side edge and the opposite
        vertex. Elements likewise — cap quads/tris become hex/wedge columns on
        the volume plus a quad/tri on the opposite face; cap edge segments
        become quad strips on the side face plus a line on the opposite edge;
        cap vertices become line strips on the side edge. ``collect()`` then
        emits boundary faces/edges + F/E/V containers keyed to the part's PIDs.
        """
        vol, opp = topo.vol, topo.opp
        d = np.asarray(topo.d, dtype=float)
        q = np.asarray(topo.q, dtype=float)
        m = np.asarray(topo.m, dtype=float)
        corr_edge, corr_vert = topo.corr_edge, topo.corr_vert

        # Cap node classification (hierarchical: vertex < edge < face-interior).
        edge_of = {int(t): e for e in corr_edge
                   for t in gmsh.model.mesh.getNodes(1, e)[0]}
        vert_of = {int(t): v for v in corr_vert
                   for t in gmsh.model.mesh.getNodes(0, v)[0]}

        ntags, ncoords, _ = gmsh.model.mesh.getNodes()
        if len(ntags) == 0:
            raise MeshValidationError("cap face produced no 2D mesh to extrude.")
        coord = {int(t): np.asarray(ncoords[3 * i:3 * i + 3], dtype=float)
                 for i, t in enumerate(ntags)}

        denom = float(np.dot(d, m))
        if abs(denom) < 1e-9:
            raise MeshValidationError(
                "extrude direction is parallel to the opposite face.")

        # Columns: classify the n new nodes per cap node onto original entities.
        next_node = gmsh.model.mesh.getMaxNodeTag() + 1
        column = {}
        add_nodes = {}    # (dim, ent) -> ([tags], [coord floats])
        for tag0, p in coord.items():
            dist = float(np.dot(q - p, m) / denom)
            if dist <= 1e-9:
                raise MeshValidationError(
                    "some cap nodes do not project onto the opposite face along "
                    "the extrude direction — check the cap/part geometry.")
            col = [tag0]
            for k in range(1, n + 1):
                ntag = next_node
                next_node += 1
                c = p + (k / n) * dist * d
                if tag0 in vert_of:
                    se, ov = corr_vert[vert_of[tag0]]
                    ent = (0, ov) if k == n else (1, se)
                elif tag0 in edge_of:
                    sf, oe = corr_edge[edge_of[tag0]]
                    ent = (1, oe) if k == n else (2, sf)
                else:
                    ent = (2, opp) if k == n else (3, vol)
                bucket = add_nodes.setdefault(ent, ([], []))
                bucket[0].append(ntag)
                bucket[1].extend(c.tolist())
                col.append(ntag)
            column[tag0] = col
        for (dim, ent), (tags, cs) in add_nodes.items():
            gmsh.model.mesh.addNodes(dim, ent, tags, cs)

        # Build + classify elements.
        next_elem = gmsh.model.mesh.getMaxElementTag() + 1
        add_elems = {}    # (ent, etype) -> ([tags], [node tags])

        def emit(ent, etype, nodes):
            nonlocal next_elem
            bucket = add_elems.setdefault((ent, etype), ([], []))
            bucket[0].append(next_elem)
            next_elem += 1
            bucket[1].extend(nodes)

        # Cap quads -> hex columns; cap tris -> wedge columns; + opposite face.
        # Record each cap cell's nodes by boundary edge so the side-face strips
        # below can be wound outward: a cell centroid is a point just inside the
        # solid, taken locally per edge so holes / non-convex caps still orient
        # correctly (a single global centroid would mis-orient hole walls).
        cap_cell_of_edge = {}
        for cap_etype, vol_etype in ((3, 5), (2, 6)):   # quad/hex8, tri/wedge6
            etags, econn = gmsh.model.mesh.getElementsByType(cap_etype, cap_tag)
            if len(etags) == 0:
                continue
            npe = 4 if cap_etype == 3 else 3
            econn = np.asarray(econn, dtype=np.int64).reshape(-1, npe)
            ref = econn[0]
            p0, p1, pl = (coord[int(ref[0])], coord[int(ref[1])],
                          coord[int(ref[-1])])
            flip = float(np.dot(np.cross(p1 - p0, pl - p0), d)) < 0
            for row in econn:
                b = [int(x) for x in row]
                if flip:
                    b = b[::-1]
                for i in range(npe):
                    cap_cell_of_edge[frozenset((b[i], b[(i + 1) % npe]))] = b
                for k in range(n):
                    emit(vol, vol_etype, [column[t][k] for t in b]
                         + [column[t][k + 1] for t in b])
                emit(opp, cap_etype, [column[t][n] for t in b])

        # Cap edge segments -> side-face quad strips + opposite-edge lines.
        # gmsh gives each cap edge an arbitrary segment direction, so wind every
        # side quad explicitly: its normal (edge x extrude-dir) must point away
        # from the adjacent cap cell's centroid, i.e. outward from the solid.
        for e, (sf, oe) in corr_edge.items():
            stags, sconn = gmsh.model.mesh.getElementsByType(1, e)
            if len(stags) == 0:
                continue
            for seg in np.asarray(sconn, dtype=np.int64).reshape(-1, 2):
                a, b = int(seg[0]), int(seg[1])
                cell = cap_cell_of_edge.get(frozenset((a, b)))
                if cell is not None:
                    outward = (0.5 * (coord[a] + coord[b])
                               - np.mean([coord[t] for t in cell], axis=0))
                    if float(np.dot(np.cross(coord[b] - coord[a], d),
                                    outward)) < 0:
                        a, b = b, a
                for k in range(n):
                    emit(sf, 3, [column[a][k], column[b][k],
                                 column[b][k + 1], column[a][k + 1]])
                emit(oe, 1, [column[a][n], column[b][n]])

        # Cap vertices -> side-edge line strips.
        for v, (se, _ov) in corr_vert.items():
            for k in range(n):
                emit(se, 1, [column[v][k], column[v][k + 1]])

        for (ent, etype), (tags, conn) in add_elems.items():
            gmsh.model.mesh.addElementsByType(ent, etype, tags, conn)

    def _cap_tag(self, extrusion: "ExtrusionSpec") -> int:
        """Resolve the extrusion cap face to a gmsh surface tag.

        Geometric (``cap_face_at`` centroid, resolved via the source-agnostic
        resolver) is preferred; falls back to the legacy ``cap_face`` PID.
        """
        if extrusion.cap_face_at is not None:
            tags = self._resolver.resolve_face(
                extrusion.cap_face_at, area=extrusion.cap_face_area)
            if len(tags) != 1:
                raise MeshValidationError(
                    f"cap-face anchor {tuple(extrusion.cap_face_at)} resolved to "
                    f"{tags} (expected exactly one face).")
            return tags[0]
        if extrusion.cap_face is None:
            raise MeshValidationError(
                "extrusion needs a cap face: cap_face_at (centroid) or cap_face.")
        return self._surface_tag_for_pid(extrusion.cap_face)

    def _surface_tag_for_pid(self, pid: str) -> int:
        """Map a CADModelData face PersistentID ('F{n}') to its gmsh tag (n+1)."""
        if not (isinstance(pid, str) and pid[:1].upper() == "F"
                and pid[1:].isdigit()):
            raise MeshValidationError(
                f"capFace must be a face PersistentID like 'F4', got {pid!r}.")
        tag = int(pid[1:]) + 1
        if (2, tag) not in gmsh.model.getEntities(2):
            raise MeshValidationError(
                f"capFace {pid!r} (surface tag {tag}) not found in geometry.")
        return tag

    @staticmethod
    def _face_param_mid(tag: int) -> list:
        """Parametric midpoint [u, v] of a surface, for getNormal sampling."""
        pmin, pmax = gmsh.model.getParametrizationBounds(2, tag)
        return [(pmin[0] + pmax[0]) / 2.0, (pmin[1] + pmax[1]) / 2.0]

    def _extrusion_topology(self, cap_tag: int) -> "_ExtrudeTopo":
        """Resolve the extrusion topology from the cap face (on the solid).

        Returns an ``_ExtrudeTopo``: the volume, the opposite (target) face,
        the unit extrude direction ``d`` (cap normal INTO the solid), the
        opposite-face plane ``(q, m)``, and the cap↔opposite correspondence —
        ``corr_edge`` (cap edge → side face + opposite edge) and ``corr_vert``
        (cap vertex → side edge + opposite vertex). The extruded mesh is
        assigned back onto these entities so ``collect()`` emits boundary
        faces/edges + F/E/V containers keyed to the part's PIDs.

        Auto-detected, not user-supplied: the cap plus "extrude through the
        thickness" already determines the rest. Raises MeshValidationError for a
        non-planar cap, no parallel opposite face, an incongruent pair, or a
        boundary that doesn't correspond (i.e. a non-prismatic part).

        NOTE: parallel opposite faces only (normal ∥ d), so equal-area
        congruence is valid. Slanted opposite faces are not yet supported.
        """
        cap_type = gmsh.model.getType(2, cap_tag)
        if cap_type != "Plane":
            raise MeshValidationError(
                f"cap face must be planar to extrude; got '{cap_type}'. Pick a "
                f"flat face (extruding a curved face is not supported).")
        n_cap = np.asarray(
            gmsh.model.getNormal(cap_tag, self._face_param_mid(cap_tag))[:3],
            dtype=float)
        n_cap /= np.linalg.norm(n_cap)
        cap_com = np.asarray(gmsh.model.occ.getCenterOfMass(2, cap_tag))

        vol, vol_faces = None, []
        for _, vt in gmsh.model.getEntities(3):
            faces = self._boundary_tags(3, vt)
            if cap_tag in faces:
                vol, vol_faces = vt, faces
                break
        if vol is None:
            raise MeshValidationError(
                f"capFace tag {cap_tag} is not a face of any solid.")
        into = np.asarray(gmsh.model.occ.getCenterOfMass(3, vol)) - cap_com
        d = n_cap if float(np.dot(into, n_cap)) > 0 else -n_cap

        # Opposite face: planar, normal ∥ d, farthest along d (side walls ⊥ d).
        opp, best_reach = None, None
        for ft in vol_faces:
            if ft == cap_tag or gmsh.model.getType(2, ft) != "Plane":
                continue
            fn = np.asarray(
                gmsh.model.getNormal(ft, self._face_param_mid(ft))[:3],
                dtype=float)
            fn /= np.linalg.norm(fn)
            # Parallel-only: require the face normal ∥ d. A slanted opposite
            # face (tilted normal) is intentionally skipped — see method note.
            if abs(float(np.dot(fn, d))) < 0.999:
                continue
            reach = float(np.dot(
                np.asarray(gmsh.model.occ.getCenterOfMass(2, ft)), d))
            if best_reach is None or reach > best_reach:
                best_reach, opp = reach, ft
        if opp is None:
            raise MeshValidationError(
                "no opposite planar face found for the cap — extruded hex needs "
                "a planar cap with a parallel opposite face (is the part "
                "prismatic?).")

        # Congruence: with a parallel opposite face (enforced above), a clean
        # extrusion has cap and opposite face of equal area. (A slanted face
        # would need projected area instead — deferred; see method note.)
        cap_area = gmsh.model.occ.getMass(2, cap_tag)
        opp_area = gmsh.model.occ.getMass(2, opp)
        if abs(cap_area - opp_area) > 1e-3 * max(cap_area, 1e-12):
            raise MeshValidationError(
                f"cap ({cap_area:.4g}) and opposite face ({opp_area:.4g}) areas "
                f"differ — not a clean extrusion pair (non-prismatic?).")

        q = np.asarray(gmsh.model.occ.getCenterOfMass(2, opp))
        m = np.asarray(
            gmsh.model.getNormal(opp, self._face_param_mid(opp))[:3], dtype=float)
        m /= np.linalg.norm(m)

        # cap↔opposite correspondence from the solid's boundary topology.
        opp_edges = set(self._boundary_tags(2, opp))
        corr_edge = {}
        for e in self._boundary_tags(2, cap_tag):
            sides = [f for f in gmsh.model.getAdjacencies(1, e)[0]
                     if f != cap_tag]
            oes = ([x for x in self._boundary_tags(2, sides[0])
                    if x in opp_edges] if sides else [])
            if not sides or not oes:
                raise MeshValidationError(
                    "a cap edge has no matching side face / opposite edge — the "
                    "part is not a clean extrusion (non-prismatic?).")
            corr_edge[e] = (sides[0], oes[0])

        # Cap vertices from the face's RECURSIVE boundary, not the edges' — a
        # closed edge (e.g. a hole circle) has a seam vertex that getBoundary of
        # the edge omits; missing it would misclassify that node onto the face.
        cap_eset = set(corr_edge)
        cap_verts = set(abs(t) for dim, t in gmsh.model.getBoundary(
            [(2, cap_tag)], oriented=False, recursive=True) if dim == 0)
        corr_vert = {}
        for v in cap_verts:
            sides = [c for c in gmsh.model.getAdjacencies(0, v)[0]
                     if c not in cap_eset]
            ovs = ([x for x in self._boundary_tags(1, sides[0])
                    if x != v] if sides else [])
            if not sides or not ovs:
                raise MeshValidationError(
                    "a cap vertex has no matching side edge / opposite vertex — "
                    "the part is not a clean extrusion (non-prismatic?).")
            corr_vert[v] = (sides[0], ovs[0])

        return _ExtrudeTopo(vol=vol, opp=opp, d=d, q=q, m=m,
                            corr_edge=corr_edge, corr_vert=corr_vert)

    def _apply_cap_sag_field(self, cap_tag: int, element_size: float,
                             sag: float) -> None:
        """Refine the cap's curved boundary edges to the sag tolerance locally.

        A Distance+Threshold background field sizes the curved edges to
        ``2πR / N`` (N = elements-per-circle from the sag tolerance) while flat
        regions stay at ``element_size``. This gives geometric fidelity on
        holes/fillets without uniformly refining the whole cap.
        """
        n_per_circle = sag_tol_to_elements_per_circle(sag)
        curved, sizes = [], []
        for _, etag in gmsh.model.getBoundary([(2, cap_tag)], oriented=False):
            etag = abs(etag)
            if gmsh.model.getType(1, etag) == "Line":
                continue
            curved.append(etag)
            try:
                b = gmsh.model.getParametrizationBounds(1, etag)
                kappa = abs(gmsh.model.getCurvature(
                    1, etag, [(b[0][0] + b[1][0]) / 2.0])[0])
            except Exception:
                kappa = 0.0
            if kappa > 1e-9:
                sizes.append(2.0 * math.pi * (1.0 / kappa) / n_per_circle)
        if not curved or not sizes:
            return
        fd = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(fd, "CurvesList", curved)
        gmsh.model.mesh.field.setNumber(fd, "Sampling", 200)
        ft = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(ft, "InField", fd)
        gmsh.model.mesh.field.setNumber(ft, "SizeMin", min(sizes))
        gmsh.model.mesh.field.setNumber(ft, "SizeMax", element_size)
        gmsh.model.mesh.field.setNumber(ft, "DistMin", 0.0)
        gmsh.model.mesh.field.setNumber(ft, "DistMax", element_size * 2.0)
        gmsh.model.mesh.field.setAsBackgroundMesh(ft)

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
                             entity_owners: dict = None,
                             selections: list = None) -> None:
        """Write the generated mesh to a MeshData XML file.

        ``selections`` are geometric owner entries resolved via the geometric
        resolver; ``entity_owners`` is the legacy PersistentID fallback.
        Delegates to the XML exporter; does NOT finalize Gmsh.
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")
        owner_by_tag = (self._resolver.build_owner_map(selections)
                        if selections else None)
        from .export.meshdata_xml_exporter import save_as_meshdata_xml
        save_as_meshdata_xml(
            filename, mesh_id=mesh_id,
            owner=owner or self.model_name,
            entity_owners=entity_owners,
            owner_by_tag=owner_by_tag,
        )

    def save_as_meshdata_json(self, filename: str, mesh_id: int = 1,
                              owner: str = None,
                              entity_owners: dict = None,
                              selections: list = None) -> None:
        """Write the generated mesh to a MeshData JSON file.

        ``selections`` are geometric ``(anchor, owner[, required])`` entries
        resolved to entities via the geometric resolver — the source-agnostic
        owner path. ``entity_owners`` is the legacy PersistentID fallback.
        Delegates to the JSON exporter; does NOT finalize Gmsh.
        """
        if not self._initialized:
            raise RuntimeError("No mesh generated yet. Call generate() first.")
        owner_by_tag = (self._resolver.build_owner_map(selections)
                        if selections else None)
        from .export.meshdata_json_exporter import save_as_meshdata_json
        save_as_meshdata_json(
            filename, mesh_id=mesh_id,
            owner=owner or self.model_name,
            entity_owners=entity_owners,
            owner_by_tag=owner_by_tag,
        )

    def _import_geometry(self) -> None:
        """Export CadQuery object to a temporary STEP file and import into Gmsh.

        Type-dispatched: ``cq.exporters.export(..., STEP)`` raises a
        DispatchError on ``cq.Assembly`` inputs in some cadquery versions
        (no Assembly overload registered on the generic dispatcher), so
        Assembly is routed explicitly through ``exportAssembly``.
        """
        import cadquery as cq

        with tempfile.NamedTemporaryFile(
            suffix=".step", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            if isinstance(self.cq_object, cq.Assembly):
                from cadquery.occ_impl.exporters.assembly import exportAssembly
                exportAssembly(self.cq_object, tmp_path)
            else:
                cq.exporters.export(
                    self.cq_object, tmp_path, cq.exporters.ExportTypes.STEP
                )
            gmsh.merge(tmp_path)
            gmsh.model.occ.synchronize()
        finally:
            os.unlink(tmp_path)

        # Index the imported geometry so geometric selections can be resolved to
        # entities (source-agnostic identity; tags persist through meshing).
        from .resolver import GeometricResolver
        self._resolver = GeometricResolver()

    def _configure_mesh(self, mesh_type: MeshType,
                        element_size: float,
                        relative_sag_tolerance: float = None,
                        refinements: Optional[List["RefinementSpec"]] = None
                        ) -> None:
        """Configure Gmsh meshing options based on mesh type and element size."""
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", element_size)

        if relative_sag_tolerance and relative_sag_tolerance > 0:
            n = sag_tol_to_elements_per_circle(relative_sag_tolerance)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", n)
            # Relax the minimum-size clamp so tight curves can refine below
            # element_size * 0.5. Gmsh treats 0 as "no lower bound".
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", 0.0)
        elif refinements:
            # Refinement fields prescribe sizes well below element_size; relax
            # the lower clamp (0 = no bound) so they are not clamped back up.
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

    def _apply_refinement_fields(
            self, refinements: Optional[List["RefinementSpec"]],
            element_size: float) -> None:
        """Build local/contact refinement size fields and set them as the mesh
        size background (combined via a single Min field).

        Each spec becomes a Distance+Threshold field, optionally wrapped in a
        Restrict field (local scope). A final Min field combines them; gmsh
        further takes the min with its own curvature/boundary sizing, so this
        coexists with ``relativeSagTolerance``. No-op when there are no specs.
        """
        if not refinements:
            return
        field_tags = [self._build_refinement_field(spec, element_size)
                      for spec in refinements]
        fmin = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(fmin, "FieldsList", field_tags)
        gmsh.model.mesh.field.setAsBackgroundMesh(fmin)

    def _build_refinement_field(self, spec: "RefinementSpec",
                                element_size: float) -> int:
        """Build one refinement field from a ``RefinementSpec``; return its tag.

        Distance (from the anchor point set) -> Threshold (graded size), and for
        ``scope="local"`` a Restrict that confines it to one part's volume.
        """
        if spec.fine_size <= 0 or spec.radius <= 0:
            raise MeshValidationError(
                "refinement fine_size and radius must be positive.")
        from .resolver import EntityResolutionError

        # Anchor by coordinate via the shared geometric resolver (namespace-
        # independent; returns the whole coincident set, one vertex per body).
        try:
            near = self._resolver.resolve_vertex(spec.at)
        except EntityResolutionError:
            raise MeshValidationError(
                f"refinement anchor {tuple(spec.at)} matches no model vertex.")

        target_vol = None
        if spec.scope == "contact":
            # Every point at the anchor (one per body meeting there) so all
            # touching parts refine from a single picked vertex.
            points = near
        elif spec.scope == "local":
            if spec.part_index is not None:
                vols = gmsh.model.getEntities(3)
                if not 0 <= spec.part_index < len(vols):
                    raise MeshValidationError(
                        f"refinement part_index {spec.part_index} out of range "
                        f"(0..{len(vols) - 1}).")
                target_vol = vols[spec.part_index][1]
                try:
                    points = self._resolver.resolve_vertex(
                        spec.at, volume=target_vol)
                except EntityResolutionError:
                    raise MeshValidationError(
                        f"refinement anchor {tuple(spec.at)} has no vertex on "
                        f"part {spec.part_index}.")
            else:
                points = near[:1]
                target_vol = next(
                    iter(self._resolver.volumes_of_vertex(points[0])), None)
        else:
            raise MeshValidationError(
                f"refinement scope must be 'local' or 'contact', "
                f"got {spec.scope!r}.")

        fd = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(fd, "PointsList", points)
        ft = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(ft, "InField", fd)
        gmsh.model.mesh.field.setNumber(ft, "SizeMin", spec.fine_size)
        gmsh.model.mesh.field.setNumber(ft, "SizeMax", element_size)
        gmsh.model.mesh.field.setNumber(ft, "DistMin", 0.0)
        gmsh.model.mesh.field.setNumber(ft, "DistMax", spec.radius)
        if spec.scope != "local":
            return ft

        if target_vol is None:
            raise MeshValidationError(
                f"local refinement anchor {tuple(spec.at)} is not on any part "
                f"(volume).")
        fr = gmsh.model.mesh.field.add("Restrict")
        gmsh.model.mesh.field.setNumber(fr, "InField", ft)
        gmsh.model.mesh.field.setNumbers(fr, "VolumesList", [target_vol])
        return fr

    # All hex types share the recombine-from-tet-subdivision path and the
    # same curvature-under-resolution failure mode (verified for HEX8/20/27).
    _HEX_TYPES = (MeshType.HEX8, MeshType.HEX20, MeshType.HEX27)

    def _assert_hex_valid(self, mesh_type: MeshType) -> None:
        """Fail if a hex mesh (HEX8/HEX20/HEX27) contains inverted elements.

        The hex path recombines a subdivided tet mesh, which guarantees
        all-hex *topology* but not *validity*: where the underlying tet mesh
        is coarse in high-curvature regions, the split hexes can be inverted
        (negative scaled Jacobian) — invalid for FEA. The root-cause fix is
        resolution: with ``relativeSagTolerance`` (or a smaller elementSize)
        the curvature is resolved and the inversions disappear at the source —
        verified for all three hex orders (see docs/plans/Hex8-Mesh-Quality.md).
        So rather than mask an under-resolved mesh, we refuse to emit it.
        No-op for tet meshes.
        """
        if mesh_type not in self._HEX_TYPES:
            return
        tags = []
        etypes, _, _ = gmsh.model.mesh.getElements(dim=3)
        for et in etypes:
            t, _ = gmsh.model.mesh.getElementsByType(int(et))
            tags.extend(int(x) for x in t)
        if not tags:
            return
        qualities = gmsh.model.mesh.getElementQualities(tags, "minSICN")
        inverted = sum(1 for v in qualities if v < 0.0)
        if inverted:
            raise MeshValidationError(
                f"{mesh_type.value} mesh has {inverted} inverted element(s) "
                f"(negative Jacobian) of {len(tags)} — invalid for analysis. "
                f"This is curvature under-resolution. Increase resolution: "
                f"set relativeSagTolerance (e.g. 0.01) or reduce elementSize."
            )

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
