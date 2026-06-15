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
from dataclasses import dataclass

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


_MESH_TYPE_MAP = {
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
    cap_face: str
    num_layers: int = 1


def create_mesh(model, mesh_type_str, element_size, model_name="model",
                relative_sag_tolerance=None, extrusion=None):
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
    mesh_type = _MESH_TYPE_MAP[mesh_type_str]
    mesher = GmshMesher(model, model_name=model_name)
    stats = mesher.generate(mesh_type, element_size,
                            relative_sag_tolerance=relative_sag_tolerance,
                            extrusion=extrusion)
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
                            entity_owners=None):
    """Save a generated mesh to a MeshData JSON file.

    Args:
        mesher: A GmshMesher instance returned by create_mesh().
        filename: Output file path (should end with .json).
        owner: Optional owner string for the mesh envelope.
        entity_owners: Optional ``{persistent_id: owner_string}`` mapping
            (e.g. ``{"F0": "Face 1"}``); each entry becomes one
            MeshEntityContainer in the output.
    """
    mesher.save_as_meshdata_json(
        filename, owner=owner, entity_owners=entity_owners,
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

    def generate(self, mesh_type: MeshType = MeshType.TET4,
                 element_size: float = 5.0,
                 relative_sag_tolerance: float = None,
                 extrusion: "ExtrusionSpec" = None) -> dict:
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
            extrusion: Optional ``ExtrusionSpec``. When given, produces
                structured HEX8 by quad-meshing the named cap face and extruding
                it through the thickness (``mesh_type`` is ignored — the result
                is HEX8). ``element_size`` sets the in-plane quad size and
                ``relative_sag_tolerance`` the curved cap-edge fidelity.

        Returns:
            Dictionary with mesh statistics: node_count, element_count,
            element_types.
        """
        gmsh.initialize()
        self._initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(self.model_name)

        if extrusion is not None:
            if mesh_type != MeshType.HEX8:
                raise MeshValidationError(
                    f"extrusion produces hex8 — set mesh_type=hex8 (got "
                    f"'{mesh_type.value}').")
            return self._generate_extruded(
                extrusion, element_size, relative_sag_tolerance)

        self._import_geometry()
        self._configure_mesh(mesh_type, element_size, relative_sag_tolerance)

        gmsh.model.mesh.generate(3)
        self._assert_hex_valid(mesh_type)

        return self._collect_mesh_info(mesh_type)

    def _generate_extruded(self, extrusion: "ExtrusionSpec",
                        element_size: float,
                        relative_sag_tolerance: float = None) -> dict:
        """Structured HEX8 by quad-meshing a cap face and extruding it.

        Imports the solid, locates the user-specified cap face, isolates that
        face as an independent copy, deletes the whole original solid, 2D-quad-
        meshes the copy, and extrudes that mesh into ``num_layers`` uniform hex
        layers along the inward normal (see :meth:`_build_extruded_volume`). For a
        true prism the extruded mesh reproduces the solid; for a non-prismatic pick
        it will not, which is the caller's responsibility (the cap face is an
        input, not detected).

        The original solid is removed *recursively* (not just the volume): its
        other faces are coincident with the extruded volume's walls, and leaving
        them around would pollute the mesh. Copying the cap first keeps a clean
        source that survives the recursive delete.
        """
        self._import_geometry()
        cap_tag = self._surface_tag_for_pid(extrusion.cap_face)
        d, target_q, target_m = self._extrusion_target(cap_tag)

        # Isolate the cap, then delete the entire original solid (volume +
        # all its faces/edges) so ONLY the cap remains to mesh and extrude.
        cap_copy = gmsh.model.occ.copy([(2, cap_tag)])
        gmsh.model.occ.remove(gmsh.model.getEntities(3), recursive=True)
        gmsh.model.occ.synchronize()
        cap = cap_copy[0][1]

        # 2D quad mesh of the cap, with optional curved-edge sag refinement.
        gmsh.option.setNumber("Mesh.Algorithm", 11)   # quasi-structured quad
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", element_size)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        if relative_sag_tolerance and relative_sag_tolerance > 0:
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", 0.0)
            self._apply_cap_sag_field(cap, element_size,
                                      relative_sag_tolerance)
        else:
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", element_size)
        gmsh.model.mesh.setRecombine(2, cap)
        gmsh.model.mesh.generate(2)

        # Extrude the cap mesh into uniform hex layers. occ.extrude's numElements
        # is only a soft hint that gmsh's 3D mesher ignores (it produces
        # non-uniform layering), so we build the layers explicitly.
        self._build_extruded_volume(
            cap, d, target_q, target_m, max(1, int(extrusion.num_layers)))

        self._assert_hex_valid(MeshType.HEX8)
        return self._collect_mesh_info(MeshType.HEX8)

    def _build_extruded_volume(self, cap: int, d, target_q, target_m,
                               n: int) -> None:
        """Extrude the cap's 2D mesh into ``n`` uniform layers of 3D elements.

        Each cap quad becomes a column of ``n`` hexes (each cap triangle, if the
        recombiner left any, a column of ``n`` wedges). Every cap node is
        projected along the extrude direction ``d`` onto the opposite face's
        plane ``(target_q, target_m)``, so the far layer lands exactly on that
        face — and a non-parallel opposite face is handled per node (each column
        gets its own length). Node winding is flipped when needed so every
        element has a positive Jacobian. The result is a discrete volume.
        """
        qtags, qconn = gmsh.model.mesh.getElementsByType(3, cap)   # 4-node quad
        ttags, tconn = gmsh.model.mesh.getElementsByType(2, cap)   # 3-node tri
        qconn = (np.asarray(qconn, dtype=np.int64).reshape(-1, 4)
                 if len(qtags) else np.empty((0, 4), dtype=np.int64))
        tconn = (np.asarray(tconn, dtype=np.int64).reshape(-1, 3)
                 if len(ttags) else np.empty((0, 3), dtype=np.int64))
        if len(qconn) == 0 and len(tconn) == 0:
            raise MeshValidationError(
                "cap face produced no 2D mesh to extrude — check the cap face "
                "and element size.")

        used = np.unique(np.concatenate(
            [qconn.ravel(), tconn.ravel()]).astype(np.int64))
        idx = {int(t): i for i, t in enumerate(used)}
        n_cap = len(used)
        # PERF: this per-node fetch costs ~25 us/node (one Python<->gmsh
        # round-trip each), measured linear. Negligible for typical caps
        # (~100 nodes ~2.5 ms, ~1000 ~25 ms) and only perceptible past ~10k
        # nodes (~40k ~0.65 s, ~200k ~3 s). If very fine caps ever matter,
        # replace this loop with ONE batched call:
        #   _, coords, _ = gmsh.model.mesh.getNodes(2, cap, includeBoundary=True)
        # and build the tag->coord map from the returned arrays (~100x faster
        # at scale; flat ~15-25 ms even at 200k nodes).
        base = np.empty((n_cap, 3))
        for tag in used:
            coord, _, _, _ = gmsh.model.mesh.getNode(int(tag))
            base[idx[int(tag)]] = coord

        # Project each cap node along d onto the opposite-face plane so the far
        # layer lands exactly on that face; ``dist`` is the per-node travel and
        # ``disp`` the per-node displacement to the opposite face.
        d = np.asarray(d, dtype=float)
        target_q = np.asarray(target_q, dtype=float)
        target_m = np.asarray(target_m, dtype=float)
        denom = float(np.dot(d, target_m))
        if abs(denom) < 1e-9:
            raise MeshValidationError(
                "extrude direction is parallel to the opposite face.")
        dist = ((target_q - base) @ target_m) / denom
        if np.any(dist <= 1e-9):
            raise MeshValidationError(
                "some cap nodes do not project onto the opposite face along the "
                "extrude direction — check the cap/part geometry.")
        disp = dist[:, None] * d[None, :]

        # Positive-Jacobian orientation: test one cap face's winding vs d.
        ref = qconn[0] if len(qconn) else tconn[0]
        p0, p1, pl = (base[idx[int(ref[0])]], base[idx[int(ref[1])]],
                      base[idx[int(ref[-1])]])
        flip = float(np.dot(np.cross(p1 - p0, pl - p0), d)) < 0

        # Layered node coordinates; node tag for cap node i at level k = k*N+i+1.
        coords = np.empty(((n + 1) * n_cap, 3))
        for k in range(n + 1):
            coords[k * n_cap:(k + 1) * n_cap] = base + (k / n) * disp

        gmsh.model.occ.remove([(2, cap)], recursive=True)
        gmsh.model.occ.synchronize()
        vol = gmsh.model.addDiscreteEntity(3)
        node_tags = np.arange(1, (n + 1) * n_cap + 1, dtype=np.int64)
        gmsh.model.mesh.addNodes(3, vol, node_tags, coords.ravel())

        def _columns(conn):
            cols = []
            for row in conn:
                b = [idx[int(x)] for x in row]
                if flip:
                    b = b[::-1]
                for k in range(n):
                    cols.append([k * n_cap + i + 1 for i in b]
                                + [(k + 1) * n_cap + i + 1 for i in b])
            return cols

        next_tag = 1
        for conn, etype in ((qconn, 5), (tconn, 6)):   # hex8 / wedge6
            cols = _columns(conn)
            if not cols:
                continue
            flat = np.asarray(cols, dtype=np.int64).ravel()
            etags = np.arange(next_tag, next_tag + len(cols), dtype=np.int64)
            next_tag += len(cols)
            gmsh.model.mesh.addElementsByType(vol, etype, etags, flat)

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

    def _extrusion_target(self, cap_tag: int):
        """Find the extrude direction and the opposite face's plane.

        Returns ``(d, Q, m)``: the unit extrude direction ``d`` (cap normal
        pointing INTO the solid), and the opposite (target) face as a plane
        point ``Q`` and unit normal ``m``. The target is the planar face — other
        than the cap — whose plane is perpendicular to ``d`` (normal parallel to
        ``d``) and that lies farthest along ``d``. Cap nodes are later projected
        onto this plane along ``d`` so the far layer lands exactly on the face
        (see :meth:`_build_extruded_volume`).

        Auto-detected, not user-supplied: the cap plus "extrude through the
        thickness" already determines the opposite face. Raises
        MeshValidationError when there is no opposite planar face, or it isn't
        congruent with the cap (the cap/part isn't a clean extrusion pair).

        NOTE: Slanted opposite faces are NOT currently supported — the opposite
        face must be parallel to the cap (normal ∥ d), so equal-area congruence
        is valid. Supporting a slanted opposite face (detect by "faces away
        along d" + projected-area congruence + per-node travel) is deferred to
        the entity-container phase, together with associating boundary nodes to
        the opposite face's edges/vertices.
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
            faces = [abs(t) for _, t in
                     gmsh.model.getBoundary([(3, vt)], oriented=False)]
            if cap_tag in faces:
                vol, vol_faces = vt, faces
                break
        if vol is None:
            raise MeshValidationError(
                f"capFace tag {cap_tag} is not a face of any solid.")
        into = np.asarray(gmsh.model.occ.getCenterOfMass(3, vol)) - cap_com
        d = n_cap if float(np.dot(into, n_cap)) > 0 else -n_cap

        # Opposite face: planar, plane perpendicular to d (normal ∥ d), farthest
        # along d. Side walls have normals ⊥ d and are skipped.
        target, best_reach = None, None
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
                best_reach, target = reach, ft
        if target is None:
            raise MeshValidationError(
                "no opposite planar face found for the cap — extruded hex needs "
                "a planar cap with a parallel opposite face (is the part "
                "prismatic?).")

        # Congruence: with a parallel opposite face (enforced above), a clean
        # extrusion has cap and opposite face of equal area. (A slanted face
        # would need projected area instead — deferred; see method note.)
        cap_area = gmsh.model.occ.getMass(2, cap_tag)
        tgt_area = gmsh.model.occ.getMass(2, target)
        if abs(cap_area - tgt_area) > 1e-3 * max(cap_area, 1e-12):
            raise MeshValidationError(
                f"cap ({cap_area:.4g}) and opposite face ({tgt_area:.4g}) areas "
                f"differ — not a clean extrusion pair (non-prismatic?).")

        q = np.asarray(gmsh.model.occ.getCenterOfMass(2, target))
        m = np.asarray(
            gmsh.model.getNormal(target, self._face_param_mid(target))[:3],
            dtype=float)
        m /= np.linalg.norm(m)
        return d, q, m

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
