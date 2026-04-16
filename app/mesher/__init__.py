"""
mesher - Volumetric mesh generation functionality
"""

from .gmsh_mesher import (
    HAS_GMSH,
    GmshMesher,
    MeshType,
    create_mesh,
    save_mesh,
    save_mesh_json,
    generate_pyvista_mesh,
    gmsh_to_pyvista,
    mesh_json_to_pyvista,
)

from . import export  # noqa: F401 — register submodule

__all__ = [
    'HAS_GMSH',
    'GmshMesher',
    'MeshType',
    'create_mesh',
    'save_mesh',
    'save_mesh_json',
    'generate_pyvista_mesh',
    'gmsh_to_pyvista',
    'mesh_json_to_pyvista',
    'export',
]
