"""app_core - GTK-free application controller (Architecture-Review T2.1).

Holds the domain logic the GUI window (`cad_app`) and the CLIs share: build/
convert a model, resolve picked entities to geometric anchors, mesh, and save/
export. No `gi`/Gtk import — so it is unit-testable headlessly and reusable by
`app_cli`. UI concerns (dialogs, picking interaction, status text) stay in the
wrappers; the core **raises** typed errors and the wrappers present them.

See docs/plans/Core-UI-Separation.md.
"""
import inspect
import logging
from typing import Optional

import cadquery as cq

from converter import assembly_to_modeldata, part_to_modeldata
from exporter import cadmodeldata_exporter, step_exporter
from mesher import (
    HAS_GMSH, create_mesh, save_mesh_json, save_mesh_meshdata_json,
    ExtrusionSpec, RefinementSpec,
)
from mesher import save_mesh as _save_mesh_native
from model.tessellation import (
    anchor_for_pick, create_polydatas_per_part, enumerate_part_labels,
)
from models.parts import get_all_parts
from models.assemblies import get_all_assemblies

logger = logging.getLogger(__name__)


class AppError(Exception):
    """A core operation failed for a user-facing reason (no model, an
    unresolved cap face / refinement vertex, missing gmsh). Wrappers turn it
    into a dialog (GUI) or stderr + nonzero exit (CLI)."""


class AppCore:
    def __init__(self):
        self._model = None
        self._name = "model"
        self._params = None
        self._sig = None
        self._model_data = None            # cached CADModelData dict
        self._face_owners: list = []       # [(pid, label)]
        self._vertex_owners: list = []     # [(pid, label)]
        self._edge_owners: list = []       # [(pid, label)]
        self._mesh = None
        self._stats = None

    # ---------- model lifecycle ----------
    def set_model(self, model, name, parameters=None, param_signature=None):
        """Load an already-built model (the GUI path: ModelBuilder built it).

        Short-circuits when the *same* model object is re-set with unchanged
        name/params/signature: the imported-STEP panel re-sets its one stable
        cached model on every menu action, so without this the CADModelData
        cache would be rebuilt each time. A registry builder hands a fresh model
        object on every build, so its cache is invalidated exactly as before.
        """
        name = name or "model"
        if (model is self._model and name == self._name
                and parameters == self._params
                and param_signature == self._sig):
            return
        self._model = model
        self._name = name
        self._params = parameters
        self._sig = param_signature
        self._model_data = None            # invalidate cache

    def build_model(self, name, params=None, kind="part"):
        """Build a registry model by name + params (the CLI path)."""
        registry = get_all_parts() if kind == "part" else get_all_assemblies()
        if name not in registry:
            raise AppError(f"unknown {kind} model {name!r}")
        fn = registry[name]
        model = fn(**(params or {}))
        self.set_model(model, name, parameters=params or {},
                       param_signature=inspect.signature(fn))

    def model_data(self) -> dict:
        """CADModelData dict for the current model (cached). Raises on no model
        or a conversion failure."""
        if self._model is None:
            raise AppError("No model set.")
        if self._model_data is None:
            if isinstance(self._model, cq.Assembly):
                md = assembly_to_modeldata(self._model)
            else:
                md = part_to_modeldata(
                    self._model, name=self._name,
                    parameters=self._params, param_signature=self._sig)
            self._model_data = md.to_dict()
        return self._model_data

    def part_labels(self):
        """Ordered per-part labels for the current model — assembly child names
        (or the single part's name), one per solid in volume order. Tags the
        viewer mesh so an assembly's parts can be hidden/shown by name. Returns
        None when unavailable, so the viewer falls back to ``Part 1..N``."""
        try:
            labels = enumerate_part_labels(self.model_data())
        except Exception:
            return None
        return labels or None

    def clear(self):
        self.finalize()
        self._model = None
        self._model_data = None
        self._face_owners = []
        self._vertex_owners = []
        self._edge_owners = []

    # ---------- selection state (owners for mesh-entity containers) ----------
    def set_face_owners(self, items):
        self._face_owners = list(items or [])

    def set_vertex_owners(self, items):
        self._vertex_owners = list(items or [])

    def set_edge_owners(self, items):
        self._edge_owners = list(items or [])

    def selection_anchors(self):
        """``(selections, entity_owners)`` for a MeshData save. Picked
        faces/vertices/edges become geometric resolver selections; per-part
        ``P{i}`` fragment owners stay legacy (part order is preserved)."""
        md = self.model_data()
        selections = []
        for pid, label in (self._face_owners + self._vertex_owners
                           + self._edge_owners):
            anchor = anchor_for_pick(md, pid)
            if anchor is None:
                # A pick that no longer resolves (a stale/unknown PID after the
                # model changed) is dropped — loudly, naming it, so a missing
                # container can't pass for "no such entity" (loud-safety-net).
                logger.warning(
                    "owner %r references %s, which does not resolve on the "
                    "current model — dropping it (no container written).",
                    label, pid)
                continue
            selections.append((anchor, label))
        entity_owners: dict = {}
        try:
            for i, label in enumerate(enumerate_part_labels(md)):
                entity_owners.setdefault(f"P{i}", label)
        except Exception:
            pass
        return (selections or None), (entity_owners or None)

    # ---------- geometric anchors (also used by the GUI pickers) ----------
    def face_anchor(self, pid):
        """Geometric anchor for a picked face PID (or None)."""
        return anchor_for_pick(self.model_data(), pid)

    def vertex_anchor(self, pid):
        """Picked vertex PID -> ``(coord, part_index)`` (or None)."""
        anchor = anchor_for_pick(self.model_data(), pid)
        if anchor and anchor.get("kind") == "vertex":
            return (anchor["at"], anchor["part"])
        return None

    def edge_anchor(self, pid):
        """Picked edge PID -> sample points along the edge (or None)."""
        anchor = anchor_for_pick(self.model_data(), pid)
        if anchor and anchor.get("kind") == "edge":
            return anchor["samples"]
        return None

    # ---------- mesh ----------
    def mesh(self, config: dict) -> dict:
        """Build specs from ``config`` (resolving cap face + refinement vertices
        geometrically), run create_mesh, store mesh + stats, return stats."""
        if not HAS_GMSH:
            raise AppError("Gmsh is not installed.")
        if self._model is None:
            raise AppError("No model set.")
        extrusion = self._build_extrusion(config.get("extrusion"))
        refinements = self._build_refinements(config.get("refinements") or [])
        self.finalize()                    # drop any prior mesh/session
        mesh, stats = create_mesh(
            self._model, config["mesh_type"], config["element_size"],
            model_name=self._name,
            relative_sag_tolerance=config.get("relative_sag_tolerance"),
            extrusion=extrusion, refinements=refinements)
        self._mesh = mesh
        self._stats = stats
        return stats

    def _build_extrusion(self, ex) -> Optional[ExtrusionSpec]:
        if not ex:
            return None
        cap_pid = ex.get("cap_face")
        if not cap_pid:
            raise AppError("Extruded hex needs a cap face.")
        anchor = self.face_anchor(cap_pid)
        if anchor is None:
            raise AppError(
                "Could not resolve the cap face on the current model.")
        return ExtrusionSpec(
            cap_face_at=anchor["centroid"], cap_face_area=anchor.get("area"),
            num_layers=ex["num_layers"])

    def _build_refinements(self, regions) -> list:
        specs = []
        for region in regions:
            scope = region["scope"]
            if region.get("edge_pid"):
                samples = self.edge_anchor(region["edge_pid"])
                if samples is None:
                    raise AppError(
                        f"Refinement edge {region['edge_pid']} could not be "
                        "resolved on the current model.")
                # Edges aren't part-disambiguated by the anchor, so a local edge
                # refinement takes its body from an explicit part_index (or the
                # mesher defaults to the first resolved curve's volume).
                specs.append(RefinementSpec(
                    edge_samples=samples, fine_size=region["fine_size"],
                    radius=region["radius"], scope=scope,
                    part_index=region.get("part_index") if scope == "local"
                    else None))
                continue
            anchor = self.vertex_anchor(region["vertex_pid"])
            if anchor is None:
                raise AppError(
                    f"Refinement vertex {region['vertex_pid']} could not be "
                    "resolved on the current model.")
            coord, part_index = anchor
            specs.append(RefinementSpec(
                at=coord, fine_size=region["fine_size"],
                radius=region["radius"], scope=scope,
                part_index=part_index if scope == "local" else None))
        return specs

    def has_mesh(self) -> bool:
        return self._mesh is not None

    def mesh_stats(self) -> Optional[dict]:
        return self._stats

    @property
    def mesh_object(self):
        return self._mesh

    def finalize(self):
        if self._mesh is not None:
            self._mesh.finalize()
            self._mesh = None
            self._stats = None

    # ---------- outputs ----------
    def save_mesh(self, path: str, fmt: str, model_name: str = None):
        if self._mesh is None:
            raise AppError("No mesh to save.")
        name = model_name or self._name or "model"
        if fmt == "meshdata_json":
            selections, entity_owners = self.selection_anchors()
            save_mesh_meshdata_json(
                self._mesh, path, owner=name,
                entity_owners=entity_owners, selections=selections)
        elif fmt == "json":
            save_mesh_json(self._mesh, path, title=name)
        else:
            _save_mesh_native(self._mesh, path)

    def export_model(self, path: str, fmt: str):
        if self._model is None:
            raise AppError("No model set.")
        if fmt == "step":
            step_exporter.export(self._model, path)
        elif isinstance(self._model, cq.Assembly):
            cadmodeldata_exporter.export(self._model, path)
        else:
            cadmodeldata_exporter.export(
                self._model, path, name=self._name,
                parameters=self._params, param_signature=self._sig)
