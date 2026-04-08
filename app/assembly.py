"""
assembly.py - Build a cq.Assembly from a declarative YAML spec.

Spec format (see app/assemblies/*.yaml for examples):

    name: my_assembly
    units: mm
    instances:
      - id: plate
        part: box
        params:   { boxx: 40, boxy: 40, boxz: 5 }
        location: { translate: [0, 0, 0], rotate: [0, 0, 0] }
        color:    [0.7, 0.7, 0.75]

Each instance references a part function by name (looked up via the
auto-discovered registry in `models`) and is added to a cq.Assembly with the
given placement. Rotations are XYZ Euler angles in degrees, applied as
T * Rz * Ry * Rx (i.e. rotate X, then Y, then Z, then translate).
"""

from pathlib import Path
from typing import Any, Dict, Union

import cadquery as cq
import yaml

from models import get_model_function


def _make_location(loc: Dict[str, Any]) -> cq.Location:
    """Build a cq.Location from {"translate":[x,y,z], "rotate":[rx,ry,rz]}.

    Translation is in the assembly's length unit; rotations are degrees.
    """
    if not loc:
        return cq.Location()

    t = loc.get("translate", [0.0, 0.0, 0.0])
    r = loc.get("rotate", [0.0, 0.0, 0.0])

    origin = cq.Vector(0, 0, 0)
    rx = cq.Location(origin, cq.Vector(1, 0, 0), r[0])
    ry = cq.Location(origin, cq.Vector(0, 1, 0), r[1])
    rz = cq.Location(origin, cq.Vector(0, 0, 1), r[2])
    tr = cq.Location(cq.Vector(*t))

    return tr * rz * ry * rx


def load_assembly(path: Union[str, Path]) -> cq.Assembly:
    """Load an assembly described by a YAML file and return a cq.Assembly."""
    path = Path(path)
    with path.open() as f:
        spec = yaml.safe_load(f)

    if not isinstance(spec, dict):
        raise ValueError(f"Assembly spec at {path} must be a YAML mapping")

    name = spec.get("name", path.stem)
    assy = cq.Assembly(name=name)

    instances = spec.get("instances") or []
    if not instances:
        raise ValueError(f"Assembly '{name}' has no instances")

    for inst in instances:
        part_name = inst.get("part")
        if not part_name:
            raise ValueError(f"Instance {inst.get('id', '?')!r} missing 'part'")

        func = get_model_function(part_name)
        if func is None:
            raise ValueError(
                f"Unknown part '{part_name}' (not found in models registry)"
            )

        params = inst.get("params") or {}
        try:
            shape = func(**params)
        except TypeError as e:
            raise ValueError(
                f"Bad params for part '{part_name}' in instance "
                f"{inst.get('id', '?')!r}: {e}"
            ) from e

        kwargs: Dict[str, Any] = {
            "name": inst.get("id", part_name),
            "loc": _make_location(inst.get("location")),
        }

        color = inst.get("color")
        if color is not None:
            kwargs["color"] = cq.Color(*color)

        assy.add(shape, **kwargs)

    return assy
