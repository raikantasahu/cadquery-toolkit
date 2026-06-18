#!/usr/bin/env python3
"""
mesh_step_model.py - Generate a volumetric mesh from a STEP file.

Reads a STEP file and generates a volumetric mesh using Gmsh.  Mesh
controls and output format are specified in a YAML config file.

Usage:
    python mesh_step_model.py input.step mesh_config.yaml
    python mesh_step_model.py input.step mesh_config.yaml -o output.json
    python mesh_step_model.py input.step mesh_config.yaml --name my_part

Example config (mesh_config.yaml):

    mesh:
      elementType: tet4             # tet4, tet10, hex8, hex20, hex27
      elementSize: 5.0
      relativeSagTolerance: 0.01    # optional; max sag/radius on curved faces
      # Optional local refinement around a point (tet/recombined-hex).
      # Anchored by coordinate (portable across the CAD->gmsh boundary).
      localRefinement:              # refine only one part near the point
        at: [0, 0, -10]
        fineSize: 0.1
        radius: 2.0
        part: 0                     # optional: 0-based part to confine to
      contactRefinement:            # refine all parts near the point
        at: [0, 0, -10]
        fineSize: 0.05
        radius: 1.0

    output:
      format: xml             # xml, json (MeshData formats), or msh
"""

import argparse
from pathlib import Path

import yaml

from importer import step_importer
from mesher.gmsh_mesher import (
    GmshMesher, MeshValidationError, ExtrusionSpec, RefinementSpec,
)
from mesher import MESH_TYPES
from meshconfig import parse_mesh_basics

_FORMAT_EXTENSIONS = {
    "xml": ".xml",
    "json": ".json",
    "msh": ".msh",
}


def _parse_refinements(mesh_cfg, parser):
    """Build RefinementSpec list from mesh.localRefinement / contactRefinement.

    Each key may hold one entry (a dict) or several (a list of dicts). Every
    entry needs ``at: [x, y, z]`` plus positive ``fineSize`` and ``radius``.
    ``localRefinement`` may add ``part`` (0-based volume index) to disambiguate
    a coordinate shared by several parts.
    """
    specs = []
    for key, scope in (("localRefinement", "local"),
                       ("contactRefinement", "contact")):
        cfg = mesh_cfg.get(key)
        if not cfg:
            continue
        entries = cfg if isinstance(cfg, list) else [cfg]
        for entry in entries:
            if not isinstance(entry, dict):
                parser.error(f"mesh.{key} must be a mapping (or list of them)")
            at = entry.get("at")
            if not (isinstance(at, (list, tuple)) and len(at) == 3):
                parser.error(f"mesh.{key} requires 'at: [x, y, z]'")
            try:
                at = tuple(float(v) for v in at)
                fine_size = float(entry["fineSize"])
                radius = float(entry["radius"])
            except (KeyError, TypeError, ValueError):
                parser.error(
                    f"mesh.{key} requires numeric 'at', 'fineSize', 'radius'")
            if fine_size <= 0 or radius <= 0:
                parser.error(
                    f"mesh.{key}: 'fineSize' and 'radius' must be positive")
            part = entry.get("part")
            if part is not None:
                try:
                    part = int(part)
                except (TypeError, ValueError):
                    parser.error(f"mesh.{key}: 'part' must be an integer index")
            specs.append(RefinementSpec(
                at=at, fine_size=fine_size, radius=radius, scope=scope,
                part_index=part))
    return specs


def _parse_owners(owners_cfg, parser):
    """Return ``(entity_owners, selections)`` from the config's ``owners``.

    ``owners`` may be the legacy mapping ``{PersistentID: label}`` (returned as
    entity_owners) or a geometric list of entries with ``owner``, ``kind``
    (vertex/edge/face/part) and geometry (``at: [x,y,z]`` for vertex/face/part,
    ``samples: [[x,y,z], ...]`` for edge; faces accept ``area``; vertices accept
    ``part`` for disambiguation) — returned as resolver selections.
    """
    if not owners_cfg:
        return {}, None
    if isinstance(owners_cfg, dict):
        return owners_cfg, None
    if not isinstance(owners_cfg, list):
        parser.error("owners must be a mapping (legacy) or a list (geometric)")

    selections = []
    for e in owners_cfg:
        if not isinstance(e, dict):
            parser.error("each geometric owner must be a mapping")
        owner, kind = e.get("owner"), e.get("kind")
        if not owner or kind not in ("vertex", "edge", "face", "part"):
            parser.error("geometric owner needs 'owner' and 'kind' "
                         "(vertex|edge|face|part)")
        if kind == "edge":
            samples = e.get("samples")
            if not (isinstance(samples, list) and len(samples) >= 2):
                parser.error("edge owner needs 'samples': [[x,y,z], ...] (>=2)")
            anchor = {"kind": "edge",
                      "samples": [tuple(map(float, s)) for s in samples]}
        else:
            at = e.get("at")
            if not (isinstance(at, (list, tuple)) and len(at) == 3):
                parser.error(f"{kind} owner needs 'at': [x, y, z]")
            at = tuple(map(float, at))
            if kind == "vertex":
                anchor = {"kind": "vertex", "at": at}
                if e.get("part") is not None:
                    anchor["part"] = int(e["part"])
            elif kind == "part":
                anchor = {"kind": "part", "centroid": at}
            else:
                anchor = {"kind": "face", "centroid": at}
                if e.get("area") is not None:
                    anchor["area"] = float(e["area"])
        selections.append((anchor, str(owner), bool(e.get("required", True))))
    return {}, selections


_DIM_LABEL = {0: "vertex", 1: "edge", 2: "face", 3: "part"}
_DIM_MEASURE = {1: "length", 2: "area", 3: "volume"}


def _list_entities(step_path, name):
    """Print the model's entity manifest (geometry per entity) and return."""
    import gmsh
    from mesher.resolver import GeometricResolver
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(name)
    try:
        gmsh.merge(step_path)
        gmsh.model.occ.synchronize()
        entities = GeometricResolver().describe_entities()
    finally:
        gmsh.finalize()
    _print_manifest(entities)


def _print_manifest(entities):
    by_dim = {}
    for e in entities:
        by_dim.setdefault(e["dim"], []).append(e)
    for dim in range(4):
        ents = by_dim.get(dim, [])
        if not ents:
            continue
        print(f"\n# {len(ents)} {_DIM_LABEL[dim]}(s)")
        for e in sorted(ents, key=lambda x: x["tag"]):
            cx, cy, cz = e["com"]
            line = (f"  {_DIM_LABEL[dim]} {e['tag']}: "
                    f"at [{cx:.4g}, {cy:.4g}, {cz:.4g}]")
            if dim in _DIM_MEASURE:
                line += f"  {_DIM_MEASURE[dim]}={e['meas']:.4g}"
            print(line)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a volumetric mesh from a STEP file.",
    )
    parser.add_argument("input", help="Path to a .step or .stp file")
    parser.add_argument("config", nargs="?",
                        help="Path to a YAML mesh config file")
    parser.add_argument(
        "-o", "--output",
        help="Output path (defaults to <input>.<ext> based on config format)",
    )
    parser.add_argument(
        "--name",
        help="Model name for the Gmsh model (defaults to the input file stem)",
    )
    parser.add_argument(
        "--list-entities", action="store_true",
        help="Print the model's entity manifest (vertex/edge/face/part with "
             "centroid and measure) for authoring geometric references, and "
             "exit.",
    )
    args = parser.parse_args()

    # --- Validate input STEP file ---
    input_path = Path(args.input)
    if not input_path.exists():
        parser.error(f"input file not found: {input_path}")
    if input_path.suffix.lower() not in (".step", ".stp"):
        parser.error(
            f"unexpected input extension '{input_path.suffix}' "
            f"(expected .step or .stp)"
        )

    name = args.name or input_path.stem

    # --- Entity manifest (discovery), then exit ---
    if args.list_entities:
        _list_entities(str(input_path), name)
        return

    if not args.config:
        parser.error("a config file is required (unless --list-entities)")

    # --- Read config ---
    config_path = Path(args.config)
    if not config_path.exists():
        parser.error(f"config file not found: {config_path}")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    mesh_cfg = config.get("mesh", {})
    output_cfg = config.get("output", {})
    entity_owners, owner_selections = _parse_owners(config.get("owners"), parser)

    element_type_str, element_size, relative_sag_tolerance = parse_mesh_basics(
        mesh_cfg, parser.error)
    mesh_type = MESH_TYPES[element_type_str]
    mesh_owner = mesh_cfg.get("owner")

    # Compound extruded-hex config: cap face + through-thickness layers
    # always travel together. Its presence selects structured-hex meshing.
    extrusion = None
    extrusion_cfg = mesh_cfg.get("extrusion")
    if extrusion_cfg:
        cap_face = extrusion_cfg.get("capFace")
        if not cap_face:
            parser.error("mesh.extrusion requires 'capFace' (e.g. F4)")
        if element_type_str != "hex8":
            parser.error(
                "mesh.extrusion produces hex8; set elementType: hex8 "
                f"(got '{element_type_str}')"
            )
        num_layers = int(extrusion_cfg.get("numLayers", 1))
        if num_layers < 1:
            parser.error(f"numLayers must be >= 1 (got {num_layers})")
        if isinstance(cap_face, (list, tuple)) and len(cap_face) == 3:
            area = extrusion_cfg.get("capFaceArea")
            extrusion = ExtrusionSpec(
                cap_face_at=tuple(float(c) for c in cap_face),
                cap_face_area=float(area) if area is not None else None,
                num_layers=num_layers)
        else:
            extrusion = ExtrusionSpec(cap_face=str(cap_face),
                                      num_layers=num_layers)

    # Local/contact refinement (tet & recombined-hex paths only).
    refinements = _parse_refinements(mesh_cfg, parser)
    if refinements and extrusion is not None:
        parser.error(
            "mesh.localRefinement/contactRefinement cannot be combined with "
            "mesh.extrusion (extruded hex)")

    output_format = output_cfg.get("format", "msh")
    if output_format not in _FORMAT_EXTENSIONS:
        parser.error(
            f"unknown output format '{output_format}' "
            f"(expected one of: {', '.join(_FORMAT_EXTENSIONS)})"
        )

    # --- Resolve output path ---
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix(_FORMAT_EXTENSIONS[output_format])

    name = args.name or input_path.stem
    owner = mesh_owner or name

    # --- Mesh ---
    model = step_importer.read(str(input_path))

    mesher = GmshMesher(model, model_name=name)
    try:
        stats = mesher.generate(
            mesh_type,
            element_size=element_size,
            relative_sag_tolerance=relative_sag_tolerance,
            extrusion=extrusion,
            refinements=refinements,
        )
    except MeshValidationError as e:
        mesher.finalize()
        parser.error(str(e))

    if stats.get("warning"):
        print(f"Warning: {stats['warning']}")

    if output_format == "xml":
        mesher.save_as_meshdata_xml(
            str(output_path), owner=owner, entity_owners=entity_owners,
            selections=owner_selections,
        )
    elif output_format == "json":
        mesher.save_as_meshdata_json(
            str(output_path), owner=owner, entity_owners=entity_owners,
            selections=owner_selections,
        )
    else:
        mesher.save(str(output_path))

    print(
        f"Wrote {output_path} "
        f"(nodes={stats['node_count']}, "
        f"elements={stats['element_count']}, "
        f"types={stats['element_types']})"
    )

    mesher.finalize()


if __name__ == "__main__":
    main()
