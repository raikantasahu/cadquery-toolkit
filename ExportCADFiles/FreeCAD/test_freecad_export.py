#!/usr/bin/env python3
"""
test_freecad_export.py - Test script for FreeCAD-based CadQuery exporter

This script verifies that FreeCAD is installed correctly and
tests basic export functionality.

Usage:
    python test_freecad_export.py
"""

import sys

def check_imports():
    """Check if all required modules are available"""
    print("Checking dependencies...")
    print("-" * 50)
    
    required = {
        'cadquery': 'CadQuery',
        'FreeCAD': 'FreeCAD',
        'Part': 'FreeCAD Part module',
        'Mesh': 'FreeCAD Mesh module',
        'numpy': 'NumPy',
        'requests': 'Requests'
    }
    
    missing = []
    for module, name in required.items():
        try:
            __import__(module)
            print(f"✓ {name:25s} installed")
        except ImportError:
            print(f"✗ {name:25s} MISSING")
            missing.append(module)
    
    if missing:
        print()
        print("Missing dependencies. Install with:")
        if 'cadquery' in missing:
            print("  conda install -c conda-forge cadquery")
        if any(m in missing for m in ['FreeCAD', 'Part', 'Mesh']):
            print("  # Install FreeCAD:")
            print("  # Ubuntu: sudo apt install freecad")
            print("  # macOS: brew install --cask freecad")
            print("  # Windows: Download from freecad.org")
        if any(m in missing for m in ['numpy', 'requests']):
            other = [m for m in missing if m in ['numpy', 'requests']]
            print(f"  pip install {' '.join(other)}")
        return False
    
    # Show versions
    try:
        import FreeCAD
        print()
        print(f"FreeCAD version: {'.'.join(FreeCAD.Version()[:3])}")
    except:
        pass
    
    try:
        import cadquery as cq
        print(f"CadQuery version: {cq.__version__}")
    except:
        pass
    
    print()
    return True


def test_basic_export():
    """Test basic FreeCAD export"""
    print("Testing FreeCAD-based export...")
    print("-" * 50)
    
    try:
        import cadquery as cq
        from cadquery_freecad_exporter import FreeCADExporter
        
        # Create a simple box
        print("Creating simple box...")
        box = cq.Workplane("XY").box(10, 10, 10)
        
        # Export
        print("Exporting to CAD_ModelData format...")
        exporter = FreeCADExporter(box, model_name="Test Box")
        model_data = exporter.export()
        
        # Verify data
        print()
        print("Export successful!")
        print(f"  Model name: {model_data['modelName']}")
        print(f"  Vertices:   {len(model_data['vertexList'])}")
        print(f"  Edges:      {len(model_data['edgeList'])}")
        print(f"  Faces:      {len(model_data['faceList'])}")
        print(f"  Volume:     {model_data['geometricVolume']:.2f} mm³")
        print(f"  Bounding:   {model_data['boundingBox']}")
        
        # Save to file
        filename = "test_freecad_export.json"
        exporter.save_to_file(filename)
        print(f"  Saved to:   {filename}")
        
        # Verify JSON is valid
        import json
        with open(filename, 'r') as f:
            loaded = json.load(f)
            assert loaded['modelName'] == "Test Box"
        
        print()
        print("✓ All tests passed!")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_complex_model():
    """Test with a more complex model"""
    print("Testing with complex model...")
    print("-" * 50)
    
    try:
        import cadquery as cq
        from cadquery_freecad_exporter import FreeCADExporter
        
        # Create bracket
        print("Creating bracket with multiple features...")
        bracket = (
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
        
        print("Exporting bracket...")
        exporter = FreeCADExporter(bracket, model_name="Test Bracket")
        model_data = exporter.export()
        
        print()
        print("Complex model export successful!")
        print(f"  Vertices: {len(model_data['vertexList'])}")
        print(f"  Edges:    {len(model_data['edgeList'])}")
        print(f"  Faces:    {len(model_data['faceList'])}")
        print(f"  Volume:   {model_data['geometricVolume']:.2f} mm³")
        
        exporter.save_to_file("test_bracket.json")
        print(f"  Saved to: test_bracket.json")
        
        print()
        print("✓ Complex model test passed!")
        return True
        
    except Exception as e:
        print(f"✗ Complex model test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def compare_with_ocp():
    """Compare FreeCAD approach with OCP direct"""
    print("Comparing FreeCAD vs OCP approaches...")
    print("-" * 50)
    
    import time
    import cadquery as cq
    
    # Create test model
    box = cq.Workplane("XY").box(10, 10, 10)
    
    results = {}
    
    # Test FreeCAD exporter
    try:
        from cadquery_freecad_exporter import FreeCADExporter
        
        start = time.time()
        exporter = FreeCADExporter(box, model_name="Comparison Box")
        model_data = exporter.export()
        elapsed = time.time() - start
        
        results['FreeCAD'] = {
            'success': True,
            'time': elapsed,
            'vertices': len(model_data['vertexList']),
            'error': None
        }
        print(f"✓ FreeCAD: {elapsed:.3f}s - {len(model_data['vertexList'])} vertices")
    except Exception as e:
        results['FreeCAD'] = {
            'success': False,
            'error': str(e)
        }
        print(f"✗ FreeCAD: Failed - {e}")
    
    # Test OCP exporter
    try:
        from cadquery_exporter import CADModelExporter
        
        start = time.time()
        exporter = CADModelExporter(box, model_name="Comparison Box")
        model_data = exporter.export()
        elapsed = time.time() - start
        
        results['OCP'] = {
            'success': True,
            'time': elapsed,
            'vertices': len(model_data['vertexList']),
            'error': None
        }
        print(f"✓ OCP:     {elapsed:.3f}s - {len(model_data['vertexList'])} vertices")
    except Exception as e:
        results['OCP'] = {
            'success': False,
            'error': str(e)
        }
        print(f"✗ OCP:     Failed - {e}")
    
    print()
    
    # Summary
    if results.get('FreeCAD', {}).get('success') and results.get('OCP', {}).get('success'):
        print("Both exporters work!")
        print(f"  FreeCAD: {results['FreeCAD']['time']:.3f}s")
        print(f"  OCP:     {results['OCP']['time']:.3f}s")
        
        if results['FreeCAD']['time'] < results['OCP']['time']:
            print("  → FreeCAD is faster")
        else:
            print("  → OCP is faster")
    elif results.get('FreeCAD', {}).get('success'):
        print("✓ FreeCAD works!")
        print("✗ OCP has issues - FreeCAD is more reliable!")
    elif results.get('OCP', {}).get('success'):
        print("✓ OCP works!")
        print("✗ FreeCAD not available")
    else:
        print("✗ Both exporters have issues")
    
    print()
    return results


def run_all_tests():
    """Run all tests"""
    print("╔════════════════════════════════════════════╗")
    print("║  FreeCAD Exporter - Test Suite            ║")
    print("╚════════════════════════════════════════════╝")
    print()
    
    results = []
    
    # Check imports
    if not check_imports():
        print()
        print("Please install missing dependencies first")
        return False
    
    # Test basic export
    results.append(("Basic Export", test_basic_export()))
    print()
    
    # Test complex model
    results.append(("Complex Model", test_complex_model()))
    print()
    
    # Compare with OCP
    compare_with_ocp()
    
    # Summary
    print("╔════════════════════════════════════════════╗")
    print("║  Test Summary                              ║")
    print("╚════════════════════════════════════════════╝")
    print()
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {name:20s} {status}")
    
    print()
    
    # Overall result
    failed = sum(1 for _, r in results if not r)
    if failed == 0:
        print("✓ All tests passed!")
        return True
    else:
        print(f"✗ {failed} test(s) failed")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
