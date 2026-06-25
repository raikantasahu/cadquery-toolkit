"""Display constants for the CAD viewers (colors + scene background).

A leaf module imported by the picking/scene/viewer layers, so keeping the
constants here avoids an import cycle. GTK-free.
"""
import os


DEFAULT_COLOR = '#667eea'
VOLUMETRIC_COLOR = '#4fc3f7'
# Viewer scene background. Defaults to a near-black dark grey; override with the
# VIEWER_BACKGROUND_COLOR env var (any pyvista-accepted color name or hex, e.g.
# VIEWER_BACKGROUND_COLOR=white). Read once at import, so set it before launch.
BACKGROUND_COLOR = os.environ.get('VIEWER_BACKGROUND_COLOR', '#1a1a1a')
PICK_HIGHLIGHT_COLOR = '#ffeb3b'
