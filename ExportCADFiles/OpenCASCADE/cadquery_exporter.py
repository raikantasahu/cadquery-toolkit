"""
cadquery_exporter.py - Export CadQuery models to CAD_ModelData format

This module provides functionality to convert CadQuery models to the
CAD_ModelData JSON format for use with the CAD Model Server.

Requirements:
    pip install cadquery numpy requests

Usage:
    import cadquery as cq
    from cadquery_exporter import CADModelExporter

    # Create a CadQuery model
    result = cq.Workplane("XY").box(10, 10, 10)

    # Export to CAD_ModelData
    exporter = CADModelExporter(result, model_name="MyBox")
    model_data = exporter.export()

    # Save to JSON file
    exporter.save_to_file("mybox.json")

    # Or upload to server
    exporter.upload_to_server("http://localhost/api/cadmodel")
"""

import json
import hashlib
from typing import List, Dict, Tuple, Optional, Any
import numpy as np

try:
    import cadquery as cq
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopoDS import TopoDS_Vertex, TopoDS_Edge, TopoDS_Face, TopoDS_Solid
    from OCP.gp import gp_Pnt
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopLoc import TopLoc_Location
    HAS_CADQUERY = True
except ImportError:
    HAS_CADQUERY = False
    print("Warning: CadQuery not installed. Run: pip install cadquery")


class CADModelExporter:
    """
    Exports CadQuery models to CAD_ModelData JSON format
    """

    def __init__(self,
                 cadquery_object: Any,
                 model_name: str = "CadQuery Model",
                 cad_name: str = "CadQuery",
                 length_unit: str = "mm",
                 mass_unit: str = "kg",
                 angle_unit: str = "degrees"):
        """
        Initialize exporter with a CadQuery object

        Args:
            cadquery_object: CadQuery Workplane or Assembly
            model_name: Name for the model
            cad_name: CAD system name (default: "CadQuery")
            length_unit: Length units (default: "mm")
            mass_unit: Mass units (default: "kg")
            angle_unit: Angle units (default: "degrees")
        """
        if not HAS_CADQUERY:
            raise ImportError("CadQuery is required. Install with: pip install cadquery")

        self.cq_object = cadquery_object
        self.model_name = model_name
        self.cad_name = cad_name
        self.length_unit = length_unit
        self.mass_unit = mass_unit
        self.angle_unit = angle_unit

        # Get the underlying shape
        if hasattr(cadquery_object, 'val'):
            self.shape = cadquery_object.val()
        elif hasattr(cadquery_object, 'toCompound'):
            self.shape = cadquery_object.toCompound()
        else:
            self.shape = cadquery_object

        # Storage for extracted geometry
        self.vertices_map = {}  # Map of OCP vertex hash -> index
        self.vertices_list = []
        self.edges_list = []
        self.faces_list = []
        self.volumes_list = []
        self.bodies_list = []

    def _hash_vertex(self, vertex: TopoDS_Vertex) -> str:
        """Create unique hash for a vertex based on its coordinates"""
        pnt = BRep_Tool.Pnt_s(vertex)
        coords = (round(pnt.X(), 6), round(pnt.Y(), 6), round(pnt.Z(), 6))
        return hashlib.md5(str(coords).encode()).hexdigest()[:16]

    def _extract_vertices(self) -> None:
        """Extract all unique vertices from the shape"""
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_ShapeEnum

        explorer = TopExp_Explorer(self.shape, TopAbs_ShapeEnum.TopAbs_VERTEX)
        vertex_index = 0

        while explorer.More():
            vertex = TopoDS_Vertex.DownCast(explorer.Current())
            vertex_hash = self._hash_vertex(vertex)

            if vertex_hash not in self.vertices_map:
                pnt = BRep_Tool.Pnt_s(vertex)

                self.vertices_list.append({
                    "persistentID": f"V{vertex_index}",
                    "location": [pnt.X(), pnt.Y(), pnt.Z()]
                })

                self.vertices_map[vertex_hash] = vertex_index
                vertex_index += 1

            explorer.Next()

    def _get_vertex_index(self, vertex: TopoDS_Vertex) -> int:
        """Get the index of a vertex in the vertices list"""
        vertex_hash = self._hash_vertex(vertex)
        return self.vertices_map.get(vertex_hash, -1)

    def _extract_edges(self) -> None:
        """Extract all edges from the shape"""
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_ShapeEnum
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GCPnts import GCPnts_UniformAbscissa

        explorer = TopExp_Explorer(self.shape, TopAbs_ShapeEnum.TopAbs_EDGE)
        edge_index = 0

        while explorer.More():
            edge = TopoDS_Edge.DownCast(explorer.Current())

            # Get start and end vertices
            from OCP.TopoDS import TopoDS
            from OCP.TopExp import TopExp

            v1 = TopoDS.Vertex_s(TopExp.FirstVertex_s(edge, True))
            v2 = TopoDS.Vertex_s(TopExp.LastVertex_s(edge, True))

            start_idx = self._get_vertex_index(v1)
            end_idx = self._get_vertex_index(v2)

            # Sample points along the edge
            curve_adaptor = BRepAdaptor_Curve(edge)
            vertex_locations = []

            try:
                # Sample 10 points along the curve
                num_points = 10
                sampler = GCPnts_UniformAbscissa(curve_adaptor, num_points)

                if sampler.IsDone():
                    for i in range(1, sampler.NbPoints() + 1):
                        param = sampler.Parameter(i)
                        pnt = curve_adaptor.Value(param)
                        vertex_locations.extend([pnt.X(), pnt.Y(), pnt.Z()])
            except:
                # If sampling fails, just use start and end points
                pnt1 = BRep_Tool.Pnt_s(v1)
                pnt2 = BRep_Tool.Pnt_s(v2)
                vertex_locations = [
                    pnt1.X(), pnt1.Y(), pnt1.Z(),
                    pnt2.X(), pnt2.Y(), pnt2.Z()
                ]

            self.edges_list.append({
                "persistentID": f"E{edge_index}",
                "start": start_idx,
                "end": end_idx,
                "vertexLocations": vertex_locations
            })

            edge_index += 1
            explorer.Next()

    def _triangulate_face(self, face: TopoDS_Face) -> Tuple[List[float], List[int]]:
        """Triangulate a face and return vertex locations and connectivity"""
        # Mesh the face
        BRepMesh_IncrementalMesh(face, 0.1, False, 0.1, True)

        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)

        vertex_locations = []
        connectivity = []

        if triangulation:
            # Get transformation
            trsf = location.Transformation()

            # Extract vertices
            for i in range(1, triangulation.NbNodes() + 1):
                pnt = triangulation.Node(i)
                pnt.Transform(trsf)
                vertex_locations.extend([pnt.X(), pnt.Y(), pnt.Z()])

            # Extract triangles (connectivity)
            for i in range(1, triangulation.NbTriangles() + 1):
                triangle = triangulation.Triangle(i)
                n1, n2, n3 = triangle.Get()
                # Convert to 0-based indexing
                connectivity.extend([n1 - 1, n2 - 1, n3 - 1])

        return vertex_locations, connectivity

    def _extract_faces(self) -> None:
        """Extract all faces from the shape"""
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_ShapeEnum

        explorer = TopExp_Explorer(self.shape, TopAbs_ShapeEnum.TopAbs_FACE)
        face_index = 0

        while explorer.More():
            face = TopoDS_Face.DownCast(explorer.Current())

            # Calculate face area
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            area = props.Mass()

            # Get edge indices for this face
            edge_list = []
            edge_explorer = TopExp_Explorer(face, TopAbs_ShapeEnum.TopAbs_EDGE)
            while edge_explorer.More():
                # Find matching edge in edges_list
                # This is simplified - in production, track edge hashes
                edge_list.append(len(edge_list))
                edge_explorer.Next()

            # Triangulate the face
            vertex_locations, connectivity = self._triangulate_face(face)

            self.faces_list.append({
                "persistentID": f"F{face_index}",
                "area": area,
                "edgeList": edge_list,
                "vertexLocations": vertex_locations,
                "connectivity": connectivity,
                "colors": [-1.0, -1.0, -1.0],
                "transparency": -1.0
            })

            face_index += 1
            explorer.Next()

    def _extract_solids(self) -> None:
        """Extract solid volumes from the shape"""
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_ShapeEnum

        explorer = TopExp_Explorer(self.shape, TopAbs_ShapeEnum.TopAbs_SOLID)
        solid_index = 0

        while explorer.More():
            solid = TopoDS_Solid.DownCast(explorer.Current())

            # Get face indices for this solid
            face_list = list(range(len(self.faces_list)))  # Simplified

            self.volumes_list.append({
                "persistentID": f"S{solid_index}",
                "faceList": face_list
            })

            solid_index += 1
            explorer.Next()

        # Create body containing all volumes
        if self.volumes_list:
            self.bodies_list.append({
                "persistentID": "B0",
                "volumeList": list(range(len(self.volumes_list)))
            })

    def _calculate_properties(self) -> Dict[str, Any]:
        """Calculate geometric properties (volume, center of mass, etc.)"""
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(self.shape, props)

        # Volume
        volume = props.Mass()

        # Center of mass
        center = props.CentreOfMass()
        center_of_mass = [center.X(), center.Y(), center.Z()]

        # Moments of inertia (simplified)
        matrix = props.MatrixOfInertia()
        moments = [
            matrix.Value(1, 1), matrix.Value(2, 2), matrix.Value(3, 3),
            matrix.Value(1, 2), matrix.Value(1, 3), matrix.Value(2, 3)
        ]

        # Bounding box
        bbox = Bnd_Box()
        BRepBndLib.Add_s(self.shape, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
        bounding_box = [xmin, ymin, zmin, xmax, ymax, zmax]

        return {
            "volume": volume,
            "geometricVolume": volume,
            "centerOfMass": center_of_mass,
            "volumeMomentsOfInertia": moments,
            "boundingBox": bounding_box
        }

    def export(self) -> Dict[str, Any]:
        """
        Export the CadQuery model to CAD_ModelData format

        Returns:
            Dictionary in CAD_ModelData format
        """
        # Extract geometry
        self._extract_vertices()
        self._extract_edges()
        self._extract_faces()
        self._extract_solids()

        # Calculate properties
        properties = self._calculate_properties()

        # Build CAD_ModelData structure
        model_data = {
            "cadName": self.cad_name,
            "modelName": self.model_name,
            "componentName": "",
            "modelTypeValue": "PART",
            "configurationName": "",
            "persistentID": f"CQ_{self.model_name}",
            "id": 0,
            "lengthUnit": self.length_unit,
            "massUnit": self.mass_unit,
            "angleUnit": self.angle_unit,
            "colors": [-1.0, -1.0, -1.0],
            "transparency": -1.0,
            "volume": properties["volume"],
            "geometricVolume": properties["geometricVolume"],
            "density": 1.0,
            "centerOfMass": properties["centerOfMass"],
            "volumeMomentsOfInertia": properties["volumeMomentsOfInertia"],
            "boundingBox": properties["boundingBox"],
            "transformToParent": [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            ],
            "vertexList": self.vertices_list,
            "edgeList": self.edges_list,
            "faceList": self.faces_list,
            "volumeList": self.volumes_list,
            "bodyList": self.bodies_list,
            "parameterList": []
        }

        return model_data

    def to_json(self, indent: int = 2) -> str:
        """
        Export to JSON string

        Args:
            indent: JSON indentation (default: 2)

        Returns:
            JSON string
        """
        model_data = self.export()
        return json.dumps(model_data, indent=indent)

    def save_to_file(self, filename: str, indent: int = 2) -> None:
        """
        Save to JSON file

        Args:
            filename: Output filename
            indent: JSON indentation (default: 2)
        """
        with open(filename, 'w') as f:
            f.write(self.to_json(indent=indent))
        print(f"Model exported to {filename}")

    def upload_to_server(self,
                        server_url: str,
                        use_multipart: bool = False) -> Dict[str, Any]:
        """
        Upload model to CAD Model Server

        Args:
            server_url: Server URL (e.g., "http://localhost/api/cadmodel")
            use_multipart: Upload as file (True) or JSON body (False)

        Returns:
            Server response as dictionary
        """
        import requests

        if use_multipart:
            # Upload as file
            files = {
                'file': (
                    f'{self.model_name}.json',
                    self.to_json(),
                    'application/json'
                )
            }
            response = requests.post(f"{server_url}/upload", files=files)
        else:
            # Upload as JSON body
            model_data = self.export()
            response = requests.post(
                server_url,
                json=model_data,
                headers={'Content-Type': 'application/json'}
            )

        response.raise_for_status()
        return response.json()


def export_cadquery_model(cq_object: Any,
                         model_name: str = "CadQuery Model",
                         output_file: Optional[str] = None,
                         server_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to export a CadQuery model

    Args:
        cq_object: CadQuery Workplane or shape
        model_name: Name for the model
        output_file: Optional output filename
        server_url: Optional server URL for upload

    Returns:
        CAD_ModelData dictionary

    Example:
        import cadquery as cq

        # Create model
        result = cq.Workplane("XY").box(10, 10, 10)

        # Export
        model_data = export_cadquery_model(
            result,
            model_name="My Box",
            output_file="box.json",
            server_url="http://localhost/api/cadmodel"
        )
    """
    exporter = CADModelExporter(cq_object, model_name=model_name)

    if output_file:
        exporter.save_to_file(output_file)

    if server_url:
        exporter.upload_to_server(server_url)

    return exporter.export()


if __name__ == "__main__":
    print("CadQuery to CAD_ModelData Exporter")
    print("Import this module and use CADModelExporter class")
