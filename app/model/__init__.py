"""
Model package for CAD data structures.

This package provides data classes for representing CAD geometry
in a format compatible with the C# CADModelData class.
"""

from .cad_modeldata import (
    # Enums
    ModelType,
    EntityType,
    ParameterType,
    # Entity classes
    Vertex,
    Edge,
    Face,
    Volume,
    Body,
    Parameter,
    Point,
    Axis,
    CoordinateSystem,
    Component,
    # Main model class
    CAD_ModelData,
)

__all__ = [
    'ModelType',
    'EntityType',
    'ParameterType',
    'Vertex',
    'Edge',
    'Face',
    'Volume',
    'Body',
    'Parameter',
    'Point',
    'Axis',
    'CoordinateSystem',
    'Component',
    'CAD_ModelData',
]
