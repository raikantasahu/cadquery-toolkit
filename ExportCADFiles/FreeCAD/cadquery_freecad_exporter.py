"""
cadquery_freecad_exporter.py - Export CadQuery models using FreeCAD

This module uses FreeCAD's Python API to convert CadQuery models to 
CAD_ModelData format. FreeCAD has more stable bindings than raw OCP.

Requirements:
    pip install cadquery numpy requests
    # FreeCAD must be installed separately:
    # - Ubuntu/Debian: sudo apt install freecad
    # - macOS: brew install --cask freecad
    # - Windows: Download from freecad.org

Usage:
    import cadquery as cq
    from cadquery_freecad_exporter import FreeCADExporter
    
    # Create a CadQuery model
    result = cq.Workplane("XY").box(10, 10, 10)
    
    # Export to CAD_ModelData
    exporter = FreeCADExporter(result, model_name="MyBox")
    model_data = exporter.export()
    
    # Save to JSON file
    exporter.save_to_file("mybox.json")
"""

import json
import os
import tempfile
import hashlib
from typing import List, Dict, Tuple, Optional, Any
import numpy as np

try:
    import cadquery as cq
    HAS_CADQUERY = True
except ImportError:
    HAS_CADQUERY = False
    print("Warning: CadQuery not installed. Run: conda install -c conda-forge cadquery")

try:
    # Try conda installation (lowercase, different structure)
    import freecad
    import freecad.app as FreeCAD
    import freecad.part as Part
    HAS_FREECAD = True
    FREECAD_TYPE = "conda"
except ImportError:
    try:
        # Try system installation (uppercase)
        import FreeCAD
        import Part
        import Mesh
        HAS_FREECAD = True
        FREECAD_TYPE = "system"
    except ImportError:
        HAS_FREECAD = False
        FREECAD_TYPE = None
        print("Warning: FreeCAD not installed.")
        print("Install FreeCAD:")
        print("  Conda: conda install -c conda-forge freecad")
        print("  Ubuntu/Debian: sudo apt install freecad")
        print("  macOS: brew install --cask freecad")
        print("  Windows: Download from freecad.org")


class FreeCADExporter:
    """
    Exports CadQuery models to CAD_ModelData JSON format using FreeCAD
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
            cadquery_object: CadQuery Workplane or shape
            model_name: Name for the model
            cad_name: CAD system name (default: "CadQuery")
            length_unit: Length units (default: "mm")
            mass_unit: Mass units (default: "kg")
            angle_unit: Angle units (default: "degrees")
        """
        if not HAS_CADQUERY:
            raise ImportError("CadQuery is required. Install with: conda install -c conda-forge cadquery")
        
        if not HAS_FREECAD:
            raise ImportError("FreeCAD is required. See installation instructions above.")
        
        self.cq_object = cadquery_object
        self.model_name = model_name
        self.cad_name = cad_name
        self.length_unit = length_unit
        self.mass_unit = mass_unit
        self.angle_unit = angle_unit
        
        # Storage for extracted geometry
        self.vertices_map = {}  # Map of vertex coords -> index
        self.vertices_list = []
        self.edges_list = []
        self.faces_list = []
        self.volumes_list = []
        self.bodies_list = []
        
        # Load shape into FreeCAD
        self.freecad_shape = self._load_to_freecad()
    
    def _load_to_freecad(self) -> Any:
        """Load CadQuery shape into FreeCAD via STEP file"""
        # Create temporary STEP file
        with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tmp:
            step_file = tmp.name
        
        try:
            # Export CadQuery to STEP
            self.cq_object.val().exportStep(step_file)
            
            # Import into FreeCAD
            shape = Part.read(step_file)
            
            return shape
            
        finally:
            # Clean up temporary file
            if os.path.exists(step_file):
                os.remove(step_file)
    
    def _hash_vertex(self, vertex) -> str:
        """Create unique hash for a vertex based on its coordinates"""
        pnt = vertex.Point
        coords = (round(pnt.x, 6), round(pnt.y, 6), round(pnt.z, 6))
        return hashlib.md5(str(coords).encode()).hexdigest()[:16]
    
    def _extract_vertices(self) -> None:
        """Extract all unique vertices from the shape"""
        vertex_index = 0
        
        for vertex in self.freecad_shape.Vertexes:
            vertex_hash = self._hash_vertex(vertex)
            
            if vertex_hash not in self.vertices_map:
                pnt = vertex.Point
                
                self.vertices_list.append({
                    "persistentID": f"V{vertex_index}",
                    "location": [pnt.x, pnt.y, pnt.z]
                })
                
                self.vertices_map[vertex_hash] = vertex_index
                vertex_index += 1
    
    def _get_vertex_index(self, vertex) -> int:
        """Get the index of a vertex in the vertices list"""
        vertex_hash = self._hash_vertex(vertex)
        return self.vertices_map.get(vertex_hash, -1)
    
    def _extract_edges(self) -> None:
        """Extract all edges from the shape"""
        for edge_index, edge in enumerate(self.freecad_shape.Edges):
            # Get start and end vertices
            try:
                start_vertex = edge.firstVertex()
                end_vertex = edge.lastVertex()
            except AttributeError:
                # Try alternative method
                try:
                    start_vertex = edge.Vertexes[0]
                    end_vertex = edge.Vertexes[-1]
                except:
                    # Skip this edge if we can't get vertices
                    continue
            
            start_idx = self._get_vertex_index(start_vertex)
            end_idx = self._get_vertex_index(end_vertex)
            
            # Sample points along the edge
            vertex_locations = []
            
            try:
                # Discretize the edge into points
                num_points = 10
                curve = edge.Curve
                
                # Get parameter range
                u_min = edge.FirstParameter
                u_max = edge.LastParameter
                
                # Sample points
                for i in range(num_points + 1):
                    u = u_min + (u_max - u_min) * i / num_points
                    pnt = curve.value(u)
                    vertex_locations.extend([pnt.x, pnt.y, pnt.z])
                    
            except:
                # Fallback: use start and end points
                try:
                    pnt1 = start_vertex.Point
                    pnt2 = end_vertex.Point
                    vertex_locations = [
                        pnt1.x, pnt1.y, pnt1.z,
                        pnt2.x, pnt2.y, pnt2.z
                    ]
                except:
                    # Last resort - empty locations
                    vertex_locations = [0, 0, 0, 0, 0, 0]
            
            self.edges_list.append({
                "persistentID": f"E{edge_index}",
                "start": start_idx,
                "end": end_idx,
                "vertexLocations": vertex_locations
            })
    
    def _triangulate_face(self, face) -> Tuple[List[float], List[int]]:
        """Triangulate a face and return vertex locations and connectivity"""
        # Use FreeCAD's tessellate method directly (works in both conda and system)
        try:
            # Mesh the face with linear deflection
            mesh_data = face.tessellate(0.1)
            
            vertices = mesh_data[0]  # List of FreeCAD.Vector
            triangles = mesh_data[1]  # List of triangle indices
            
            # Convert to flat lists
            vertex_locations = []
            for v in vertices:
                vertex_locations.extend([v.x, v.y, v.z])
            
            connectivity = []
            for tri in triangles:
                connectivity.extend(tri)
            
            return vertex_locations, connectivity
            
        except Exception as e:
            print(f"Warning: Could not triangulate face: {e}")
            return [], []
    
    def _extract_faces(self) -> None:
        """Extract all faces from the shape"""
        for face_index, face in enumerate(self.freecad_shape.Faces):
            # Calculate face area
            try:
                area = face.Area
            except AttributeError:
                # Fallback for different API
                try:
                    area = face.area()
                except:
                    # Last resort - approximate from triangulation
                    area = 0.0
            
            # Get edges for this face
            edge_list = []
            for edge in face.Edges:
                # Find matching edge in edges_list
                # Simplified - just use sequential indices
                edge_list.append(len(edge_list))
            
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
    
    def _extract_solids(self) -> None:
        """Extract solid volumes from the shape"""
        for solid_index, solid in enumerate(self.freecad_shape.Solids):
            # Get face indices for this solid
            # Simplified - assume all faces belong to solid
            face_list = list(range(len(self.faces_list)))
            
            self.volumes_list.append({
                "persistentID": f"S{solid_index}",
                "faceList": face_list
            })
        
        # Create body containing all volumes
        if self.volumes_list:
            self.bodies_list.append({
                "persistentID": "B0",
                "volumeList": list(range(len(self.volumes_list)))
            })
    
    def _calculate_properties(self) -> Dict[str, Any]:
        """Calculate geometric properties using FreeCAD"""
        # Volume
        try:
            volume = self.freecad_shape.Volume
        except AttributeError:
            # Fallback for different API
            try:
                volume = self.freecad_shape.volume()
            except:
                volume = 0.0
        
        # Center of mass
        try:
            com = self.freecad_shape.CenterOfMass
            center_of_mass = [com.x, com.y, com.z]
        except AttributeError:
            # Fallback - try different method or calculate from vertices
            try:
                com = self.freecad_shape.centerOfMass()
                center_of_mass = [com.x, com.y, com.z]
            except:
                # Last resort - use geometric center of bounding box
                try:
                    bbox = self.freecad_shape.BoundBox
                    center_of_mass = [
                        (bbox.XMin + bbox.XMax) / 2,
                        (bbox.YMin + bbox.YMax) / 2,
                        (bbox.ZMin + bbox.ZMax) / 2
                    ]
                except:
                    center_of_mass = [0.0, 0.0, 0.0]
        
        # Moments of inertia
        try:
            matrix = self.freecad_shape.MatrixOfInertia
            moments = [
                matrix.A11, matrix.A22, matrix.A33,
                matrix.A12, matrix.A13, matrix.A23
            ]
        except (AttributeError, TypeError):
            # Not available in this FreeCAD version
            moments = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        
        # Bounding box
        try:
            bbox = self.freecad_shape.BoundBox
            bounding_box = [
                bbox.XMin, bbox.YMin, bbox.ZMin,
                bbox.XMax, bbox.YMax, bbox.ZMax
            ]
        except AttributeError:
            # Fallback - calculate from vertices
            if self.vertices_list:
                xs = [v['location'][0] for v in self.vertices_list]
                ys = [v['location'][1] for v in self.vertices_list]
                zs = [v['location'][2] for v in self.vertices_list]
                bounding_box = [
                    min(xs), min(ys), min(zs),
                    max(xs), max(ys), max(zs)
                ]
            else:
                bounding_box = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        
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
    Convenience function to export a CadQuery model using FreeCAD
    
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
    exporter = FreeCADExporter(cq_object, model_name=model_name)
    
    if output_file:
        exporter.save_to_file(output_file)
    
    if server_url:
        exporter.upload_to_server(server_url)
    
    return exporter.export()


if __name__ == "__main__":
    print("CadQuery to CAD_ModelData Exporter (FreeCAD-based)")
    print("Import this module and use FreeCADExporter class")
