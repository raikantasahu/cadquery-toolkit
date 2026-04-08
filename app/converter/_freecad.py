"""
_freecad - FreeCAD-bound geometry walking for a single CadQuery part.

Internal implementation detail of the `converter` package. This module hands
a CadQuery shape to FreeCAD (via a temporary BRep file — OCCT's native
binary format, lossless and faster than STEP) and walks the resulting OCCT
topology to pull out unique vertices, edges, tessellated faces, volumes,
and bodies — plus mass properties (volume, center of mass, moments of
inertia, bounding box).

The output is a dict of plain dicts that mirror the CADModelData entity
field names (camelCase). The public converter functions in
`converter.converter` are responsible for repackaging those dicts into
typed CADModelData / Vertex / Edge / Face / Volume / Body instances.

There is no public API here. Use `converter.part_to_modeldata` instead.
"""

import hashlib
import inspect
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

try:
    import cadquery as cq  # noqa: F401
    HAS_CADQUERY = True
except ImportError:
    HAS_CADQUERY = False

try:
    # Conda installation (lowercase, namespace package)
    import freecad  # noqa: F401
    import freecad.app as FreeCAD  # noqa: F401
    import freecad.part as Part
    HAS_FREECAD = True
    FREECAD_TYPE = "conda"
except ImportError:
    try:
        # System installation (uppercase)
        import FreeCAD  # noqa: F401
        import Part
        HAS_FREECAD = True
        FREECAD_TYPE = "system"
    except ImportError:
        HAS_FREECAD = False
        FREECAD_TYPE = None


class _FreeCADShape:
    """
    A FreeCAD-loaded copy of a CadQuery shape, with operations to walk its
    topology and produce CADModelData-shaped dicts.

    Construct with a CadQuery object (Workplane or Shape) and call
    `extract()` to get a dict containing `vertices`, `edges`, `faces`,
    `volumes`, `bodies`, and `properties` (volume / centerOfMass /
    moments / boundingBox).
    """

    def __init__(self, cadquery_object: Any):
        if not HAS_CADQUERY:
            raise ImportError(
                "CadQuery is required. "
                "Install with: conda install -c conda-forge cadquery"
            )
        if not HAS_FREECAD:
            raise ImportError(
                "FreeCAD is required. "
                "Install with: conda install -c conda-forge freecad"
            )

        self.cq_object = cadquery_object

        self.vertices_map: Dict[str, int] = {}
        self.vertices_list: List[Dict[str, Any]] = []
        self.edges_list: List[Dict[str, Any]] = []
        self.faces_list: List[Dict[str, Any]] = []
        self.volumes_list: List[Dict[str, Any]] = []
        self.bodies_list: List[Dict[str, Any]] = []
        self._edge_index_map: Dict[str, int] = {}

        self.freecad_shape = self._load_to_freecad()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def extract(self) -> Dict[str, Any]:
        """Run all extraction passes and return the collected data."""
        self._extract_vertices()
        self._extract_edges()
        self._extract_faces()
        self._extract_solids()
        properties = self._calculate_properties()
        return {
            "vertices": self.vertices_list,
            "edges": self.edges_list,
            "faces": self.faces_list,
            "volumes": self.volumes_list,
            "bodies": self.bodies_list,
            "properties": properties,
        }

    # ------------------------------------------------------------------
    # FreeCAD shape loading
    # ------------------------------------------------------------------

    def _load_to_freecad(self) -> Any:
        """Hand the CadQuery shape to FreeCAD via a temporary BRep file.

        BRep is OCCT's native binary format — both cadquery (via OCP) and
        FreeCAD's Part module read and write it directly, with no protocol
        translation and no precision loss. Faster and lossless compared to
        round-tripping through STEP.

        Future improvement (out of current scope): in-memory BRep transfer
        via cq.Shape.exportBrep(BytesIO) + Part.Shape().importBrepFromString,
        which would drop the tempfile entirely.
        """
        with tempfile.NamedTemporaryFile(suffix=".brep", delete=False) as tmp:
            brep_file = tmp.name
        try:
            self._cq_shape().exportBrep(brep_file)
            shape = Part.Shape()
            shape.importBrep(brep_file)
            return shape
        finally:
            if os.path.exists(brep_file):
                os.remove(brep_file)

    def _cq_shape(self):
        """Return the underlying CadQuery Shape (val()) for the input object."""
        obj = self.cq_object
        # cq.Workplane has .val() returning the first Shape
        if hasattr(obj, "val"):
            return obj.val()
        # Already a Shape
        return obj

    # ------------------------------------------------------------------
    # Vertex extraction
    # ------------------------------------------------------------------

    def _hash_vertex(self, vertex) -> str:
        pnt = vertex.Point
        coords = (round(pnt.x, 6), round(pnt.y, 6), round(pnt.z, 6))
        return hashlib.md5(str(coords).encode()).hexdigest()[:16]

    def _extract_vertices(self) -> None:
        vertex_index = 0
        for vertex in self.freecad_shape.Vertexes:
            vertex_hash = self._hash_vertex(vertex)
            if vertex_hash not in self.vertices_map:
                pnt = vertex.Point
                self.vertices_list.append({
                    "persistentID": f"V{vertex_index}",
                    "location": [pnt.x, pnt.y, pnt.z],
                })
                self.vertices_map[vertex_hash] = vertex_index
                vertex_index += 1

    def _get_vertex_index(self, vertex) -> int:
        return self.vertices_map.get(self._hash_vertex(vertex), -1)

    # ------------------------------------------------------------------
    # Edge extraction
    # ------------------------------------------------------------------

    def _hash_edge(self, edge) -> str:
        """Hash by sorted endpoint coords + curve midpoint to disambiguate."""
        try:
            start = edge.firstVertex()
            end = edge.lastVertex()
        except AttributeError:
            start = edge.Vertexes[0]
            end = edge.Vertexes[-1]

        sh = self._hash_vertex(start)
        eh = self._hash_vertex(end)
        pair = tuple(sorted([sh, eh]))

        try:
            u_mid = (edge.FirstParameter + edge.LastParameter) / 2
            mid = edge.Curve.value(u_mid)
            mid_coords = (round(mid.x, 6), round(mid.y, 6), round(mid.z, 6))
        except Exception:
            mid_coords = ()

        return hashlib.md5(str((*pair, mid_coords)).encode()).hexdigest()[:16]

    def _extract_edges(self) -> None:
        for edge_index, edge in enumerate(self.freecad_shape.Edges):
            self._edge_index_map[self._hash_edge(edge)] = edge_index

            try:
                start_vertex = edge.firstVertex()
                end_vertex = edge.lastVertex()
            except AttributeError:
                try:
                    start_vertex = edge.Vertexes[0]
                    end_vertex = edge.Vertexes[-1]
                except Exception:
                    continue

            start_idx = self._get_vertex_index(start_vertex)
            end_idx = self._get_vertex_index(end_vertex)

            vertex_locations: List[float] = []
            try:
                points = edge.discretize(Deflection=0.05)
                for pnt in points:
                    vertex_locations.extend([pnt.x, pnt.y, pnt.z])
            except Exception:
                try:
                    pnt1 = start_vertex.Point
                    pnt2 = end_vertex.Point
                    vertex_locations = [
                        pnt1.x, pnt1.y, pnt1.z,
                        pnt2.x, pnt2.y, pnt2.z,
                    ]
                except Exception:
                    vertex_locations = [0.0] * 6

            self.edges_list.append({
                "persistentID": f"E{edge_index}",
                "start": start_idx,
                "end": end_idx,
                "vertexLocations": vertex_locations,
            })

    # ------------------------------------------------------------------
    # Face extraction
    # ------------------------------------------------------------------

    def _triangulate_face(self, face) -> Tuple[List[float], List[int]]:
        try:
            mesh_data = face.tessellate(0.1)
            vertices = mesh_data[0]
            triangles = mesh_data[1]

            vertex_locations: List[float] = []
            for v in vertices:
                vertex_locations.extend([v.x, v.y, v.z])

            connectivity: List[int] = []
            for tri in triangles:
                connectivity.extend(tri)

            return vertex_locations, connectivity
        except Exception as e:
            print(f"Warning: Could not triangulate face: {e}")
            return [], []

    def _extract_faces(self) -> None:
        for face_index, face in enumerate(self.freecad_shape.Faces):
            try:
                area = face.Area
            except AttributeError:
                try:
                    area = face.area()
                except Exception:
                    area = 0.0

            edge_list: List[int] = []
            for edge in face.Edges:
                edge_idx = self._edge_index_map.get(self._hash_edge(edge), -1)
                if edge_idx >= 0:
                    edge_list.append(edge_idx)

            vertex_locations, connectivity = self._triangulate_face(face)

            self.faces_list.append({
                "persistentID": f"F{face_index}",
                "area": area,
                "edgeList": edge_list,
                "vertexLocations": vertex_locations,
                "connectivity": connectivity,
                "colors": [-1.0, -1.0, -1.0],
                "transparency": -1.0,
            })

    # ------------------------------------------------------------------
    # Solid / body extraction
    # ------------------------------------------------------------------

    def _extract_solids(self) -> None:
        for solid_index, _solid in enumerate(self.freecad_shape.Solids):
            # Simplified — assume all faces belong to the solid.
            face_list = list(range(len(self.faces_list)))
            self.volumes_list.append({
                "persistentID": f"S{solid_index}",
                "faceList": face_list,
            })

        if self.volumes_list:
            self.bodies_list.append({
                "persistentID": "B0",
                "volumeList": list(range(len(self.volumes_list))),
            })

    # ------------------------------------------------------------------
    # Mass properties
    # ------------------------------------------------------------------

    def _calculate_properties(self) -> Dict[str, Any]:
        # Volume
        try:
            volume = self.freecad_shape.Volume
        except AttributeError:
            try:
                volume = self.freecad_shape.volume()
            except Exception:
                volume = 0.0

        # Center of mass
        try:
            com = self.freecad_shape.CenterOfMass
            center_of_mass = [com.x, com.y, com.z]
        except AttributeError:
            try:
                com = self.freecad_shape.centerOfMass()
                center_of_mass = [com.x, com.y, com.z]
            except Exception:
                try:
                    bbox = self.freecad_shape.BoundBox
                    center_of_mass = [
                        (bbox.XMin + bbox.XMax) / 2,
                        (bbox.YMin + bbox.YMax) / 2,
                        (bbox.ZMin + bbox.ZMax) / 2,
                    ]
                except Exception:
                    center_of_mass = [0.0, 0.0, 0.0]

        # Moments of inertia
        try:
            matrix = self.freecad_shape.MatrixOfInertia
            moments = [
                matrix.A11, matrix.A22, matrix.A33,
                matrix.A12, matrix.A13, matrix.A23,
            ]
        except (AttributeError, TypeError):
            moments = [0.0] * 6

        # Bounding box
        try:
            bbox = self.freecad_shape.BoundBox
            bounding_box = [
                bbox.XMin, bbox.YMin, bbox.ZMin,
                bbox.XMax, bbox.YMax, bbox.ZMax,
            ]
        except AttributeError:
            if self.vertices_list:
                xs = [v["location"][0] for v in self.vertices_list]
                ys = [v["location"][1] for v in self.vertices_list]
                zs = [v["location"][2] for v in self.vertices_list]
                bounding_box = [
                    min(xs), min(ys), min(zs),
                    max(xs), max(ys), max(zs),
                ]
            else:
                bounding_box = [0.0] * 6

        return {
            "volume": volume,
            "centerOfMass": center_of_mass,
            "volumeMomentsOfInertia": moments,
            "boundingBox": bounding_box,
        }


# ----------------------------------------------------------------------
# Build-parameter conversion (no FreeCAD dependency, but kept here so the
# converter only has one place to import "extraction stuff" from).
# ----------------------------------------------------------------------

def build_parameter_dicts(
    parameters: Optional[Dict[str, Any]],
    param_signature: Optional[inspect.Signature],
) -> List[Dict[str, Any]]:
    """Convert (parameters, signature) into the list shape used by ParameterList."""
    from model.CADModelData import ParameterType

    type_map = {
        float: ParameterType.PARAMETER_REAL,
        int: ParameterType.PARAMETER_INTEGER,
        str: ParameterType.PARAMETER_STRING,
        bool: ParameterType.PARAMETER_BOOLEAN,
    }

    result: List[Dict[str, Any]] = []
    if not parameters:
        return result

    for name, value in parameters.items():
        param_type = ParameterType.PARAMETER_UNKNOWN
        if param_signature and name in param_signature.parameters:
            ann = param_signature.parameters[name].annotation
            if ann is not inspect.Parameter.empty:
                param_type = type_map.get(ann, ParameterType.PARAMETER_UNKNOWN)
        if param_type == ParameterType.PARAMETER_UNKNOWN:
            param_type = type_map.get(type(value), ParameterType.PARAMETER_UNKNOWN)

        result.append({
            "type": int(param_type),
            "name": name,
            "value": str(value),
        })
    return result
