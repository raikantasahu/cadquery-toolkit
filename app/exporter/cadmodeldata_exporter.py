"""
cadmodeldata_exporter - Write CadQuery parts and assemblies as CAD_ModelData JSON.

A thin wrapper: ask the `converter` package to turn the CadQuery thing into
a CAD_ModelData and call `.save(path)` to write the envelope-format JSON.
"""

from typing import Any, Union

import cadquery as cq

from converter import to_modeldata
from model.cad_modeldata import CAD_ModelData


def export(
    thing: Union[cq.Assembly, cq.Workplane, cq.Shape, CAD_ModelData],
    path: str,
    **kwargs: Any,
) -> CAD_ModelData:
    """
    Write a CadQuery object (or an already-built CAD_ModelData) to a JSON file.

    Returns the CAD_ModelData that was written, in case the caller wants to
    introspect it (e.g. count children, walk faces) without re-reading the
    file.

    Keyword arguments are forwarded to `converter.to_modeldata`. For parts,
    callers commonly pass `name=`, `parameters=`, and `param_signature=`.
    """
    if isinstance(thing, CAD_ModelData):
        model_data = thing
    else:
        model_data = to_modeldata(thing, **kwargs)
    model_data.save(path)
    return model_data
