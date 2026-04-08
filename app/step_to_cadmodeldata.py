#!/usr/bin/env python3
"""
step_to_cadmodeldata.py - Convert a STEP file to CADModelData JSON.

Reads a STEP file and writes it as a CADModelData envelope JSON. If the
STEP file contains assembly structure, the output is a multi-model
envelope (1 ASSEMBLY + N PARTs) with component names and per-instance
transforms recovered from the STEP product hierarchy. If the STEP file
contains a single shape, the output is a 1-model PART envelope.

Usage:
    python step_to_cadmodeldata.py input.step
    python step_to_cadmodeldata.py input.step -o output.json
    python step_to_cadmodeldata.py input.step --name my_part
"""

import argparse
from pathlib import Path

from converter import step_model_to_cadmodeldata
from exporter import cadmodeldata_exporter
from importer import step_importer


def main():
    parser = argparse.ArgumentParser(
        description="Convert a STEP file to CADModelData JSON.",
    )
    parser.add_argument("input", help="Path to a .step or .stp file")
    parser.add_argument(
        "-o", "--output",
        help="Output JSON path (defaults to <input>.json next to the input)",
    )
    parser.add_argument(
        "--name",
        help="modelName / componentName for the CADModelData entry "
             "(defaults to the input file stem)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        parser.error(f"input file not found: {input_path}")
    if input_path.suffix.lower() not in (".step", ".stp"):
        parser.error(
            f"unexpected input extension '{input_path.suffix}' "
            f"(expected .step or .stp)"
        )

    output_path = (
        Path(args.output) if args.output
        else input_path.with_suffix(".json")
    )
    name = args.name or input_path.stem

    model = step_importer.read(str(input_path))
    model_data = step_model_to_cadmodeldata(model, name=name)
    cadmodeldata_exporter.export(model_data, str(output_path))

    if model_data.ChildComponents:
        print(
            f"Wrote {output_path} "
            f"({1 + len(model_data.ChildComponents)} models: "
            f"1 assembly + {len(model_data.ChildComponents)} parts)"
        )
    else:
        print(
            f"Wrote {output_path} "
            f"(1 part: faces={len(model_data.FaceList)}, "
            f"edges={len(model_data.EdgeList)}, "
            f"vertices={len(model_data.VertexList)})"
        )


if __name__ == "__main__":
    main()
