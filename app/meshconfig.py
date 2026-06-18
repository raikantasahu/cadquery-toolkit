"""Shared mesh-config parsing for the CLIs (GTK-free).

The registry CLI (app_cli) and the STEP CLI (mesh_step_model) parse the same
``mesh`` block — element type, size, sag tolerance — the same way, against the
single mesh-type registry (mesher.MESH_TYPES). They still diverge on how owners /
refinements / cap faces are *referenced* (PID for registry models vs coordinate
for foreign STEP), so that parsing stays per-CLI; only the basics are shared.
"""
from mesher import MESH_TYPES


def parse_mesh_basics(mesh_cfg, error):
    """Validate and return ``(element_type, element_size, relative_sag_tol)``.

    ``mesh_cfg`` is the YAML ``mesh`` block (a dict). ``error`` is a callable
    that raises with a message (e.g. ``argparse.ArgumentParser.error``).
    ``element_type`` is the validated name (a key of ``mesher.MESH_TYPES``);
    ``relative_sag_tol`` is a positive float or None.
    """
    element_type = mesh_cfg.get("elementType", "tet4")
    if element_type not in MESH_TYPES:
        error(f"unknown elementType '{element_type}' "
              f"(expected one of: {', '.join(MESH_TYPES)})")

    element_size = float(mesh_cfg.get("elementSize", 5.0))

    relative_sag_tol = mesh_cfg.get("relativeSagTolerance")
    if relative_sag_tol is not None:
        relative_sag_tol = float(relative_sag_tol)
        if relative_sag_tol <= 0:
            error(f"relativeSagTolerance must be positive "
                  f"(got {relative_sag_tol})")

    return element_type, element_size, relative_sag_tol
