"""Geometric entity resolver — source-agnostic identity for the mesher.

Resolves a geometric *anchor* (a coordinate, edge sample points, or a face
centroid+area) to the gmsh entity tag(s) it denotes, independent of any tool- or
app-specific numbering. This is the single mechanism every entity-identity
consumer (owner containers, cap face, refinement) routes through. See
docs/plans/Geometric-Entity-Identification/.

Operates on the *current* gmsh model: the caller must have imported geometry and
called gmsh.model.occ.synchronize() before constructing a resolver. gmsh entity
tags are per-dimension, so resolution is always within a dimension.
"""
import logging
import math

import gmsh

logger = logging.getLogger(__name__)

# Face/extent acceptance band: a matched entity's measure (area/length) must be
# within this ratio of the reference's (retaincad's ~10%).
_MEAS_LO, _MEAS_HI = 0.90, 1.10

# Anchor kind -> gmsh dimension.
_KIND_DIM = {"vertex": 0, "edge": 1, "face": 2, "part": 3}


class EntityResolutionError(RuntimeError):
    """An anchor could not be resolved to a matching gmsh entity, or the match
    failed the geometric self-check. Loud by design (Feature R6)."""


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class GeometricResolver:
    def __init__(self, tol=None):
        bb = gmsh.model.getBoundingBox(-1, -1)
        self._diag = math.sqrt(sum((bb[i + 3] - bb[i]) ** 2 for i in range(3)))
        # Scale-relative base tolerance; grown adaptively up to _tol_max.
        self._tol = tol if tol is not None else max(1e-9, self._diag * 1e-6)
        self._tol_max = max(self._tol, self._diag * 1e-2)
        self._index = self._build_index()
        self._pt_to_vols = self._build_point_volume_map()

    # ---------- index / manifest ----------
    def _build_index(self):
        """Per-dim list of {tag, com, meas, bbox, name}, computed once."""
        index = {d: [] for d in range(4)}
        for d in range(4):
            for _, t in gmsh.model.getEntities(d):
                com = (gmsh.model.getValue(0, t, []) if d == 0
                       else gmsh.model.occ.getCenterOfMass(d, t))
                meas = 0.0 if d == 0 else gmsh.model.occ.getMass(d, t)
                index[d].append({
                    "tag": t,
                    "com": tuple(float(c) for c in com),
                    "meas": float(meas),
                    "bbox": gmsh.model.getBoundingBox(d, t),
                })
        return index

    def _build_point_volume_map(self):
        """{point tag: set(volume tags)} so a vertex can be disambiguated by
        its owning part (Feature R5)."""
        out = {}
        for _, vol in gmsh.model.getEntities(3):
            for d, t in gmsh.model.getBoundary([(3, vol)], oriented=False,
                                               recursive=True):
                if d == 0:
                    out.setdefault(abs(t), set()).add(vol)
        return out

    def describe_entities(self):
        """Manifest: every entity's dim/tag/centroid/measure/bbox.

        No name field: gmsh's STEP importer does not surface per-entity STEP
        names (only an OCC shape-tree label such as "Shapes/SOLID"), so a "name"
        here would be misleading. Real STEP entity names would need an XDE/CAF
        import path.
        """
        return [dict(dim=d, tag=e["tag"], com=e["com"], meas=e["meas"],
                     bbox=e["bbox"]) for d in range(4) for e in self._index[d]]

    # ---------- resolution ----------
    def resolve_vertex(self, xyz, volume=None):
        matches = self._near_coms(0, xyz)
        if volume is not None:
            matches = [t for t in matches
                       if volume in self._pt_to_vols.get(t, set())]
        if not matches:
            raise EntityResolutionError(
                f"no vertex near {tuple(xyz)}"
                + (f" on volume {volume}" if volume is not None else ""))
        return sorted(matches)

    def resolve_edge(self, samples):
        tol = self._sample_tol(samples)
        sbox = self._expanded_box(samples, tol)
        cand = [e for e in self._index[1]
                if self._box_overlaps(e["bbox"], sbox)]
        out = [e["tag"] for e in cand
               if self._projects_within(1, e["tag"], samples, tol)]
        if not out:
            # Degenerate/seam curves can't be projected onto (OCC "null curve
            # in projection"); fall back to centroid + length match.
            scen = tuple(sum(p[i] for p in samples) / len(samples)
                         for i in range(3))
            slen = sum(_dist(samples[i], samples[i + 1])
                       for i in range(len(samples) - 1))
            out = [e["tag"] for e in cand
                   if _dist(e["com"], scen) <= tol
                   and self._length_match(e["meas"], slen, tol)]
        if not out:
            raise EntityResolutionError(
                f"no edge through samples near {tuple(samples[0])}")
        return sorted(out)

    def resolve_face(self, centroid, area=None, edge_anchors=None,
                     facet_samples=None):
        # (a) the surface(s) common to the face's resolved boundary edges.
        if edge_anchors:
            common = self._faces_from_edges(edge_anchors)
            if common and self._meas_ok(2, common, area):
                return sorted(common)
        # (b) centroid (+ area, + facet samples).
        tol = self._tol_for(centroid)
        cands = [e["tag"] for e in self._index[2]
                 if _dist(e["com"], centroid) <= tol
                 and (area is None or self._meas_ok(2, [e["tag"]], area))]
        if facet_samples:
            ftol = self._sample_tol(facet_samples)
            cands = [t for t in cands
                     if self._projects_within(2, t, facet_samples, ftol)]
        if not cands:
            raise EntityResolutionError(
                f"no face near centroid {tuple(centroid)} (area={area})")
        if area is not None and not self._meas_ok(2, cands, area):
            raise EntityResolutionError(
                f"matched face(s) {cands} extent disagrees with reference "
                f"area {area} — possible merge/over-selection")
        return sorted(cands)

    def resolve_part(self, centroid, volume_measure=None):
        tol = self._tol_for(centroid)
        cands = [e["tag"] for e in self._index[3]
                 if _dist(e["com"], centroid) <= tol
                 and (volume_measure is None
                      or self._meas_ok(3, [e["tag"]], volume_measure))]
        if not cands:
            raise EntityResolutionError(
                f"no part near centroid {tuple(centroid)}")
        return sorted(cands)

    def volumes_of_vertex(self, point_tag):
        """Volume tags whose boundary includes the given gmsh point tag.

        Precomputed once (unlike a per-call getBoundary scan); used to confine a
        local refinement to the part its anchor vertex belongs to.
        """
        return set(self._pt_to_vols.get(point_tag, set()))

    def build_owner_map(self, selections):
        """Resolve geometric selections to a ``{(dim, tag): owner}`` map.

        Each selection is ``(anchor, owner)`` or ``(anchor, owner, required)``;
        an anchor is ``{'kind': 'vertex'|'edge'|'face'|'part', ...}``. A required
        (default) selection that fails to resolve raises; an optional one logs
        loudly and is skipped (Feature R6). gmsh tags are per-dimension, so the
        key is ``(dim, tag)``.
        """
        owner_by_tag = {}
        for sel in selections:
            anchor, owner = sel[0], sel[1]
            required = sel[2] if len(sel) > 2 else True
            try:
                tags = self._resolve_anchor(anchor)
            except EntityResolutionError as exc:
                if required:
                    raise
                logger.warning("skipping optional selection %r: %s", owner, exc)
                continue
            dim = _KIND_DIM[anchor["kind"]]
            for t in tags:
                owner_by_tag[(dim, t)] = owner
        return owner_by_tag

    def _resolve_anchor(self, a):
        kind = a.get("kind")
        if kind == "vertex":
            volume = a.get("volume")
            if volume is None and a.get("part") is not None:
                vols = gmsh.model.getEntities(3)
                pi = a["part"]
                if not 0 <= pi < len(vols):
                    raise EntityResolutionError(
                        f"part index {pi} out of range (0..{len(vols) - 1})")
                volume = vols[pi][1]
            return self.resolve_vertex(a["at"], volume=volume)
        if kind == "edge":
            return self.resolve_edge(a["samples"])
        if kind == "face":
            return self.resolve_face(a["centroid"], area=a.get("area"),
                                     edge_anchors=a.get("edge_anchors"),
                                     facet_samples=a.get("facet_samples"))
        if kind == "part":
            return self.resolve_part(a["centroid"])
        raise EntityResolutionError(f"unknown anchor kind {kind!r}")

    # ---------- helpers ----------
    def _near_coms(self, dim, xyz):
        """Tags whose centroid is within an adaptively grown tolerance of xyz."""
        tol = self._tol
        while tol <= self._tol_max:
            hits = [e["tag"] for e in self._index[dim]
                    if _dist(e["com"], xyz) <= tol]
            if hits:
                return hits
            tol *= 4.0
        return []

    def _tol_for(self, xyz):
        tol = self._tol
        while tol <= self._tol_max:
            if any(_dist(e["com"], xyz) <= tol for e in self._index[2]
                   ) or any(_dist(e["com"], xyz) <= tol for e in self._index[3]):
                return tol
            tol *= 4.0
        return self._tol_max

    def _sample_tol(self, samples):
        return self._tol_max if len(samples) else self._tol

    def _measure(self, dim, tag):
        for e in self._index[dim]:
            if e["tag"] == tag:
                return e["meas"]
        return 0.0

    def _meas_ok(self, dim, tags, ref):
        if ref is None:
            return True
        total = sum(self._measure(dim, t) for t in tags)
        if ref <= 0:
            return total <= 0
        return _MEAS_LO <= total / ref <= _MEAS_HI

    @staticmethod
    def _length_match(meas, slen, tol):
        if slen <= tol:
            return meas <= tol
        return _MEAS_LO <= meas / slen <= _MEAS_HI

    @staticmethod
    def _projects_within(dim, tag, pts, tol):
        try:
            return all(
                _dist(gmsh.model.getClosestPoint(dim, tag, p)[0], p) <= tol
                for p in pts)
        except Exception:
            return False

    def _faces_from_edges(self, edge_anchors):
        surf_sets = []
        for ea in edge_anchors:
            try:
                edges = self.resolve_edge(ea)
            except EntityResolutionError:
                return set()
            s = set()
            for e in edges:
                up, _ = gmsh.model.getAdjacencies(1, e)
                s.update(int(x) for x in up)
            surf_sets.append(s)
        return set.intersection(*surf_sets) if surf_sets else set()

    @staticmethod
    def _expanded_box(points, pad):
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]
        return (min(xs) - pad, min(ys) - pad, min(zs) - pad,
                max(xs) + pad, max(ys) + pad, max(zs) + pad)

    @staticmethod
    def _box_overlaps(bb, box):
        return (bb[0] <= box[3] and bb[3] >= box[0] and
                bb[1] <= box[4] and bb[4] >= box[1] and
                bb[2] <= box[5] and bb[5] >= box[2])
