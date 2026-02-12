"""
mesh_viewer.py - Display a PyVista volumetric mesh in an interactive viewer.
"""

from .model_viewer import ModelViewer


def show_mesh(ugrid, on_closed=None, on_error=None):
    """Show a PyVista mesh in an interactive viewer window.

    This is a blocking call — it returns when the viewer is closed.

    Args:
        ugrid: PyVista UnstructuredGrid to display.
        on_closed: Callback invoked when the viewer is closed.
        on_error: Callback invoked with an error message string on failure.

    Returns:
        True if the viewer opened successfully, False otherwise.
    """
    viewer = ModelViewer()
    if on_closed:
        viewer.connect('viewer-closed', lambda v: on_closed())
    if on_error:
        viewer.connect('error', lambda v, msg: on_error(msg))

    if not viewer.set_mesh_from_pyvista(ugrid):
        return False

    viewer.show_viewer(title="Volumetric Mesh Viewer")
    return True
