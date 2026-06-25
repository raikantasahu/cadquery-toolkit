"""Shared scene scaffolding for the CAD viewers.

``_setup_scene`` (grid floor, 3-light setup, axes, iso camera, view-preset
keys), ``_combined_bounds`` (bounds union), and ``_add_visibility_checkboxes``
(per-part hide/show column). GTK-free.
"""
import numpy as np
import pyvista as pv


def _add_visibility_checkboxes(plotter, part_entries,
                               extra_actors_by_label=None):
    """Add a column of checkbox widgets to toggle each part's visibility.

    Each part actor gets one checkbox; clicking it flips the actor's
    visibility. Labels are added as text actors next to each checkbox.

    ``extra_actors_by_label`` optionally maps a part label to a second actor
    (e.g. the part's vertex point-cloud in vertex-pick mode) that is toggled
    in lockstep with the part actor, so hiding a part also hides — and, since
    VTK pickers honor visibility, un-picks — its vertices.

    PyVista positions widgets in pixel coordinates with origin at the
    lower-left of the render window, so the column grows upward from
    near the bottom. The starting ``y`` is set above the help-text band.
    """
    extra_actors_by_label = extra_actors_by_label or {}
    button_size = 18
    pad = 6
    y = 50
    for label, actor, _mesh in part_entries:
        extra_actor = extra_actors_by_label.get(label)

        def _make_cb(a=actor, extra=extra_actor):
            def cb(state):
                v = 1 if state else 0
                a.SetVisibility(v)
                if extra is not None:
                    extra.SetVisibility(v)
                plotter.render()
            return cb
        plotter.add_checkbox_button_widget(
            _make_cb(),
            value=True,
            position=(10, y),
            size=button_size,
            border_size=2,
            color_on='#8bc34a',
            color_off='#555555',
            background_color='#222222',
        )
        plotter.add_text(
            label,
            position=(10 + button_size + 8, y + 2),
            font_size=9,
            color='white',
            shadow=True,
        )
        y += button_size + pad


def _combined_bounds(meshes):
    """Union of the bounds of ``meshes`` as ``(xmin, xmax, ymin, ymax, zmin,
    zmax)``; a safe unit cube when there are none."""
    combined = None
    for mesh in meshes:
        b = mesh.bounds
        if combined is None:
            combined = list(b)
        else:
            combined[0] = min(combined[0], b[0])
            combined[1] = max(combined[1], b[1])
            combined[2] = min(combined[2], b[2])
            combined[3] = max(combined[3], b[3])
            combined[4] = min(combined[4], b[4])
            combined[5] = max(combined[5], b[5])
    return tuple(combined) if combined else (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)


def _setup_scene(plotter, bounds):
    """Shared viewer scaffold: grid floor, 3-light setup, axes, iso camera, and
    the view-preset key bindings (f/b/l/g/t/u/i). Used by all three viewers
    (``show_pyvista``, ``show_pick_viewer``, ``show_volumetric_viewer``) so the
    scene setup stays identical; each caller adds its own help text and any
    extra keys (e.g. wireframe).

    Args:
        plotter: The active pv.Plotter.
        bounds: A 6-tuple ``(xmin, xmax, ymin, ymax, zmin, zmax)``.

    Returns:
        ``(center, distance)`` for any caller that needs them.
    """
    center = np.array([
        (bounds[0] + bounds[1]) / 2,
        (bounds[2] + bounds[3]) / 2,
        (bounds[4] + bounds[5]) / 2,
    ])
    size = max(
        bounds[1] - bounds[0],
        bounds[3] - bounds[2],
        bounds[5] - bounds[4],
    )
    distance = size * 2.5

    grid_size = max(200, size * 4)
    grid = pv.Plane(
        center=(center[0], center[1], bounds[4] - size * 0.1),
        direction=(0, 0, 1),
        i_size=grid_size,
        j_size=grid_size,
        i_resolution=20,
        j_resolution=20,
    )
    grid_actor = plotter.add_mesh(grid, color='#333333', style='wireframe',
                                  line_width=1, opacity=0.5)
    grid_actor.PickableOff()  # never let the floor steal a pick

    plotter.enable_3_lights()
    plotter.show_axes()
    plotter.camera_position = [
        (center[0] + distance, center[1] + distance, center[2] + distance),
        tuple(center),
        (0, 0, 1),
    ]

    def _view(direction):
        positions = {
            'front':  ((center[0], center[1] - distance, center[2]), (0, 0, 1)),
            'back':   ((center[0], center[1] + distance, center[2]), (0, 0, 1)),
            'left':   ((center[0] - distance, center[1], center[2]), (0, 0, 1)),
            'right':  ((center[0] + distance, center[1], center[2]), (0, 0, 1)),
            'top':    ((center[0], center[1], center[2] + distance), (0, 1, 0)),
            'bottom': ((center[0], center[1], center[2] - distance), (0, 1, 0)),
            'iso':    ((center[0] + distance, center[1] + distance,
                        center[2] + distance), (0, 0, 1)),
        }
        pos, up = positions[direction]
        plotter.camera_position = [pos, tuple(center), up]
        plotter.render()

    plotter.add_key_event('f', lambda: _view('front'))
    plotter.add_key_event('b', lambda: _view('back'))
    plotter.add_key_event('l', lambda: _view('left'))
    plotter.add_key_event('g', lambda: _view('right'))
    plotter.add_key_event('t', lambda: _view('top'))
    plotter.add_key_event('u', lambda: _view('bottom'))
    plotter.add_key_event('i', lambda: _view('iso'))

    return center, distance
