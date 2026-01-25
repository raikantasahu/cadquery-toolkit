"""
CAD_ModelData - Data model for CAD geometry representation.

This module defines data classes that match the C# CAD_ModelData class structure,
enabling interoperability between Python and C# systems.

The format supports:
- Vertices, edges, faces with tessellation data
- Bodies and volumes for B-Rep topology
- Mass properties (volume, density, center of mass, inertia)
- Material colors and transparency
- Configuration parameters
"""

import json
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import List, Dict, Any


# =============================================================================
# Enums (matching C# enum values)
# =============================================================================

class ModelType(IntEnum):
    """Type of CAD model"""
    ASSEMBLY = 0
    PART = 1
    UNKNOWN = 2


class EntityType(IntEnum):
    """Type of geometric entity"""
    VERTEX = 0
    EDGE = 1
    FACE = 2
    POSITIVE_SIDE = 3
    NEGATIVE_SIDE = 4
    BODY = 5
    POINT = 6
    AXIS = 7
    COORDINATE_SYSTEM = 8
    MODEL = 9
    UNKNOWNENTITY = 10


class ParameterType(IntEnum):
    """Type of configuration parameter"""
    PARAMETER_INTEGER = 0
    PARAMETER_REAL = 1
    PARAMETER_STRING = 2
    PARAMETER_UNKNOWN = 3


# =============================================================================
# Helper Functions
# =============================================================================

def _to_camel_case(name: str) -> str:
    """Convert PascalCase to camelCase."""
    if not name:
        return name
    return name[0].lower() + name[1:]


def _dict_to_camel(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert dictionary keys from PascalCase to camelCase."""
    return {_to_camel_case(k): v for k, v in d.items()}


# =============================================================================
# Entity Data Classes
# =============================================================================

@dataclass
class Vertex:
    """
    Vertex entity with 3D location.
    
    Attributes:
        PersistentID: Unique identifier for the vertex
        Location: 3D coordinates [x, y, z]
    """
    PersistentID: str = ""
    Location: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    
    def __post_init__(self):
        if len(self.Location) != 3:
            raise ValueError("Location must have exactly 3 elements [x, y, z]")


@dataclass
class Edge:
    """
    Edge entity with start/end vertex indices and tessellated points.
    
    Attributes:
        PersistentID: Unique identifier for the edge
        Start: Index into VertexList for start vertex (-1 if not set)
        End: Index into VertexList for end vertex (-1 if not set)
        VertexLocations: Flattened tessellation points [x1,y1,z1,x2,y2,z2,...]
    """
    PersistentID: str = ""
    Start: int = -1
    End: int = -1
    VertexLocations: List[float] = field(default_factory=list)


@dataclass
class Face:
    """
    Face entity with tessellation data for rendering.
    
    Attributes:
        PersistentID: Unique identifier for the face
        Area: Surface area of the face
        EdgeList: Indices into the model's EdgeList
        VertexLocations: Flattened vertex positions [x1,y1,z1,x2,y2,z2,...]
        Connectivity: Triangle indices into VertexLocations (every 3 values = 1 triangle)
        Colors: RGB color values [r, g, b] normalized 0-1, or [-1,-1,-1] if not set
        Transparency: 0.0 = opaque, 1.0 = fully transparent, -1.0 = not set
    """
    PersistentID: str = ""
    Area: float = 0.0
    EdgeList: List[int] = field(default_factory=list)
    VertexLocations: List[float] = field(default_factory=list)
    Connectivity: List[int] = field(default_factory=list)
    Colors: List[float] = field(default_factory=lambda: [-1.0, -1.0, -1.0])
    Transparency: float = -1.0
    
    def __post_init__(self):
        if len(self.Colors) != 3:
            raise ValueError("Colors must have exactly 3 elements [r, g, b]")
    
    @property
    def vertex_count(self) -> int:
        """Number of unique vertices in this face"""
        return len(self.VertexLocations) // 3
    
    @property
    def triangle_count(self) -> int:
        """Number of triangles in this face"""
        return len(self.Connectivity) // 3


@dataclass
class Volume:
    """
    Volume entity containing a closed shell of faces.
    
    Attributes:
        PersistentID: Unique identifier for the volume
        FaceList: Indices into the model's FaceList
    """
    PersistentID: str = ""
    FaceList: List[int] = field(default_factory=list)


@dataclass
class Body:
    """
    Body entity representing a solid or sheet body.
    
    Attributes:
        PersistentID: Unique identifier for the body
        VolumeList: Indices into the model's VolumeList
    """
    PersistentID: str = ""
    VolumeList: List[int] = field(default_factory=list)


@dataclass
class Parameter:
    """
    Configuration parameter for parametric models.
    
    Attributes:
        Type: Parameter type (integer, real, string, unknown)
        Name: Parameter name/identifier
        Value: Parameter value as string
    """
    Type: int = ParameterType.PARAMETER_UNKNOWN
    Name: str = ""
    Value: str = ""


# =============================================================================
# Main Model Data Class
# =============================================================================

@dataclass
class CAD_ModelData:
    """
    Complete CAD model data structure matching the C# CAD_ModelData class.
    
    This class represents a complete CAD part or assembly with:
    - Metadata (name, units, type)
    - Geometric properties (volume, bounding box, center of mass)
    - Topology (vertices, edges, faces, volumes, bodies)
    - Appearance (colors, transparency)
    - Parameters (configuration variables)
    
    Attributes:
        CadName: Name of the source CAD system (e.g., "Onshape", "SolidWorks")
        ModelName: Document or file name
        ComponentName: Part or component name within the document
        ModelTypeValue: Type of model (ASSEMBLY=0, PART=1, UNKNOWN=2)
        ConfigurationName: Active configuration name
        PersistentID: Unique identifier for this component
        Id: Numeric identifier
        LengthUnit: Unit for length measurements (e.g., "meter", "inch")
        MassUnit: Unit for mass measurements (e.g., "kilogram", "pound")
        AngleUnit: Unit for angle measurements (e.g., "radian", "degree")
        Colors: RGB color [r, g, b] normalized 0-1
        Transparency: 0.0 = opaque, 1.0 = transparent
        GeometricVolume: Volume of the part in LengthUnit³
        Density: Material density in MassUnit/LengthUnit³
        CenterOfMass: Center of mass [x, y, z]
        VolumeMomentsOfInertia: [Ixx, Iyy, Izz, Ixy, Ixz, Iyz]
        BoundingBox: [minX, minY, minZ, maxX, maxY, maxZ]
        TransformToParent: 4x4 transformation matrix (row-major, 16 elements)
        VertexList: List of vertices
        EdgeList: List of edges
        FaceList: List of faces with tessellation
        VolumeList: List of volumes
        BodyList: List of bodies
        ParameterList: List of configuration parameters
    """
    
    # Metadata
    CadName: str = "Unknown"
    ModelName: str = ""
    ComponentName: str = ""
    ModelTypeValue: int = ModelType.UNKNOWN
    ConfigurationName: str = ""
    PersistentID: str = ""
    Id: int = 0
    
    # Units
    LengthUnit: str = "meter"
    MassUnit: str = "kilogram"
    AngleUnit: str = "radian"
    
    # Appearance
    Colors: List[float] = field(default_factory=lambda: [-1.0, -1.0, -1.0])
    Transparency: float = -1.0
    
    # Mass properties
    GeometricVolume: float = 0.0
    Density: float = 1.0
    CenterOfMass: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    VolumeMomentsOfInertia: List[float] = field(
        default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    )
    
    # Geometry
    BoundingBox: List[float] = field(
        default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    )
    TransformToParent: List[float] = field(
        default_factory=lambda: [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0
        ]
    )
    
    # Topology
    VertexList: List[Vertex] = field(default_factory=list)
    EdgeList: List[Edge] = field(default_factory=list)
    FaceList: List[Face] = field(default_factory=list)
    VolumeList: List[Volume] = field(default_factory=list)
    BodyList: List[Body] = field(default_factory=list)
    
    # Parameters
    ParameterList: List[Parameter] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate array lengths after initialization"""
        if len(self.Colors) != 3:
            raise ValueError("Colors must have exactly 3 elements")
        if len(self.CenterOfMass) != 3:
            raise ValueError("CenterOfMass must have exactly 3 elements")
        if len(self.VolumeMomentsOfInertia) != 6:
            raise ValueError("VolumeMomentsOfInertia must have exactly 6 elements")
        if len(self.BoundingBox) != 6:
            raise ValueError("BoundingBox must have exactly 6 elements")
        if len(self.TransformToParent) != 16:
            raise ValueError("TransformToParent must have exactly 16 elements")
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON serialization with camelCase keys.
        
        Returns:
            Dictionary matching the expected JSON structure with camelCase keys
        """
        # Convert ModelTypeValue int to string name
        model_type_names = {0: 'ASSEMBLY', 1: 'PART', 2: 'UNKNOWN'}
        model_type_str = model_type_names.get(self.ModelTypeValue, 'UNKNOWN')
        
        return {
            "cadName": self.CadName,
            "modelName": self.ModelName,
            "componentName": self.ComponentName,
            "modelTypeValue": model_type_str,
            "configurationName": self.ConfigurationName,
            "persistentID": self.PersistentID,
            "id": self.Id,
            "lengthUnit": self.LengthUnit,
            "massUnit": self.MassUnit,
            "angleUnit": self.AngleUnit,
            "colors": self.Colors,
            "transparency": self.Transparency,
            "geometricVolume": self.GeometricVolume,
            "density": self.Density,
            "centerOfMass": self.CenterOfMass,
            "volumeMomentsOfInertia": self.VolumeMomentsOfInertia,
            "boundingBox": self.BoundingBox,
            "transformToParent": self.TransformToParent,
            "vertexList": [_dict_to_camel(asdict(v)) for v in self.VertexList],
            "edgeList": [_dict_to_camel(asdict(e)) for e in self.EdgeList],
            "faceList": [_dict_to_camel(asdict(f)) for f in self.FaceList],
            "volumeList": [_dict_to_camel(asdict(v)) for v in self.VolumeList],
            "bodyList": [_dict_to_camel(asdict(b)) for b in self.BodyList],
            "parameterList": [_dict_to_camel(asdict(p)) for p in self.ParameterList],
        }
    
    def to_json(self, indent: int = 2) -> str:
        """
        Convert to JSON string.
        
        Args:
            indent: Number of spaces for indentation (None for compact)
            
        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=indent)
    
    def save(self, filepath: str, indent: int = 2) -> None:
        """
        Save to JSON file.
        
        Args:
            filepath: Path to output file
            indent: Number of spaces for indentation
        """
        with open(filepath, 'w') as f:
            f.write(self.to_json(indent=indent))
        print(f"Saved CAD_ModelData to: {filepath}")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CAD_ModelData':
        """
        Create CAD_ModelData from dictionary (e.g., loaded from JSON).
        Accepts both camelCase and PascalCase keys.
        
        Args:
            data: Dictionary with CAD_ModelData fields
            
        Returns:
            CAD_ModelData instance
        """
        # Helper to get value with either camelCase or PascalCase key
        def get(key: str, default=None):
            camel = key[0].lower() + key[1:]
            return data.get(camel, data.get(key, default))
        
        # Parse ModelTypeValue - handle both string and int
        model_type_raw = get('ModelTypeValue', ModelType.UNKNOWN)
        if isinstance(model_type_raw, str):
            model_type_map = {'ASSEMBLY': 0, 'PART': 1, 'UNKNOWN': 2}
            model_type_value = model_type_map.get(model_type_raw.upper(), 2)
        else:
            model_type_value = model_type_raw
        
        # Convert nested dictionaries to dataclass instances
        vertex_data = get('VertexList', [])
        edge_data = get('EdgeList', [])
        face_data = get('FaceList', [])
        volume_data = get('VolumeList', [])
        body_data = get('BodyList', [])
        param_data = get('ParameterList', [])
        
        # Helper to convert camelCase dict to PascalCase for dataclass
        def to_pascal(d: Dict) -> Dict:
            return {k[0].upper() + k[1:]: v for k, v in d.items()}
        
        vertex_list = [Vertex(**to_pascal(v)) for v in vertex_data]
        edge_list = [Edge(**to_pascal(e)) for e in edge_data]
        face_list = [Face(**to_pascal(f)) for f in face_data]
        volume_list = [Volume(**to_pascal(v)) for v in volume_data]
        body_list = [Body(**to_pascal(b)) for b in body_data]
        param_list = [Parameter(**to_pascal(p)) for p in param_data]
        
        return cls(
            CadName=get('CadName', 'Unknown'),
            ModelName=get('ModelName', ''),
            ComponentName=get('ComponentName', ''),
            ModelTypeValue=model_type_value,
            ConfigurationName=get('ConfigurationName', ''),
            PersistentID=get('PersistentID', ''),
            Id=get('Id', 0),
            LengthUnit=get('LengthUnit', 'meter'),
            MassUnit=get('MassUnit', 'kilogram'),
            AngleUnit=get('AngleUnit', 'radian'),
            Colors=get('Colors', [-1.0, -1.0, -1.0]),
            Transparency=get('Transparency', -1.0),
            GeometricVolume=get('GeometricVolume', 0.0),
            Density=get('Density', 1.0),
            CenterOfMass=get('CenterOfMass', [0.0, 0.0, 0.0]),
            VolumeMomentsOfInertia=get('VolumeMomentsOfInertia', [0.0]*6),
            BoundingBox=get('BoundingBox', [0.0]*6),
            TransformToParent=get('TransformToParent', [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            ]),
            VertexList=vertex_list,
            EdgeList=edge_list,
            FaceList=face_list,
            VolumeList=volume_list,
            BodyList=body_list,
            ParameterList=param_list,
        )
    
    @classmethod
    def load(cls, filepath: str) -> 'CAD_ModelData':
        """
        Load from JSON file.
        
        Args:
            filepath: Path to JSON file
            
        Returns:
            CAD_ModelData instance
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    # Computed properties
    @property
    def mass(self) -> float:
        """Computed mass from volume and density"""
        return self.GeometricVolume * self.Density
    
    @property
    def total_face_count(self) -> int:
        """Total number of faces"""
        return len(self.FaceList)
    
    @property
    def total_edge_count(self) -> int:
        """Total number of edges"""
        return len(self.EdgeList)
    
    @property
    def total_vertex_count(self) -> int:
        """Total number of vertices"""
        return len(self.VertexList)
    
    @property
    def total_triangle_count(self) -> int:
        """Total number of triangles across all faces"""
        return sum(f.triangle_count for f in self.FaceList)
    
    @property
    def bounding_box_size(self) -> List[float]:
        """Size of bounding box [width, height, depth]"""
        return [
            self.BoundingBox[3] - self.BoundingBox[0],
            self.BoundingBox[4] - self.BoundingBox[1],
            self.BoundingBox[5] - self.BoundingBox[2],
        ]
    
    def is_valid(self) -> bool:
        """Check if the model data is valid"""
        try:
            self.__post_init__()
            return bool(self.ModelName or self.ComponentName)
        except ValueError:
            return False
    
    def __repr__(self) -> str:
        return (
            f"CAD_ModelData("
            f"name='{self.ComponentName or self.ModelName}', "
            f"type={ModelType(self.ModelTypeValue).name}, "
            f"faces={self.total_face_count}, "
            f"volume={self.GeometricVolume:.6f})"
        )
