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
      # Optional local refinement around picked vertices (tet/recombined-hex).
      localRefinement:              # refine only the vertex's own part
        vertex: V7
        fineSize: 0.1
        radius: 2.0
      contactRefinement:            # refine all parts meeting at the vertex
        vertex: V12
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
    GmshMesher, MeshType, MeshValidationError, ExtrusionSpec, RefinementSpec,
)

_MESH_TYPES = {
    "tet4": MeshType.TET4,
    "tet10": MeshType.TET10,
    "hex8": MeshType.HEX8,
    "hex20": MeshType.HEX20,
    "hex27": MeshType.HEX27,
}

_FORMAT_EXTENSIONS = {
    "xml": ".xml",
    "json": ".json",
    "msh": ".msh",
}


def _parse_refinements(mesh_cfg, parser):
    """Build RefinementSpec list from mesh.localRefinement / contactRefinement.

    Each key may hold one entry (a dict) or several (a list of dicts). Every
    entry needs ``vertex`` (e.g. V7) plus positive ``fineSize`` and ``radius``.
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
            vertex = entry.get("vertex")
            if not vertex:
                parser.error(f"mesh.{key} requires 'vertex' (e.g. V7)")
            try:
                fine_size = float(entry["fineSize"])
                radius = float(entry["radius"])
            except (KeyError, TypeError, ValueError):
                parser.error(
                    f"mesh.{key} requires numeric 'fineSize' and 'radius'")
            if fine_size <= 0 or radius <= 0:
                parser.error(
                    f"mesh.{key}: 'fineSize' and 'radius' must be positive")
            specs.append(RefinementSpec(
                vertex=str(vertex), fine_size=fine_size, radius=radius,
                scope=scope))
    return specs


def main():
    parser = argparse.ArgumentParser(
        description="Generate a volumetric mesh from a STEP file.",
    )
    parser.add_argument("input", help="Path to a .step or .stp file")
    parser.add_argument("config", help="Path to a YAML mesh config file")
    parser.add_argument(
        "-o", "--output",
        help="Output path (defaults to <input>.<ext> based on config format)",
    )
    parser.add_argument(
        "--name",
        help="Model name for the Gmsh model (defaults to the input file stem)",
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

    # --- Read config ---
    config_path = Path(args.config)
    if not config_path.exists():
        parser.error(f"config file not found: {config_path}")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    mesh_cfg = config.get("mesh", {})
    output_cfg = config.get("output", {})
    entity_owners = config.get("owners", {})

    element_type_str = mesh_cfg.get("elementType", "tet4")
    if element_type_str not in _MESH_TYPES:
        parser.error(
            f"unknown elementType '{element_type_str}' "
            f"(expected one of: {', '.join(_MESH_TYPES)})"
        )
    mesh_type = _MESH_TYPES[element_type_str]
    element_size = float(mesh_cfg.get("elementSize", 5.0))
    mesh_owner = mesh_cfg.get("owner")

    relative_sag_tolerance = mesh_cfg.get("relativeSagTolerance")
    if relative_sag_tolerance is not None:
        relative_sag_tolerance = float(relative_sag_tolerance)
        if relative_sag_tolerance <= 0:
            parser.error(
                f"relativeSagTolerance must be positive "
                f"(got {relative_sag_tolerance})"
            )

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
        extrusion = ExtrusionSpec(cap_face=str(cap_face), num_layers=num_layers)

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
        )
    elif output_format == "json":
        mesher.save_as_meshdata_json(
            str(output_path), owner=owner, entity_owners=entity_owners,
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
