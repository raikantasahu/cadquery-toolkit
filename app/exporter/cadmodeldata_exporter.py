"""
cadmodeldata_exporter - Write CadQuery parts and assemblies as CADModelData JSON.

A thin wrapper: ask the `converter` package to turn the CadQuery thing into
a CADModelData and call `.save(path)` to write the envelope-format JSON.
"""

from typing import Any, Union

import cadquery as cq

from converter import to_modeldata
from model.CADModelData import CADModelData


def export(
    thing: Union[cq.Assembly, cq.Workplane, cq.Shape, CADModelData],
    path: str,
    **kwargs: Any,
) -> CADModelData:
    """
    Write a CadQuery object (or an already-built CADModelData) to a JSON file.

    Returns the CADModelData that was written, in case the caller wants to
    introspect it (e.g. count children, walk faces) without re-reading the
    file.

    Keyword arguments are forwarded to `converter.to_modeldata`. For parts,
    callers commonly pass `name=`, `parameters=`, and `param_signature=`.
    """
    if isinstance(thing, CADModelData):
        model_data = thing
    else:
        model_data = to_modeldata(thing, **kwargs)
    model_data.save(path)
    return model_data
