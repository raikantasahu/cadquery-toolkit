"""
entity_picker.py - Reusable 3D entity picker for mesh controls.

This is the canonical pattern for any mesh control that needs the user to
designate geometry — an extrusion cap face today, and (by the same call) a
face, edge, or vertex for some future control. Build the model's CADModelData
dict, then call :func:`pick_entities`; it opens the model viewer in the matching
pick mode and returns the picked ``(persistent_id, label)`` entities.

Pattern for a new mesh control that needs a picked entity::

    model_data = self._current_model_data()           # build once
    picked = pick_entities(self, model_data, kind="face", single=True)
    # picked is (pid, label) or None  (single=True)
    #   or a list of (pid, label)     (single=False)

``single=True`` returns one entity (e.g. an extrusion cap face — the last one
picked); ``single=False`` returns the whole set (e.g. entity-container owners).
The viewer pick mode is chosen from ``kind``; add new kinds in ``_PICK_MODES``
as the viewer gains support for them.
"""

from viewer import ModelViewer

# kind -> ModelViewer pick_mode. Faces, vertices, and edges are all pickable;
# every control that uses pick_entities() gets each kind for free.
_PICK_MODES = {
    "face": "faces",
    "vertex": "vertices",
    "edge": "edges",
}
# kind -> the viewer property holding the picks after the window closes.
_PICK_RESULTS = {
    "face": "picked_faces",
    "vertex": "picked_vertices",
    "edge": "picked_edges",
}


def pick_entities(parent, model_data, kind="face", single=True,
                  initial=None, title=None):
    """Open the 3D viewer to pick mesh entities of ``kind`` from ``model_data``.

    Args:
        parent: Parent GTK window (desensitized while the viewer is open), or
            None.
        model_data: The model's CADModelData as a dict (``to_dict()`` output).
        kind: ``"face"``, ``"vertex"``, or ``"edge"``. Raises ValueError for
            anything else.
        single: True returns the last-picked ``(pid, label)`` or None; False
            returns a list of ``(pid, label)``.
        initial: Optional list of ``(pid, label)`` to pre-highlight.
        title: Optional window title; defaults from ``kind``/``single``.

    Returns:
        ``(pid, label)`` or None when ``single``; otherwise a list (possibly
        empty). Returns the empty result if the model fails to load.
    """
    if kind not in _PICK_MODES:
        raise ValueError(
            f"unsupported pick kind {kind!r}; expected one of "
            f"{sorted(_PICK_MODES)}"
        )

    viewer = ModelViewer()
    if not viewer.set_mesh_from_dict(model_data, with_face_index=True):
        return None if single else []

    if title is None:
        title = "Pick " + kind.capitalize() + ("" if single else "s")

    if parent is not None:
        parent.set_sensitive(False)
    try:
        viewer.show_viewer(
            title=title,
            pick_faces=True,
            pick_mode=_PICK_MODES[kind],
            initial_picks=list(initial or []),
            single=single,
        )
    finally:
        if parent is not None:
            parent.set_sensitive(True)
            parent.present()

    picks = list(getattr(viewer, _PICK_RESULTS[kind]))
    if single:
        return picks[-1] if picks else None
    return picks
