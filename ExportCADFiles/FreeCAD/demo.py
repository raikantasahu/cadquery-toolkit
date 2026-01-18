"""
demo.py - Command-line demo of CadQuery model creation

This script demonstrates creating models and exporting them without the GUI.
"""

import create_models
from cadquery import exporters
import json
from pathlib import Path


def create_demo_models():
    """Create several demo models and export them"""

    # Create output directory
    output_dir = Path("demo_output")
    output_dir.mkdir(exist_ok=True)

    demos = [
        {
            "name": "simple_box",
            "function": create_models.box,
            "params": {"boxx": 10, "boxy": 20, "boxz": 30}
        },
        {
            "name": "mounting_bracket",
            "function": create_models.bracket,
            "params": {"basex": 40, "basey": 40, "basez": 5, "holex": 30, "holey": 30}
        },
        {
            "name": "gear",
            "function": create_models.parametric_gear,
            "params": {"num_teeth": 16, "outer_radius": 25, "inner_radius": 10,
                      "tooth_depth": 3, "thickness": 5}
        },
        {
            "name": "cylinder_holes",
            "function": create_models.cylinder_with_holes,
            "params": {"radius": 20, "height": 30, "hole_radius": 8}
        }
    ]

    for demo in demos:
        print(f"\nCreating {demo['name']}...")

        # Create the model
        model = demo["function"](**demo["params"])

        # Export STEP file
        step_path = output_dir / f"{demo['name']}.step"
        exporters.export(model, str(step_path))
        print(f"  STEP: {step_path}")

        # Create JSON metadata
        json_path = output_dir / f"{demo['name']}.json"
        model_data = {
            "model_type": demo["function"].__name__,
            "parameters": demo["params"],
            "step_file": f"{demo['name']}.step",
            "description": demo["function"].__doc__ or ""
        }

        with open(json_path, 'w') as f:
            json.dump(model_data, f, indent=2)
        print(f"  JSON: {json_path}")

    print(f"\n✓ All demo models created in {output_dir}/")
    print(f"\nTo view the models:")
    print(f"  1. Install FreeCAD: flatpak install flathub org.freecadweb.FreeCAD")
    print(f"  2. Open any .step file: flatpak run org.freecadweb.FreeCAD demo_output/simple_box.step")


if __name__ == "__main__":
    create_demo_models()
