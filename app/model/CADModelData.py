"""
CADModelData - Data model for CAD geometry representation.

This module mirrors the C# class `RSA.Model.CADModelData` (see
RSA.Applications/Model/src/CADModelData.cs) and its JSON wire format
produced by `CADModelDataWriter` / consumed by `CADModelDataReader`.

Wire format (envelope; structurally identical to CADModelDataWriter, but
this Python application emits **camelCase** property names — the C# reader
is configured with PropertyNameCaseInsensitive=true so it round-trips fine):

    {
      "rootIndex": <int>,
      "models": [
        {
          "cadName": "...",
          "modelName": "...",
          ... all CADModelData fields ...
          "childComponents": [
            { "transformToParent": [16 doubles], "childIndex": <int> },
            ...
          ]
        },
        ...
      ]
    }

- Property names are **camelCase** on output (project convention).
- `modelTypeValue` is serialized as the enum **name** ("ASSEMBLY", "PART",
  "UNKNOWN") for human readability — the C# reader is configured with
  `JsonStringEnumConverter` so string names round-trip correctly.
- `parameterList[].type` is serialized as an integer (matches the C# writer
  default).
- The tree of assemblies/parts is encoded by integer `childIndex` references
  into the flat `models` array; each model appears exactly once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Any, Dict, List, Optional


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
    PARAMETER_BOOLEAN = 3
    PARAMETER_UNKNOWN = 4


# =============================================================================
# Helper Functions
# =============================================================================

def _identity_matrix() -> List[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _ci_get(d: Dict[str, Any], name: str, default: Any = None) -> Any:
    """Case-insensitive dict lookup (mirrors PropertyNameCaseInsensitive=true)."""
    if name in d:
        return d[name]
    lower = name.lower()
    for k, v in d.items():
        if k.lower() == lower:
            return v
    return default


def _to_camel(name: str) -> str:
    """Convert a PascalCase field name to camelCase."""
    if not name:
        return name
    return name[0].lower() + name[1:]


def _entity_to_dict(obj: Any) -> Dict[str, Any]:
    """Convert an entity dataclass to a dict with camelCase keys."""
    return {_to_camel(k): v for k, v in asdict(obj).items()}


# =============================================================================
# Nested entity classes
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
            raise ValueError("Vertex.Location must have exactly 3 elements [x, y, z]")


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
            raise ValueError("Face.Colors must have exactly 3 elements [r, g, b]")

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
    Model parameter for parametric models.

    Attributes:
        Type: Parameter type (integer, real, string, unknown)
        Name: Parameter name/identifier
        Value: Parameter value as string
    """
    # Default matches C# `default(ParameterType)` == PARAMETER_INTEGER (0).
    Type: int = ParameterType.PARAMETER_INTEGER
    Name: str = ""
    Value: str = ""


@dataclass
class Point:
    """Construction point with a 3D location."""
    PersistentID: str = ""
    Location: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    def __post_init__(self):
        if len(self.Location) != 3:
            raise ValueError("Point.Location must have exactly 3 elements [x, y, z]")


@dataclass
class Axis:
    """Construction axis defined by an origin and a direction vector."""
    PersistentID: str = ""
    Origin: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    Direction: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    def __post_init__(self):
        if len(self.Origin) != 3:
            raise ValueError("Axis.Origin must have exactly 3 elements")
        if len(self.Direction) != 3:
            raise ValueError("Axis.Direction must have exactly 3 elements")


@dataclass
class CoordinateSystem:
    """
    Construction coordinate system.

    `Axes` is a flattened 3x3 rotation matrix (9 elements, row-major) giving
    the system's X/Y/Z axis directions in the parent frame.
    """
    PersistentID: str = ""
    Origin: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    Axes: List[float] = field(default_factory=lambda: [0.0] * 9)

    def __post_init__(self):
        if len(self.Origin) != 3:
            raise ValueError("CoordinateSystem.Origin must have exactly 3 elements")
        if len(self.Axes) != 9:
            raise ValueError("CoordinateSystem.Axes must have exactly 9 elements")


@dataclass
class Component:
    """
    A child model placement inside an assembly.

    Holds the per-instance 4x4 transform that maps the child's local frame
    into the parent's frame, plus a reference to the child model itself.
    """
    TransformToParent: List[float] = field(default_factory=_identity_matrix)
    ChildModelData: "CADModelData" = field(
        default_factory=lambda: CADModelData()
    )

    def __post_init__(self):
        if len(self.TransformToParent) != 16:
            raise ValueError(
                "Component.TransformToParent must have exactly 16 elements"
            )


# =============================================================================
# Main CADModelData class
# =============================================================================

@dataclass
class CADModelData:
    """
    Complete CAD model data structure mirroring the C# CADModelData class.

    Attributes
    ----------
    Metadata
        CadName, ModelName, ComponentName, ModelTypeValue, ConfigurationName,
        PersistentID, Id
    Units
        LengthUnit, MassUnit, AngleUnit
    Appearance
        Colors (r,g,b in [0,1] or -1 if unset), Transparency
    Mass properties
        GeometricVolume, Density, CenterOfMass, VolumeMomentsOfInertia
    Geometry
        BoundingBox (minX,minY,minZ,maxX,maxY,maxZ)
    Topology
        VertexList, EdgeList, FaceList, VolumeList, BodyList
    Construction geometry
        PointList, AxisList, CoordinateSystemList
    Configuration
        ParameterList
    Assembly
        ChildComponents — list of Component placements (only used when
        ModelTypeValue == ASSEMBLY).

    Note: There is no `TransformToParent` on CADModelData itself — a model's
    placement is held on the parent's `Component` wrapper.
    """

    # Metadata (order matches CADModelEntryData in CADModelFileData.cs)
    CadName: str = ""
    ModelName: str = ""
    ComponentName: str = ""
    # C# `default(ModelType)` == ASSEMBLY (0). Matched here.
    ModelTypeValue: int = ModelType.ASSEMBLY
    ConfigurationName: str = ""
    PersistentID: str = ""
    Id: int = 0

    # Units
    LengthUnit: str = ""
    MassUnit: str = ""
    AngleUnit: str = ""

    # Appearance
    Colors: List[float] = field(default_factory=lambda: [-1.0, -1.0, -1.0])
    Transparency: float = -1.0

    # Mass properties
    GeometricVolume: float = 0.0
    Density: float = 1.0
    CenterOfMass: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    VolumeMomentsOfInertia: List[float] = field(
        default_factory=lambda: [0.0] * 6
    )

    # Geometry
    BoundingBox: List[float] = field(default_factory=lambda: [0.0] * 6)

    # Topology
    VertexList: List[Vertex] = field(default_factory=list)
    EdgeList: List[Edge] = field(default_factory=list)
    FaceList: List[Face] = field(default_factory=list)
    VolumeList: List[Volume] = field(default_factory=list)
    BodyList: List[Body] = field(default_factory=list)

    # Model parameters
    ParameterList: List[Parameter] = field(default_factory=list)

    # Construction geometry
    PointList: List[Point] = field(default_factory=list)
    AxisList: List[Axis] = field(default_factory=list)
    CoordinateSystemList: List[CoordinateSystem] = field(default_factory=list)

    # Assembly children (only meaningful when ModelTypeValue == ASSEMBLY)
    ChildComponents: List[Component] = field(default_factory=list)

    def __post_init__(self):
        if len(self.Colors) != 3:
            raise ValueError("Colors must have exactly 3 elements")
        if len(self.CenterOfMass) != 3:
            raise ValueError("CenterOfMass must have exactly 3 elements")
        if len(self.VolumeMomentsOfInertia) != 6:
            raise ValueError("VolumeMomentsOfInertia must have exactly 6 elements")
        if len(self.BoundingBox) != 6:
            raise ValueError("BoundingBox must have exactly 6 elements")

    # ------------------------------------------------------------------
    # Serialization (matches CADModelDataWriter.cs)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize this model (and any nested children) to the envelope
        format: {"rootIndex": int, "models": [entry, ...]}.

        Models reachable through `ChildComponents` are walked by object
        identity, assigned indices, and emitted exactly once — matching
        the C# `CADModelDataWriter.CollectModels` algorithm. Output keys
        are camelCase (project convention).
        """
        identity_map: Dict[int, int] = {}
        entries: List[Optional[Dict[str, Any]]] = []

        def collect(model: "CADModelData") -> int:
            key = id(model)
            if key in identity_map:
                return identity_map[key]
            index = len(identity_map)
            identity_map[key] = index
            entries.append(None)  # reserve slot at the assigned index

            for component in model.ChildComponents:
                collect(component.ChildModelData)

            entries[index] = model._to_entry_dict(identity_map)
            return index

        root_index = collect(self)
        return {
            "rootIndex": root_index,
            "models": entries,
        }

    def _to_entry_dict(
        self, identity_map: Dict[int, int]
    ) -> Dict[str, Any]:
        """Build a single entry dict for this model (camelCase keys)."""
        return {
            "cadName": self.CadName,
            "modelName": self.ModelName,
            "componentName": self.ComponentName,
            "modelTypeValue": ModelType(self.ModelTypeValue).name,
            "configurationName": self.ConfigurationName,
            "persistentID": self.PersistentID,
            "id": self.Id,
            "lengthUnit": self.LengthUnit,
            "massUnit": self.MassUnit,
            "angleUnit": self.AngleUnit,
            "colors": list(self.Colors),
            "transparency": self.Transparency,
            "geometricVolume": self.GeometricVolume,
            "density": self.Density,
            "centerOfMass": list(self.CenterOfMass),
            "volumeMomentsOfInertia": list(self.VolumeMomentsOfInertia),
            "boundingBox": list(self.BoundingBox),
            "vertexList": [_entity_to_dict(v) for v in self.VertexList],
            "edgeList": [_entity_to_dict(e) for e in self.EdgeList],
            "faceList": [_entity_to_dict(f) for f in self.FaceList],
            "volumeList": [_entity_to_dict(v) for v in self.VolumeList],
            "bodyList": [_entity_to_dict(b) for b in self.BodyList],
            "parameterList": [
                {"type": int(p.Type), "name": p.Name, "value": p.Value}
                for p in self.ParameterList
            ],
            "pointList": [_entity_to_dict(p) for p in self.PointList],
            "axisList": [_entity_to_dict(a) for a in self.AxisList],
            "coordinateSystemList": [
                _entity_to_dict(c) for c in self.CoordinateSystemList
            ],
            "childComponents": [
                {
                    "transformToParent": list(c.TransformToParent),
                    "childIndex": identity_map[id(c.ChildModelData)],
                }
                for c in self.ChildComponents
            ],
        }

    def to_json(self, indent: Optional[int] = 2) -> str:
        """Serialize to a JSON string in the C# envelope format."""
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, filepath: str, indent: Optional[int] = 2) -> None:
        """Save to a JSON file in the C# envelope format."""
        with open(filepath, "w") as f:
            f.write(self.to_json(indent=indent))
        print(f"Saved CADModelData to: {filepath}")

    # ------------------------------------------------------------------
    # Deserialization (matches CADModelDataReader.cs)
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CADModelData":
        """
        Build a CADModelData from a dict.

        Accepts:
          1. The C# envelope format `{"RootIndex": int, "Models": [...]}`
             — full assembly tree, returns the root model.
          2. A flat single-model dict (legacy / non-envelope), with either
             PascalCase or camelCase keys (case-insensitive).
        """
        if not isinstance(data, dict):
            raise TypeError("CADModelData.from_dict expects a dict")

        models_raw = _ci_get(data, "Models")
        if isinstance(models_raw, list) and models_raw:
            return cls._from_envelope(data, models_raw)

        # Fallback: flat single model
        return cls._from_entry_dict(data, models=None)

    @classmethod
    def _from_envelope(
        cls,
        envelope: Dict[str, Any],
        models_raw: List[Dict[str, Any]],
    ) -> "CADModelData":
        root_index = int(_ci_get(envelope, "RootIndex", 0) or 0)
        if root_index < 0 or root_index >= len(models_raw):
            raise ValueError(
                f"RootIndex {root_index} out of range "
                f"(0..{len(models_raw) - 1})"
            )

        # First pass: build models without children
        models: List[CADModelData] = [
            cls._from_entry_dict(entry, models=None) for entry in models_raw
        ]

        # Second pass: wire up ChildComponents using ChildIndex
        for model, entry in zip(models, models_raw):
            child_components_raw = _ci_get(entry, "ChildComponents") or []
            for comp in child_components_raw:
                transform = _ci_get(comp, "TransformToParent") or _identity_matrix()
                child_index = int(_ci_get(comp, "ChildIndex", 0) or 0)
                if child_index < 0 or child_index >= len(models):
                    raise ValueError(
                        f"ChildIndex {child_index} out of range "
                        f"(0..{len(models) - 1})"
                    )
                model.ChildComponents.append(
                    Component(
                        TransformToParent=list(transform),
                        ChildModelData=models[child_index],
                    )
                )

        return models[root_index]

    @classmethod
    def _from_entry_dict(
        cls,
        entry: Dict[str, Any],
        models: Optional[List["CADModelData"]],
    ) -> "CADModelData":
        """
        Build a CADModelData from a single entry dict (no ChildComponents
        wiring — that happens in the second pass when reading an envelope).

        If `models` is None, ChildComponents in the entry are ignored
        (legacy single-model fallback).
        """
        get = lambda name, default=None: _ci_get(entry, name, default)

        # ModelTypeValue may be int or string (legacy / JsonStringEnumConverter)
        mtv_raw = get("ModelTypeValue", ModelType.ASSEMBLY)
        if isinstance(mtv_raw, str):
            mtv = {
                "ASSEMBLY": ModelType.ASSEMBLY,
                "PART": ModelType.PART,
                "UNKNOWN": ModelType.UNKNOWN,
            }.get(mtv_raw.upper(), ModelType.UNKNOWN)
        else:
            mtv = int(mtv_raw)

        def build_list(key: str, klass) -> list:
            raw = get(key) or []
            return [_build_entity(klass, item) for item in raw]

        return cls(
            CadName=get("CadName", "") or "",
            ModelName=get("ModelName", "") or "",
            ComponentName=get("ComponentName", "") or "",
            ModelTypeValue=mtv,
            ConfigurationName=get("ConfigurationName", "") or "",
            PersistentID=get("PersistentID", "") or "",
            Id=int(get("Id", 0) or 0),
            LengthUnit=get("LengthUnit", "") or "",
            MassUnit=get("MassUnit", "") or "",
            AngleUnit=get("AngleUnit", "") or "",
            Colors=list(get("Colors") or [-1.0, -1.0, -1.0]),
            Transparency=float(get("Transparency", -1.0) or -1.0),
            GeometricVolume=float(get("GeometricVolume", 0.0) or 0.0),
            Density=float(get("Density", 1.0) or 1.0),
            CenterOfMass=list(get("CenterOfMass") or [0.0, 0.0, 0.0]),
            VolumeMomentsOfInertia=list(
                get("VolumeMomentsOfInertia") or [0.0] * 6
            ),
            BoundingBox=list(get("BoundingBox") or [0.0] * 6),
            VertexList=build_list("VertexList", Vertex),
            EdgeList=build_list("EdgeList", Edge),
            FaceList=build_list("FaceList", Face),
            VolumeList=build_list("VolumeList", Volume),
            BodyList=build_list("BodyList", Body),
            ParameterList=build_list("ParameterList", Parameter),
            PointList=build_list("PointList", Point),
            AxisList=build_list("AxisList", Axis),
            CoordinateSystemList=build_list(
                "CoordinateSystemList", CoordinateSystem
            ),
            # ChildComponents wired up by _from_envelope's second pass
        )

    @classmethod
    def load(cls, filepath: str) -> "CADModelData":
        """Load from a JSON file (envelope or legacy flat format)."""
        with open(filepath, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def mass(self) -> float:
        return self.GeometricVolume * self.Density

    @property
    def total_face_count(self) -> int:
        return len(self.FaceList)

    @property
    def total_edge_count(self) -> int:
        return len(self.EdgeList)

    @property
    def total_vertex_count(self) -> int:
        return len(self.VertexList)

    @property
    def total_triangle_count(self) -> int:
        return sum(f.triangle_count for f in self.FaceList)

    @property
    def bounding_box_size(self) -> List[float]:
        return [
            self.BoundingBox[3] - self.BoundingBox[0],
            self.BoundingBox[4] - self.BoundingBox[1],
            self.BoundingBox[5] - self.BoundingBox[2],
        ]

    def is_valid(self) -> bool:
        try:
            self.__post_init__()
            return bool(self.ModelName or self.ComponentName)
        except ValueError:
            return False

    def __repr__(self) -> str:
        return (
            f"CADModelData("
            f"name='{self.ComponentName or self.ModelName}', "
            f"type={ModelType(self.ModelTypeValue).name}, "
            f"faces={self.total_face_count}, "
            f"children={len(self.ChildComponents)}, "
            f"volume={self.GeometricVolume:.6f})"
        )


# =============================================================================
# Internal helpers
# =============================================================================

def _build_entity(klass, data: Any):
    """Build an entity dataclass from a dict (case-insensitive)."""
    if isinstance(data, klass):
        return data
    if not isinstance(data, dict):
        raise TypeError(f"Expected dict for {klass.__name__}, got {type(data).__name__}")

    # Map case-insensitive keys to the dataclass field names
    field_names = {f.name.lower(): f.name for f in klass.__dataclass_fields__.values()}
    kwargs: Dict[str, Any] = {}
    for k, v in data.items():
        canon = field_names.get(k.lower())
        if canon is not None:
            kwargs[canon] = v
    return klass(**kwargs)
