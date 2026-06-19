"""Structured HEX8 extrusion engine, extracted from GmshMesher (Arch-Review T2.4).

Builds a structured all-hex mesh (with wedge degeneracies on triangles) by
quad-meshing a user-specified planar cap face and explicitly sweeping it through
the part's thickness onto the ORIGINAL solid's entities — so ``collect()`` can
emit boundary faces/edges + F/E/V containers keyed to the part's PersistentIDs.

Operates on the active gmsh session (geometry already imported). ``GmshMesher``
owns the steps around the build — geometry import, the hex-validity gate, and
stats collection — and delegates the engine here so it is no longer a ~360-line
responsibility bundled into the mesher class.
"""
import logging
import math
from collections import namedtuple

import gmsh
import numpy as np

from .gmsh_mesher import MeshValidationError, sag_tol_to_elements_per_circle

logger = logging.getLogger(__name__)

# cap↔opposite extrusion topology, resolved from the solid's boundary: the
# volume, the opposite (target) face, the unit extrude direction d (cap normal
# into the solid), the opposite-face plane (q, m), and the cap↔opposite
# correspondence corr_edge / corr_vert.
_ExtrudeTopo = namedtuple(
    "_ExtrudeTopo", "vol opp d q m corr_edge corr_vert")


class ExtrudedHexBuilder:
    """Quad-mesh a cap face and sweep it into structured hex layers.

    Constructed with the resolved ``ExtrusionSpec``, the target element size, an
    optional curvature sag tolerance, and the ``GeometricResolver`` for the
    imported geometry (used to resolve the cap face). ``build()`` leaves the
    swept mesh fully classified on the original solid's entities in the active
    gmsh session, ready for ``collect()``.
    """

    def __init__(self, extrusion: "ExtrusionSpec", element_size: float,
                 relative_sag_tolerance, resolver):
        self.extrusion = extrusion
        self.element_size = element_size
        self.relative_sag_tolerance = relative_sag_tolerance
        self.resolver = resolver

    def build(self) -> None:
        """Resolve cap + topology, quad-mesh the cap, sweep into n hex layers.

        Locates the user-specified cap face, resolves the extrusion topology
        (opposite face + cap↔opposite face/edge/vertex correspondence), 2D-quad-
        meshes the cap, then builds ``num_layers`` uniform layers explicitly and
        assigns them — fully classified — back onto the ORIGINAL solid's
        entities (see :meth:`_build_extruded_mesh`).

        For a true prism the extruded mesh reproduces the solid; for a
        non-prismatic pick :meth:`_extrusion_topology` raises (the cap face is an
        input, not detected). occ.extrude is avoided because its ``numElements``
        is only a soft hint gmsh's 3D mesher ignores (non-uniform layering).
        """
        cap_tag = self._cap_tag()
        topo = self._extrusion_topology(cap_tag)

        # Mesh the cap with quads (+ optional sag), then clear every other
        # entity so only the cap mesh survives — classified on the ORIGINAL cap
        # face/edges/vertices, ready to sweep onto the rest of the solid.
        gmsh.option.setNumber("Mesh.Algorithm", 11)   # quasi-structured quad
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", self.element_size)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        sag = self.relative_sag_tolerance
        if sag and sag > 0:
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", 0.0)
            self._apply_cap_sag_field(cap_tag, self.element_size, sag)
        else:
            gmsh.option.setNumber(
                "Mesh.CharacteristicLengthMin", self.element_size)
        gmsh.model.mesh.setRecombine(2, cap_tag)
        gmsh.model.mesh.generate(2)
        self._clear_non_cap_mesh(cap_tag)

        self._build_extruded_mesh(
            cap_tag, topo, max(1, int(self.extrusion.num_layers)))

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

    def _cap_tag(self) -> int:
        """Resolve the extrusion cap face to a gmsh surface tag.

        Geometric (``cap_face_at`` centroid, resolved via the source-agnostic
        resolver) is preferred; falls back to the legacy ``cap_face`` PID.
        """
        extrusion = self.extrusion
        if extrusion.cap_face_at is not None:
            tags = self.resolver.resolve_face(
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
                # Curvature couldn't be sampled: this curved cap edge is then
                # excluded from sag sizing (no local refinement there). Warn
                # loudly, naming the edge, rather than silently coarsening it.
                logger.warning(
                    "could not sample curvature on cap edge %d; excluding it "
                    "from sag-based sizing", etag, exc_info=True)
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
