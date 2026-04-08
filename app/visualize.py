#!/usr/bin/env python3
"""
visualize.py - Standalone CLI for viewing CAD models and volumetric meshes.

Accepts a file path and auto-detects the format:
  - .json with "faceList"            → CAD_ModelData (surface view)
  - .json with "nodes"/"elements"    → mesh JSON     (volumetric view)
  - .msh                             → Gmsh mesh     (volumetric view)
  - .step / .stp                     → STEP model    (surface view)

Usage:
    python visualize.py model.json
    python visualize.py mesh.json
    python visualize.py mesh.msh
    python visualize.py part.step
    python visualize.py              # opens a file selection dialog
"""

import argparse
import json
import sys

import gmsh

from converter import step_model_to_cadmodeldata
from dialogs import ask_open_file
from importer import step_importer
from mesher import gmsh_to_pyvista, mesh_json_to_pyvista
from viewer import create_polydata_from_model_data, show_pyvista


def load_file(path):
    """Load a file and return (pyvista_mesh, title, is_volumetric)."""
    ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''

    if ext == 'msh':
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        try:
            gmsh.open(path)
            return gmsh_to_pyvista(), path, True
        finally:
            gmsh.finalize()

    if ext in ('step', 'stp'):
        model = step_importer.read(path)
        model_data = step_model_to_cadmodeldata(model, name=path)
        return create_polydata_from_model_data(model_data.to_dict()), path, False

    if ext == 'json':
        with open(path) as f:
            data = json.load(f)

        if 'nodes' in data and 'elements' in data:
            return mesh_json_to_pyvista(data), data.get('title', path), True

        # CAD_ModelData envelope: { rootIndex, models: [...] }
        # (case-insensitive so PascalCase from a C# writer works too)
        models = data.get('models') or data.get('Models')
        if isinstance(models, list) and models:
            root_index = int(data.get('rootIndex', data.get('RootIndex', 0)) or 0)
            root = models[root_index] if 0 <= root_index < len(models) else {}
            title = root.get('modelName') or root.get('ModelName') or path
            return create_polydata_from_model_data(data), title, False

        # Legacy flat single-model CAD_ModelData
        if 'faceList' in data or 'FaceList' in data:
            title = data.get('modelName') or data.get('ModelName') or path
            return create_polydata_from_model_data(data), title, False

        print("Error: JSON file does not look like a CAD model or mesh")
        print("  Expected 'models' (CAD_ModelData envelope), 'faceList' "
              "(CAD_ModelData flat), or 'nodes'+'elements' (mesh)")
        sys.exit(1)

    print(f"Error: unsupported file extension '.{ext}'")
    print("Supported formats: .json, .msh, .step, .stp")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Visualize a CAD model or mesh file.",
    )
    parser.add_argument(
        'file', nargs='?', default=None,
        help="Path to a .json, .msh, .step, or .stp file (opens dialog if omitted)",
    )
    args = parser.parse_args()

    path = args.file or ask_open_file()
    if not path:
        print("No file selected.")
        sys.exit(0)

    mesh, title, volumetric = load_file(path)
    show_pyvista(mesh, title=title, volumetric=volumetric)


if __name__ == '__main__':
    main()
