"""
importer - Format-specific readers for CAD models.

Each submodule exposes a single `read(path)` function that returns an
in-memory CadQuery object (cq.Workplane / cq.Shape / cq.Assembly):

    from importer import step_importer

    model = step_importer.read("input.step")

The returned object can then be passed to the `converter` package to
build a CADModelData, or written back out via the `exporter` package.
"""

from . import step_importer

__all__ = [
    "step_importer",
]
