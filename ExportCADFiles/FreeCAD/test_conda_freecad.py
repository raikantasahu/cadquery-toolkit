#!/usr/bin/env python3
"""
Test suite for conda FreeCAD setup and CadQuery exporter

This script verifies that FreeCAD is properly installed and that
the CadQuery to CAD_ModelData exporter works correctly.
"""

import sys
import traceback


def test_freecad_import():
    """
    Test 1: Import freecad module (conda style)
    
    Returns:
        bool: True if successful, False otherwise
    """
    print("\n1. Testing freecad import (conda style)...")
    try:
        import freecad
        print("   ✓ freecad imported successfully!")
        
        # Try to get version
        try:
            if hasattr(freecad, 'app'):
                import freecad.app as FreeCAD
                if hasattr(FreeCAD, 'Version'):
                    print(f"   Version: {'.'.join(FreeCAD.Version()[:3])}")
            else:
                print("   Version: (conda installation - version info not readily available)")
        except:
            print("   Version: (conda installation)")
            
        print(f"   Location: {freecad.__file__}")
        return True
        
    except ImportError as e:
        print(f"   ✗ Failed: {e}")
        print("\n   Solution:")
        print("     conda install -c conda-forge freecad")
        return False


def test_part_module():
    """
    Test 2: Import Part module
    
    Returns:
        bool: True if successful, False otherwise
    """
    print("\n2. Testing Part module...")
    try:
        try:
            # Try conda style first
            import freecad.part as Part
            print("   ✓ Part module works (conda)!")
        except:
            # Try system style
            import Part
            print("   ✓ Part module works (system)!")
        return True
        
    except ImportError as e:
        print(f"   ✗ Failed: {e}")
        return False


def test_cadquery():
    """
    Test 3: Import CadQuery
    
    Returns:
        bool: True if successful, False otherwise
    """
    print("\n3. Testing CadQuery...")
    try:
        import cadquery as cq
        print(f"   ✓ CadQuery works!")
        print(f"   Version: {cq.__version__}")
        return True
        
    except ImportError as e:
        print(f"   ✗ Failed: {e}")
        print("\n   Solution:")
        print("     conda install -c conda-forge cadquery")
        return False


def test_exporter():
    """
    Test 4: Test FreeCAD exporter with a simple box
    
    Returns:
        bool: True if successful, False otherwise
    """
    print("\n4. Testing FreeCAD exporter...")
    try:
        import cadquery as cq
        from cadquery_freecad_exporter import FreeCADExporter
        
        # Create simple box
        box = cq.Workplane("XY").box(5, 5, 5)
        
        # Export
        exporter = FreeCADExporter(box, model_name="Quick Test")
        model_data = exporter.export()
        
        print(f"   ✓ Export successful!")
        print(f"   Vertices: {len(model_data['vertexList'])}")
        print(f"   Faces:    {len(model_data['faceList'])}")
        print(f"   Volume:   {model_data['geometricVolume']:.2f} mm³")
        print(f"   Bounding: {[f'{x:.1f}' for x in model_data['boundingBox']]}")
        return True
        
    except Exception as e:
        print(f"   ✗ Export failed: {e}")
        print("\n   Stack trace:")
        traceback.print_exc()
        
        # Additional diagnostics
        run_diagnostics()
        return False


def run_diagnostics():
    """
    Run diagnostic checks to help troubleshoot export failures
    """
    print("\n   Diagnostic info:")
    try:
        import cadquery as cq
        import tempfile
        import os
        
        box = cq.Workplane("XY").box(5, 5, 5)
        shape = box.val()
        
        # Export to STEP and read back
        with tempfile.NamedTemporaryFile(suffix='.step', delete=False) as tmp:
            step_file = tmp.name
        
        shape.exportStep(step_file)
        
        try:
            import freecad.part as Part
            freecad_shape = Part.read(step_file)
        except:
            import Part
            freecad_shape = Part.read(step_file)
        
        os.remove(step_file)
        
        print(f"   Shape type: {type(freecad_shape)}")
        print(f"   Available attributes:")
        attrs = [a for a in dir(freecad_shape) if not a.startswith('_')]
        for attr in sorted(attrs)[:20]:  # Show first 20
            print(f"     - {attr}")
        print(f"     ... ({len(attrs)} total attributes)")
        
    except Exception as diag_e:
        print(f"   Could not run diagnostics: {diag_e}")


def export_model_to_file(model, model_name, output_file):
    """
    Export a CadQuery model to a JSON file in CAD_ModelData format
    
    Args:
        model: CadQuery Workplane or shape
        model_name: Name for the model
        output_file: Output filename (e.g., "mymodel.json")
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        import cadquery as cq
        box = cq.Workplane("XY").box(10, 10, 10)
        export_model_to_file(box, "My Box", "box.json")
    """
    try:
        from cadquery_freecad_exporter import FreeCADExporter
        
        print(f"\nExporting '{model_name}' to {output_file}...")
        
        # Create exporter
        exporter = FreeCADExporter(model, model_name=model_name)
        
        # Export to file
        exporter.save_to_file(output_file)
        
        # Get model data for summary
        model_data = exporter.export()
        
        print(f"✓ Export successful!")
        print(f"  File:     {output_file}")
        print(f"  Vertices: {len(model_data['vertexList'])}")
        print(f"  Edges:    {len(model_data['edgeList'])}")
        print(f"  Faces:    {len(model_data['faceList'])}")
        print(f"  Volume:   {model_data['geometricVolume']:.2f} mm³")
        
        return True
        
    except Exception as e:
        print(f"✗ Export failed: {e}")
        traceback.print_exc()
        return False


def create_example_models():
    """
    Create several example CadQuery models for testing
    
    Returns:
        dict: Dictionary of {name: model} pairs
    """
    import cadquery as cq
    
    models = {}
    
    # Simple box
    models["box"] = cq.Workplane("XY").box(10, 10, 10)
    
    # Cylinder with hole
    models["cylinder"] = (
        cq.Workplane("XY")
        .circle(15)
        .extrude(30)
        .faces(">Z")
        .workplane()
        .circle(8)
        .cutThruAll()
    )
    
    # Bracket
    models["bracket"] = (
        cq.Workplane("XY")
        .box(40, 40, 5)
        .faces(">Z")
        .workplane()
        .rect(30, 30)
        .cutThruAll()
        .faces(">Z")
        .workplane()
        .pushPoints([(-12, 12), (12, 12), (-12, -12), (12, -12)])
        .circle(2)
        .cutThruAll()
    )
    
    return models


def run_all_tests():
    """
    Run all tests in sequence
    
    Returns:
        bool: True if all tests passed, False otherwise
    """
    print("=" * 60)
    print("Testing conda FreeCAD setup...")
    print("=" * 60)
    
    results = []
    
    # Run each test
    test_functions = [
        ("FreeCAD Import", test_freecad_import),
        ("Part Module", test_part_module),
        ("CadQuery", test_cadquery),
        ("Exporter", test_exporter),
    ]
    
    for name, test_func in test_functions:
        result = test_func()
        results.append((name, result))
        
        # Stop if critical test fails
        if not result and name in ["FreeCAD Import", "CadQuery"]:
            print(f"\n✗ Critical test '{name}' failed. Stopping.")
            break
    
    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {name:20s} {status}")
    
    print()
    
    # Overall result
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("✓ All tests passed!")
        print("\nYou're all set! The exporter is ready to use.")
        print("\nNote: The message about PATH_TO_FREECAD_LIBDIR is normal")
        print("      and can be safely ignored.")
    else:
        print("✗ Some tests failed. Please check the errors above.")
    
    print()
    return all_passed


def demo_export():
    """
    Demonstrate exporting example models to JSON files
    """
    print("=" * 60)
    print("Demo: Exporting Example Models")
    print("=" * 60)
    
    try:
        models = create_example_models()
        
        for name, model in models.items():
            output_file = f"example_{name}.json"
            export_model_to_file(model, name.capitalize(), output_file)
        
        print("\n" + "=" * 60)
        print("✓ All example models exported successfully!")
        print("=" * 60)
        print("\nGenerated files:")
        for name in models.keys():
            print(f"  - example_{name}.json")
        print()
        
    except Exception as e:
        print(f"\n✗ Demo export failed: {e}")
        traceback.print_exc()


def main():
    """
    Main entry point for the test suite
    
    Runs all tests and optionally exports example models
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Test conda FreeCAD setup and CadQuery exporter"
    )
    parser.add_argument(
        '--demo',
        action='store_true',
        help='Run demo export after tests'
    )
    parser.add_argument(
        '--export',
        metavar='FILE',
        help='Export a simple box to the specified file'
    )
    
    args = parser.parse_args()
    
    # Run tests
    success = run_all_tests()
    
    # Run demo if requested and tests passed
    if args.demo and success:
        print()
        demo_export()
    
    # Export simple model if requested
    if args.export and success:
        import cadquery as cq
        print()
        box = cq.Workplane("XY").box(10, 10, 10)
        export_model_to_file(box, "Simple Box", args.export)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
