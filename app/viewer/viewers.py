"""Window-composition functions for the CAD viewers.

Each ``show_*`` builds a pyvista Plotter, lays out actors, attaches the shared
scene scaffold and (where relevant) a picker, and blocks on ``plotter.show()``.
GTK-free; the GObject controller (``viewer.model_viewer.ModelViewer``) drives
these.
"""
from typing import Any, Dict, List

import numpy as np
import pyvista as pv

from model.tessellation import edge_lines_polydata
from mesh_parts import split_grid_by_part

from .style import BACKGROUND_COLOR, DEFAULT_COLOR, VOLUMETRIC_COLOR
from .picking import (
    _setup_multi_edge_picking,
    _setup_multi_face_picking,
    _setup_multi_vertex_picking,
)
from .scene import (
    _add_visibility_checkboxes,
    _combined_bounds,
    _setup_scene,
)


def show_pick_viewer(parts, title="Pick Faces", pick_state=None,
                     pick_mode="faces", single=False):
    """Open a PyVista viewer with per-part actors, visibility toggles, and
    face or vertex picking.

    Args:
        parts: List of ``(label, pv.PolyData)`` from
            ``create_polydatas_per_part(..., with_face_index=True)``.
        title: Window title.
        pick_state: Required dict with a ``picks`` list; the caller
            reads ``picks`` (list of ``(pid, label)``) after the window
            closes.
        pick_mode: ``"faces"`` (default) picks CAD faces; ``"vertices"``
            renders each part's topological vertices as a pickable point
            cloud (faces become non-pickable context) and picks those;
            ``"edges"`` renders each part's edges as pickable line actors and
            picks those. In every mode a left-click toggles the entity under
            the cursor.

    This is a blocking call — it returns when the viewer window is closed.
    """
    plotter = pv.Plotter(title=title)
    plotter.set_background(BACKGROUND_COLOR)

    # One actor per part so visibility can be toggled independently.
    part_entries: List[tuple] = []
    for label, mesh in parts:
        actor = plotter.add_mesh(
            mesh,
            color=DEFAULT_COLOR,
            show_edges=False,
            lighting=True,
            smooth_shading=True,
            specular=0.5,
            specular_power=30,
        )
        part_entries.append((label, actor, mesh))

    _setup_scene(plotter, _combined_bounds(m for _label, m in parts))

    # In vertex/edge mode, build the pickable entity actors per part (faces
    # become context only) BEFORE the checkboxes, so each checkbox toggles the
    # part's faces and its picked-entity actor together.
    vertex_entries: List[tuple] = []
    edge_entries: List[tuple] = []
    extra_actors_by_label: Dict[str, Any] = {}
    if pick_state is not None and pick_mode == "vertices":
        for label, actor, mesh in part_entries:
            actor.PickableOff()
            vp = mesh.field_data.get("vertex_points")
            vpids = mesh.field_data.get("vertex_pids")
            if vp is None or vpids is None or len(vpids) == 0:
                continue
            points = np.asarray(vp, dtype=np.float64).reshape(-1, 3)
            vtx_actor = plotter.add_points(
                points, color='#ff5252', render_points_as_spheres=True,
                point_size=11,
            )
            extra_actors_by_label[label] = vtx_actor
            vertex_entries.append(
                (label, vtx_actor, points, [str(p) for p in vpids]),
            )
    elif pick_state is not None and pick_mode == "edges":
        for label, actor, mesh in part_entries:
            actor.PickableOff()
            ep = mesh.field_data.get("edge_points")
            eo = mesh.field_data.get("edge_offsets")
            epids = mesh.field_data.get("edge_pids")
            if ep is None or eo is None or epids is None or len(epids) == 0:
                continue
            line_mesh = edge_lines_polydata(ep, eo, epids)
            edge_actor = plotter.add_mesh(
                line_mesh, color='#ff5252', line_width=3,
                render_lines_as_tubes=True, lighting=False,
            )
            extra_actors_by_label[label] = edge_actor
            edge_entries.append((label, edge_actor, line_mesh))

    _add_visibility_checkboxes(
        plotter, part_entries, extra_actors_by_label=extra_actors_by_label,
    )

    if pick_state is not None and pick_mode == "vertices":
        _setup_multi_vertex_picking(plotter, vertex_entries, pick_state,
                                    single=single)
    elif pick_state is not None and pick_mode == "edges":
        _setup_multi_edge_picking(plotter, edge_entries, pick_state,
                                  single=single)
    elif pick_state is not None:
        _setup_multi_face_picking(plotter, part_entries, pick_state,
                                  single=single)

    pick_help = {"vertices": "Left-click=Pick vertex",
                 "edges": "Left-click=Pick edge"}.get(
                     pick_mode, "Left-click=Pick face")
    plotter.add_text(
        "Views: F=Front  B=Back  L=Left  G=Right  T=Top  U=Bottom  I=Iso\n"
        f"R=Reset  {pick_help}  Q=Close",
        position='lower_left',
        font_size=8,
        color='white',
        shadow=True,
    )

    plotter.show()


def show_pyvista(mesh, title="CAD Viewer", volumetric=False):
    """Open a PyVista plotter with standard CAD viewer styling.

    This is a blocking call — it returns when the viewer window is closed.

    Args:
        mesh: A PyVista PolyData or UnstructuredGrid.
        title: Window title.
        volumetric: If True, use volumetric styling (edges visible).

    For face picking (with per-part hide/show), use ``show_pick_viewer``.
    """
    plotter = pv.Plotter(title=title)
    plotter.set_background(BACKGROUND_COLOR)

    if volumetric:
        actor = plotter.add_mesh(
            mesh,
            color=VOLUMETRIC_COLOR,
            show_edges=True,
            edge_color='#333333',
            opacity=1.0,
            smooth_shading=False,
            lighting=True,
        )
    else:
        actor = plotter.add_mesh(
            mesh,
            color=DEFAULT_COLOR,
            show_edges=False,
            lighting=True,
            smooth_shading=True,
            specular=0.5,
            specular_power=30,
        )

    _setup_scene(plotter, mesh.bounds)

    wireframe_state = [False]

    def _toggle_wireframe():
        wireframe_state[0] = not wireframe_state[0]
        if wireframe_state[0]:
            actor.GetProperty().SetRepresentationToWireframe()
        else:
            actor.GetProperty().SetRepresentationToSurface()
        plotter.render()

    plotter.add_key_event('z', _toggle_wireframe)

    plotter.add_text(
        "Views: F=Front  B=Back  L=Left  G=Right  T=Top  U=Bottom  I=Iso\n"
        "R=Reset  Z=Wireframe  Q=Close",
        position='lower_left',
        font_size=8,
        color='white',
        shadow=True,
    )

    plotter.show()


def _run_parts_viewer(parts, title, volumetric):
    """Render a per-part viewer: one actor per ``(label, mesh)``, the shared
    scene scaffold, a per-part visibility-checkbox column for an assembly
    (>1 part), and a ``Z`` wireframe toggle across all parts. Shared by the
    volumetric mesh viewer and the surface CAD model viewer; ``volumetric`` only
    selects actor styling (edged volumetric vs smooth surface).

    The Part-vs-Assembly decision is data-driven (the part count), so a single
    part shows no control and an assembly gets one checkbox per part.

    This is a blocking call — it returns when the viewer window is closed.
    """
    multi = len(parts) > 1

    plotter = pv.Plotter(title=title)
    plotter.set_background(BACKGROUND_COLOR)

    part_entries: List[tuple] = []
    for label, mesh in parts:
        if volumetric:
            actor = plotter.add_mesh(
                mesh, color=VOLUMETRIC_COLOR, show_edges=True,
                edge_color='#333333', opacity=1.0, smooth_shading=False,
                lighting=True,
            )
        else:
            actor = plotter.add_mesh(
                mesh, color=DEFAULT_COLOR, show_edges=False, lighting=True,
                smooth_shading=True, specular=0.5, specular_power=30,
            )
        part_entries.append((label, actor, mesh))

    _setup_scene(plotter, _combined_bounds(m for _label, m in parts))

    if multi:
        _add_visibility_checkboxes(plotter, part_entries)

    wireframe_state = [False]

    def _toggle_wireframe():
        wireframe_state[0] = not wireframe_state[0]
        for _label, actor, _mesh in part_entries:
            prop = actor.GetProperty()
            if wireframe_state[0]:
                prop.SetRepresentationToWireframe()
            else:
                prop.SetRepresentationToSurface()
        plotter.render()

    plotter.add_key_event('z', _toggle_wireframe)

    parts_help = "  Checkboxes=Hide/show parts" if multi else ""
    plotter.add_text(
        "Views: F=Front  B=Back  L=Left  G=Right  T=Top  U=Bottom  I=Iso\n"
        f"R=Reset  Z=Wireframe{parts_help}  Q=Close",
        position='lower_left',
        font_size=8,
        color='white',
        shadow=True,
    )

    plotter.show()


def show_volumetric_viewer(ugrid, title="Volumetric Mesh Viewer"):
    """Display a volumetric mesh, with per-part hide/show for assemblies.

    Splits the grid by its part tagging (:func:`split_grid_by_part`); a
    single-part mesh renders as one actor with no controls, a multi-part mesh as
    one actor per part plus a visibility-checkbox column. Data-driven, so the
    same rule holds for the live and the loaded mesh paths.

    This is a blocking call — it returns when the viewer window is closed.
    """
    _run_parts_viewer(split_grid_by_part(ugrid), title, volumetric=True)


def show_model_viewer(parts, title="CAD Model Viewer"):
    """Display a surface CAD model split per part, with per-part hide/show for
    assemblies (>1 part). ``parts`` is ``[(label, pv.PolyData)]`` from
    :func:`model.tessellation.create_polydatas_per_part`. The geometry-view
    counterpart of :func:`show_volumetric_viewer`; a single part renders like
    ``show_pyvista`` with no control.

    This is a blocking call — it returns when the viewer window is closed.
    """
    _run_parts_viewer(parts, title, volumetric=False)
