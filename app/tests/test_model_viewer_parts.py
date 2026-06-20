"""Per-part hide/show in the surface CAD model viewer — the data it gates on.

The geometry view shows a per-part hide/show column iff
``create_polydatas_per_part`` yields more than one part (an assembly); a single
part renders with no control. This pins that data contract headlessly (the
rendering/checkbox interaction is the manual GUI check). Mirrors the volumetric
mesh viewer's gating, now shared via ``_run_parts_viewer``.
"""
import cadquery as cq

from model.tessellation import create_polydatas_per_part
from models.assemblies import get_assembly_function

from helpers import cadmodeldata


def test_assembly_splits_into_named_parts():
    """An assembly → >1 part with the assembly's child names → control shown."""
    model = get_assembly_function("bolted_single_lap_joint")()
    parts = create_polydatas_per_part(cadmodeldata(model))
    labels = [label for label, _pd in parts]
    assert labels == ["bottom-plate", "top-plate", "bolt-1"]


def test_single_part_is_one_part():
    """A single part → one part → the viewer shows no control (gate is >1)."""
    parts = create_polydatas_per_part(
        cadmodeldata(cq.Workplane("XY").box(10, 20, 30)))
    assert len(parts) == 1
