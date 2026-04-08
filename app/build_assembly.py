#!/usr/bin/env python3
"""
build_assembly.py - Build an assembly from a YAML spec.

Loads a declarative assembly spec (see app/assemblies/*.yaml), instantiates
each part via the auto-discovered models registry, places them with the
specified transforms, and either exports the result or opens the viewer.

The output format is chosen by the file extension:
    .json           → CAD_ModelData envelope (1 ASSEMBLY + N PART entries)
    .step / .stp    → STEP file (preserves component structure via cadquery)

Usage:
    python build_assembly.py assemblies/bolted_plate.yaml --view
    python build_assembly.py assemblies/bolted_plate.yaml -o bolted_plate.json
    python build_assembly.py assemblies/bolted_plate.yaml -o bolted_plate.step
    python build_assembly.py assemblies/bolted_plate.yaml -o out.json --view
"""

import argparse
from pathlib import Path

from assembly import load_assembly
from converter import assembly_to_modeldata
from exporter import cadmodeldata_exporter, step_exporter


def main():
    parser = argparse.ArgumentParser(
        description="Build an assembly from a YAML spec.",
    )
    parser.add_argument("input", help="Path to assembly YAML spec")
    parser.add_argument(
        "-o", "--output",
        help="Output path. Format is chosen by extension: "
             ".json (CAD_ModelData envelope) or .step/.stp (STEP).",
    )
    parser.add_argument(
        "--view", action="store_true",
        help="Open the viewer after building",
    )
    args = parser.parse_args()

    if not args.output and not args.view:
        parser.error("specify --output and/or --view")

    out_ext = Path(args.output).suffix.lower() if args.output else ""
    if args.output and out_ext not in (".step", ".stp", ".json"):
        parser.error(
            f"unsupported output extension '{out_ext}' "
            f"(use .json, .step, or .stp)"
        )

    assy = load_assembly(args.input)

    if out_ext in (".step", ".stp"):
        step_exporter.export(assy, args.output)
        print(f"Wrote {args.output}")

    model_data = None
    if args.output and out_ext == ".json":
        model_data = cadmodeldata_exporter.export(assy, args.output)
        print(
            f"Wrote {args.output} "
            f"({1 + len(model_data.ChildComponents)} models: 1 assembly + "
            f"{len(model_data.ChildComponents)} parts)"
        )

    if args.view:
        # Convert once if we haven't already; the viewer reads the envelope.
        if model_data is None:
            model_data = assembly_to_modeldata(assy)
        from viewer import create_polydata_from_model_data, show_pyvista
        show_pyvista(
            create_polydata_from_model_data(model_data.to_dict()),
            title=assy.name,
        )


if __name__ == "__main__":
    main()
