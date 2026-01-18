"""
cadquery_examples.py - Example CadQuery models exported to CAD_ModelData

This script demonstrates how to create CadQuery models and export them
to CAD_ModelData format.

Requirements:
    pip install cadquery numpy requests

Usage:
    python cadquery_examples.py
"""

import cadquery as cq
from cadquery_exporter import CADModelExporter, export_cadquery_model


def example1_simple_box():
    """Create a simple box"""
    print("Example 1: Simple Box")
    print("-" * 50)
    
    # Create a 10x10x10 box
    result = cq.Workplane("XY").box(10, 10, 10)
    
    # Export
    exporter = CADModelExporter(result, model_name="Simple Box")
    exporter.save_to_file("example1_box.json")
    
    # Print summary
    model_data = exporter.export()
    print(f"Exported: {model_data['modelName']}")
    print(f"  Vertices: {len(model_data['vertexList'])}")
    print(f"  Edges: {len(model_data['edgeList'])}")
    print(f"  Faces: {len(model_data['faceList'])}")
    print(f"  Volume: {model_data['geometricVolume']:.2f} mm³")
    print()


def example2_bracket():
    """Create a mounting bracket"""
    print("Example 2: Mounting Bracket")
    print("-" * 50)
    
    # Create a mounting bracket
    result = (
        cq.Workplane("XY")
        .box(40, 40, 5)  # Base plate
        .faces(">Z")
        .workplane()
        .rect(30, 30)
        .cutThruAll()  # Center hole
        .faces(">Z")
        .workplane()
        .pushPoints([(-12, 12), (12, 12), (-12, -12), (12, -12)])
        .circle(2)
        .cutThruAll()  # Mounting holes
        .faces(">Y")
        .workplane()
        .move(0, 2.5)
        .rect(10, 5)
        .extrude(20)  # Mounting tab
    )
    
    # Export
    exporter = CADModelExporter(result, model_name="Mounting Bracket")
    exporter.save_to_file("example2_bracket.json")
    
    model_data = exporter.export()
    print(f"Exported: {model_data['modelName']}")
    print(f"  Vertices: {len(model_data['vertexList'])}")
    print(f"  Edges: {len(model_data['edgeList'])}")
    print(f"  Faces: {len(model_data['faceList'])}")
    print(f"  Volume: {model_data['geometricVolume']:.2f} mm³")
    print()


def example3_cylinder_with_holes():
    """Create a cylinder with holes"""
    print("Example 3: Cylinder with Holes")
    print("-" * 50)
    
    # Create a cylinder with holes
    result = (
        cq.Workplane("XY")
        .circle(20)
        .extrude(30)
        .faces(">Z")
        .workplane()
        .circle(10)
        .cutThruAll()  # Center hole
        .faces(">Z")
        .workplane()
        .pushPoints([(12, 0), (0, 12), (-12, 0), (0, -12)])
        .circle(3)
        .cutThruAll()  # Side holes
    )
    
    # Export
    exporter = CADModelExporter(result, model_name="Cylinder with Holes")
    exporter.save_to_file("example3_cylinder.json")
    
    model_data = exporter.export()
    print(f"Exported: {model_data['modelName']}")
    print(f"  Vertices: {len(model_data['vertexList'])}")
    print(f"  Edges: {len(model_data['edgeList'])}")
    print(f"  Faces: {len(model_data['faceList'])}")
    print(f"  Volume: {model_data['geometricVolume']:.2f} mm³")
    print()


def example4_parametric_gear():
    """Create a simple parametric gear"""
    print("Example 4: Parametric Gear")
    print("-" * 50)
    
    # Parameters
    num_teeth = 12
    outer_radius = 20
    inner_radius = 10
    tooth_depth = 3
    thickness = 5
    
    # Create gear profile
    points = []
    import math
    for i in range(num_teeth * 2):
        angle = 2 * math.pi * i / (num_teeth * 2)
        radius = outer_radius if i % 2 == 0 else outer_radius - tooth_depth
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        points.append((x, y))
    
    # Create gear
    result = (
        cq.Workplane("XY")
        .polyline(points)
        .close()
        .extrude(thickness)
        .faces(">Z")
        .workplane()
        .circle(inner_radius)
        .cutThruAll()  # Center hole
    )
    
    # Export
    exporter = CADModelExporter(result, model_name="Parametric Gear")
    exporter.save_to_file("example4_gear.json")
    
    model_data = exporter.export()
    print(f"Exported: {model_data['modelName']}")
    print(f"  Vertices: {len(model_data['vertexList'])}")
    print(f"  Edges: {len(model_data['edgeList'])}")
    print(f"  Faces: {len(model_data['faceList'])}")
    print(f"  Volume: {model_data['geometricVolume']:.2f} mm³")
    print()


def example5_loft():
    """Create a lofted shape"""
    print("Example 5: Lofted Shape")
    print("-" * 50)
    
    # Create a loft between two shapes
    result = (
        cq.Workplane("XY")
        .rect(20, 20)
        .workplane(offset=20)
        .circle(10)
        .loft()
    )
    
    # Export
    exporter = CADModelExporter(result, model_name="Lofted Shape")
    exporter.save_to_file("example5_loft.json")
    
    model_data = exporter.export()
    print(f"Exported: {model_data['modelName']}")
    print(f"  Vertices: {len(model_data['vertexList'])}")
    print(f"  Edges: {len(model_data['edgeList'])}")
    print(f"  Faces: {len(model_data['faceList'])}")
    print(f"  Volume: {model_data['geometricVolume']:.2f} mm³")
    print()


def example6_upload_to_server():
    """Create a model and upload to server"""
    print("Example 6: Upload to Server")
    print("-" * 50)
    
    # Create a simple part
    result = (
        cq.Workplane("XY")
        .box(15, 15, 15)
        .edges("|Z")
        .fillet(2)
    )
    
    # Try to upload (will fail if server not running)
    try:
        model_data = export_cadquery_model(
            result,
            model_name="Filleted Box",
            output_file="example6_upload.json",
            server_url="http://localhost/api/cadmodel"
        )
        print(f"✓ Uploaded to server!")
        print(f"  Model ID: {model_data.get('id', 'N/A')}")
    except Exception as e:
        print(f"⚠ Could not upload to server: {e}")
        print(f"  (Make sure server is running at http://localhost)")
        # Still save to file
        export_cadquery_model(
            result,
            model_name="Filleted Box",
            output_file="example6_upload.json"
        )
    print()


def example7_complex_assembly():
    """Create a more complex part"""
    print("Example 7: Complex Part")
    print("-" * 50)
    
    # Create a complex part with multiple features
    result = (
        cq.Workplane("XY")
        .box(50, 50, 10)  # Base
        .faces(">Z")
        .workplane()
        .pushPoints([(-15, 15), (15, 15), (-15, -15), (15, -15)])
        .circle(3)
        .cutThruAll()  # Corner holes
        .faces(">Z")
        .workplane()
        .circle(10)
        .extrude(15)  # Center boss
        .faces(">Z")
        .workplane()
        .circle(5)
        .cutThruAll()  # Center hole through everything
        .edges("|Z")
        .fillet(1)  # Fillet edges
    )
    
    # Export
    exporter = CADModelExporter(result, model_name="Complex Part")
    exporter.save_to_file("example7_complex.json")
    
    model_data = exporter.export()
    print(f"Exported: {model_data['modelName']}")
    print(f"  Vertices: {len(model_data['vertexList'])}")
    print(f"  Edges: {len(model_data['edgeList'])}")
    print(f"  Faces: {len(model_data['faceList'])}")
    print(f"  Volume: {model_data['geometricVolume']:.2f} mm³")
    print(f"  Bounding Box: {model_data['boundingBox']}")
    print(f"  Center of Mass: {model_data['centerOfMass']}")
    print()


def run_all_examples():
    """Run all examples"""
    print("╔════════════════════════════════════════════╗")
    print("║  CadQuery to CAD_ModelData Examples       ║")
    print("╚════════════════════════════════════════════╝")
    print()
    
    examples = [
        example1_simple_box,
        example2_bracket,
        example3_cylinder_with_holes,
        example4_parametric_gear,
        example5_loft,
        example6_upload_to_server,
        example7_complex_assembly
    ]
    
    for example in examples:
        try:
            example()
        except Exception as e:
            print(f"Error in {example.__name__}: {e}")
            print()
    
    print("╔════════════════════════════════════════════╗")
    print("║  All examples completed!                   ║")
    print("╚════════════════════════════════════════════╝")
    print()
    print("Generated files:")
    import os
    for f in sorted(os.listdir(".")):
        if f.startswith("example") and f.endswith(".json"):
            size = os.path.getsize(f)
            print(f"  {f:30s} ({size:>7,} bytes)")


if __name__ == "__main__":
    run_all_examples()
