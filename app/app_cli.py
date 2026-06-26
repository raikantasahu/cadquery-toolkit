"""app_cli - headless CLI for the registry-model path (Core-UI-Separation P2).

Builds a model from the parts/assemblies registry, meshes it, and saves —
a thin wrapper over the GTK-free AppCore (the same core the GUI uses). For
external STEP input use `mesh_step_model.py` instead; this is the
build-from-registry counterpart.

    app_cli MODEL [--kind part|assembly] [--param k=v ...]
                  [--config mesh.yaml] [-o OUT] [--list-entities]

The YAML config mirrors the GUI's controls but references entities by their
CADModelData PID (F#/V#, deterministic for a registry model — use
--list-entities to discover them):

    mesh:
      elementType: tet4
      elementSize: 8.0
      relativeSagTolerance: 0.01      # optional
      extrusion: {capFace: F4, numLayers: 3}            # optional
      refinements:                                       # optional
        - {scope: contact, vertexPid: V2, fineSize: 0.5, radius: 2.0}
    owners:                                              # optional
      - {kind: face, pid: F8, label: fixed-bottom}
      - {kind: vertex, pid: V0, label: contact}
      - {kind: edge, pid: E5, label: contact-line}
    output: {format: meshdata_json}                      # json | meshdata_json | msh
"""
import argparse
import logging
import sys

import yaml

from app_core import AppCore, AppError
from meshconfig import parse_mesh_basics
from model.tessellation import anchor_for_pick, create_polydatas_per_part

_EXT = {"meshdata_json": ".json", "json": ".json", "msh": ".msh"}


def _coerce(value: str):
    """CLI scalar -> int/float/bool/str (parametric models want numbers)."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def _parse_params(pairs, parser):
    params = {}
    for pair in pairs or []:
        if "=" not in pair:
            parser.error(f"--param must be key=value (got {pair!r})")
        key, value = pair.split("=", 1)
        params[key] = _coerce(value)
    return params


def _mesh_config(mesh_cfg, error):
    """Translate the YAML mesh block into the core's config dict. Basics
    (type/size/sag) go through the shared parser; extrusion/refinements are
    PID-based (registry-model specific)."""
    element_type, element_size, sag = parse_mesh_basics(mesh_cfg, error)
    ex = mesh_cfg.get("extrusion")
    core_ex = None
    if ex:
        core_ex = {"cap_face": ex.get("capFace"),
                   "num_layers": int(ex.get("numLayers", 1))}
    refinements = [
        {"scope": r["scope"], "vertex_pid": r["vertexPid"],
         "fine_size": float(r["fineSize"]), "radius": float(r["radius"])}
        for r in mesh_cfg.get("refinements", [])
    ]
    return {
        "mesh_type": element_type,
        "element_size": element_size,
        "relative_sag_tolerance": sag,
        "extrusion": core_ex,
        "refinements": refinements,
    }


def _apply_owners(core, owners_cfg, parser):
    face_owners, vertex_owners, edge_owners = [], [], []
    for o in owners_cfg or []:
        kind, pid, label = o.get("kind"), o.get("pid"), o.get("label")
        if not (kind and pid and label):
            parser.error("each owner needs 'kind', 'pid', 'label'")
        if kind == "face":
            face_owners.append((pid, label))
        elif kind == "vertex":
            vertex_owners.append((pid, label))
        elif kind == "edge":
            edge_owners.append((pid, label))
        else:
            parser.error(f"owner kind must be face|vertex|edge (got {kind!r})")
    core.set_face_owners(face_owners)
    core.set_vertex_owners(vertex_owners)
    core.set_edge_owners(edge_owners)


def _list_entities(core):
    """Print the model's CADModelData PIDs + geometry, for authoring configs."""
    md = core.model_data()
    import numpy as np
    for label, pd in create_polydatas_per_part(md, with_face_index=True):
        fd = pd.field_data
        print(f"\n# part: {label}")
        for pid in (str(v) for v in fd.get("vertex_pids", [])):
            xyz = anchor_for_pick(md, pid)["at"]
            print(f"  {pid}: at [{xyz[0]:.4g}, {xyz[1]:.4g}, {xyz[2]:.4g}]")
        for pid in (str(v) for v in fd.get("face_pids", [])):
            a = anchor_for_pick(md, pid)
            c = a["centroid"]
            print(f"  {pid}: centroid [{c[0]:.4g}, {c[1]:.4g}, {c[2]:.4g}]"
                  f"  area={a.get('area', 0):.4g}")
        for pid in (str(v) for v in fd.get("edge_pids", [])):
            s = np.asarray(anchor_for_pick(md, pid)["samples"], dtype=float)
            c = s.mean(axis=0)
            print(f"  {pid}: near [{c[0]:.4g}, {c[1]:.4g}, {c[2]:.4g}]"
                  f"  ({len(s)} pts)")


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Mesh a registry model (part/assembly) via AppCore.")
    parser.add_argument("model", help="registry model name")
    parser.add_argument("--kind", choices=("part", "assembly"), default="part")
    parser.add_argument("--param", action="append", metavar="K=V",
                        help="build parameter (repeatable)")
    parser.add_argument("-c", "--config", help="YAML mesh config")
    parser.add_argument("-o", "--output", help="output mesh path")
    parser.add_argument("--list-entities", action="store_true",
                        help="print the model's PIDs + geometry and exit")
    args = parser.parse_args(argv)

    core = AppCore()
    try:
        core.build_model(args.model, _parse_params(args.param, parser),
                         kind=args.kind)
    except AppError as e:
        parser.error(str(e))

    if args.list_entities:
        _list_entities(core)
        return 0

    config = {}
    if args.config:
        with open(args.config) as f:
            config = yaml.safe_load(f) or {}

    output_format = config.get("output", {}).get("format", "msh")
    out = args.output or (args.model + _EXT.get(output_format, ".msh"))

    _apply_owners(core, config.get("owners"), parser)
    core_config = _mesh_config(config.get("mesh", {}), parser.error)
    try:
        stats = core.mesh(core_config)
        core.save_mesh(out, output_format, model_name=args.model)
    except Exception as e:
        core.finalize()
        print(f"error: {e}", file=sys.stderr)
        return 1
    core.finalize()

    print(f"Wrote {out} (nodes={stats['node_count']}, "
          f"elements={stats['element_count']}, types={stats['element_types']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
