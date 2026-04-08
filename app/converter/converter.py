"""
converter.converter - Public CadQuery → CADModelData conversion functions.

Three entry points:

    part_to_modeldata(cq_object, ...)     -> CADModelData (PART)
    assembly_to_modeldata(cq_assembly, ...) -> CADModelData (ASSEMBLY)
    to_modeldata(thing, ...)              -> CADModelData (type-dispatching)

Internally, per-Part conversion uses the FreeCAD-bound geometry walker in
`converter._freecad`. The assembly walk is pure-Python and does identity-based
deduplication so a shape used multiple times in the same assembly produces
exactly one PART entry referenced by multiple `Component`s.
"""

import inspect
from typing import Any, Dict, List, Optional, Union

import cadquery as cq

from model.CADModelData import (
    Body,
    CADModelData,
    Component,
    Edge,
    Face,
    ModelType,
    Parameter,
    Vertex,
    Volume,
)

from ._freecad import _FreeCADShape, build_parameter_dicts


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _location_to_matrix(loc: cq.Location) -> List[float]:
    """Convert a cq.Location to a 16-element row-major 4x4 affine matrix.

    Layout:
        [m00, m01, m02, m03,
         m10, m11, m12, m13,
         m20, m21, m22, m23,
           0,   0,   0,   1]
    The last column of the top three rows holds the translation.
    """
    trsf = loc.wrapped.Transformation()
    return [
        trsf.Value(1, 1), trsf.Value(1, 2), trsf.Value(1, 3), trsf.Value(1, 4),
        trsf.Value(2, 1), trsf.Value(2, 2), trsf.Value(2, 3), trsf.Value(2, 4),
        trsf.Value(3, 1), trsf.Value(3, 2), trsf.Value(3, 3), trsf.Value(3, 4),
        0.0, 0.0, 0.0, 1.0,
    ]


def _coerce_to_workplane_or_shape(obj: Any) -> Any:
    """Accept a Workplane or a raw cq.Shape; reject anything else."""
    if isinstance(obj, cq.Workplane):
        return obj
    if isinstance(obj, cq.Shape):
        return obj
    raise TypeError(
        f"Expected cq.Workplane or cq.Shape, got {type(obj).__name__}"
    )


# ----------------------------------------------------------------------
# Part conversion
# ----------------------------------------------------------------------

def part_to_modeldata(
    cq_object: Any,
    name: str = "CadQuery Part",
    cad_name: str = "CadQuery",
    length_unit: str = "mm",
    mass_unit: str = "kg",
    angle_unit: str = "degrees",
    parameters: Optional[Dict[str, Any]] = None,
    param_signature: Optional[inspect.Signature] = None,
) -> CADModelData:
    """
    Convert a single CadQuery part (Workplane or Shape) to a CADModelData.

    The geometry is reported in the shape's local frame. Per-instance
    placement (rotation/translation) is the caller's responsibility — it
    belongs on a parent assembly's `Component.TransformToParent`, not on
    the PART itself.
    """
    shape = _coerce_to_workplane_or_shape(cq_object)
    extracted = _FreeCADShape(shape).extract()
    properties = extracted["properties"]

    return CADModelData(
        CadName=cad_name,
        ModelName=name,
        ComponentName=name,
        ModelTypeValue=ModelType.PART,
        PersistentID=f"CQ_{name}",
        LengthUnit=length_unit,
        MassUnit=mass_unit,
        AngleUnit=angle_unit,
        GeometricVolume=properties["volume"],
        CenterOfMass=list(properties["centerOfMass"]),
        VolumeMomentsOfInertia=list(properties["volumeMomentsOfInertia"]),
        BoundingBox=list(properties["boundingBox"]),
        VertexList=[
            Vertex(
                PersistentID=v["persistentID"],
                Location=list(v["location"]),
            )
            for v in extracted["vertices"]
        ],
        EdgeList=[
            Edge(
                PersistentID=e["persistentID"],
                Start=e["start"],
                End=e["end"],
                VertexLocations=list(e["vertexLocations"]),
            )
            for e in extracted["edges"]
        ],
        FaceList=[
            Face(
                PersistentID=f["persistentID"],
                Area=f["area"],
                EdgeList=list(f["edgeList"]),
                VertexLocations=list(f["vertexLocations"]),
                Connectivity=list(f["connectivity"]),
                Colors=list(f["colors"]),
                Transparency=f["transparency"],
            )
            for f in extracted["faces"]
        ],
        VolumeList=[
            Volume(
                PersistentID=v["persistentID"],
                FaceList=list(v["faceList"]),
            )
            for v in extracted["volumes"]
        ],
        BodyList=[
            Body(
                PersistentID=b["persistentID"],
                VolumeList=list(b["volumeList"]),
            )
            for b in extracted["bodies"]
        ],
        ParameterList=[
            Parameter(Type=p["type"], Name=p["name"], Value=p["value"])
            for p in build_parameter_dicts(parameters, param_signature)
        ],
    )


# ----------------------------------------------------------------------
# Assembly conversion
# ----------------------------------------------------------------------

def assembly_to_modeldata(
    cq_assembly: cq.Assembly,
    cad_name: str = "CadQuery",
    length_unit: str = "mm",
    mass_unit: str = "kg",
    angle_unit: str = "degrees",
) -> CADModelData:
    """
    Convert a cq.Assembly to a CADModelData (ASSEMBLY).

    Each direct child of `cq_assembly` becomes a PART CADModelData (geometry
    in the child's local frame). The returned root holds one Component per
    child with the per-instance transform on `Component.TransformToParent`.

    Identity-based deduplication: if the same Python object instance is used
    as the geometry of multiple children, it is converted to a single PART
    CADModelData and referenced by multiple Components. Two separately
    constructed but geometrically identical shapes (e.g. two fresh
    `hex_bolt(...)` calls) will NOT be deduped — that would require content
    hashing of the BRep, which is out of scope.

    Only the flat case (one level of children, as produced by the YAML loader)
    is supported. Nested sub-assemblies are flagged.
    """
    name = cq_assembly.name or "assembly"
    cache: Dict[int, CADModelData] = {}
    components: List[Component] = []

    for child in cq_assembly.children:
        if child.children:
            raise NotImplementedError(
                f"Nested sub-assemblies are not supported yet "
                f"(child '{child.name}' has its own children)"
            )
        if child.obj is None:
            raise ValueError(f"Assembly child '{child.name}' has no geometry")

        key = id(child.obj)
        part = cache.get(key)
        if part is None:
            part = part_to_modeldata(
                child.obj,
                name=child.name or "part",
                cad_name=cad_name,
                length_unit=length_unit,
                mass_unit=mass_unit,
                angle_unit=angle_unit,
            )
            cache[key] = part

        components.append(
            Component(
                TransformToParent=_location_to_matrix(child.loc),
                ChildModelData=part,
            )
        )

    return CADModelData(
        CadName=cad_name,
        ModelName=name,
        ComponentName=name,
        ModelTypeValue=ModelType.ASSEMBLY,
        PersistentID=f"CQ_{name}",
        LengthUnit=length_unit,
        MassUnit=mass_unit,
        AngleUnit=angle_unit,
        ChildComponents=components,
    )


# ----------------------------------------------------------------------
# STEP-loaded model conversion
# ----------------------------------------------------------------------

def step_model_to_cadmodeldata(
    model: Union[cq.Assembly, cq.Workplane, cq.Shape],
    name: Optional[str] = None,
    cad_name: str = "STEP",
    length_unit: str = "mm",
    mass_unit: str = "kg",
    angle_unit: str = "degrees",
) -> CADModelData:
    """
    Convert a CadQuery object loaded from a STEP file to a CADModelData.

    The reading itself lives in `importer.step_importer.read(path)`; this
    function takes the in-memory result and dispatches by type:

      - cq.Assembly  → assembly_to_modeldata (multi-model envelope with
                       PART children + per-instance Components)
      - cq.Workplane / cq.Shape → part_to_modeldata (single PART)

    The defaults differ from `to_modeldata` in one place: `cad_name`
    defaults to `"STEP"` rather than `"CadQuery"`, reflecting that the
    geometry came from a STEP file.

    Note: STEP precision (~12 significant digits on floats) means recovered
    transforms and coordinates may differ from the originals at the
    1e-12-of-magnitude level. STEP also does not carry CadQuery build
    parameters, so the returned CADModelData has an empty parameterList.
    """
    units_kwargs = dict(
        cad_name=cad_name,
        length_unit=length_unit,
        mass_unit=mass_unit,
        angle_unit=angle_unit,
    )

    if isinstance(model, cq.Assembly):
        if name:
            model.name = name
        return assembly_to_modeldata(model, **units_kwargs)

    if isinstance(model, (cq.Workplane, cq.Shape)):
        return part_to_modeldata(
            model,
            name=name or "part",
            **units_kwargs,
        )

    raise TypeError(
        f"Expected cq.Assembly, cq.Workplane, or cq.Shape, "
        f"got {type(model).__name__}"
    )


# ----------------------------------------------------------------------
# Type-dispatching convenience
# ----------------------------------------------------------------------

def to_modeldata(
    thing: Union[cq.Assembly, cq.Workplane, cq.Shape],
    **kwargs: Any,
) -> CADModelData:
    """
    Convert any CadQuery thing (Assembly, Workplane, Shape) to a CADModelData.

    Dispatches by type:
      - cq.Assembly → assembly_to_modeldata
      - cq.Workplane / cq.Shape → part_to_modeldata

    Keyword arguments are forwarded to the chosen function. Note that
    part-only kwargs (parameters, param_signature) are not accepted by
    assembly_to_modeldata; pass them only when you know the input is a part.

    For STEP-loaded models, prefer `step_model_to_cadmodeldata` — it has
    STEP-flavored defaults (cad_name="STEP"). For STEP files on disk, read
    them first via `importer.step_importer.read(path)`.
    """
    if isinstance(thing, cq.Assembly):
        return assembly_to_modeldata(thing, **kwargs)
    if isinstance(thing, (cq.Workplane, cq.Shape)):
        return part_to_modeldata(thing, **kwargs)
    raise TypeError(
        f"Expected cq.Assembly, cq.Workplane, or cq.Shape, "
        f"got {type(thing).__name__}"
    )
