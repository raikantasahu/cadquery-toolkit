#!/usr/bin/env python3
"""
test_cadquery_export.py - Quick test script for CadQuery exporter

This script verifies that CadQuery is installed correctly and
tests basic export functionality.

Usage:
    python test_cadquery_export.py
"""

import sys
import json

def check_imports():
    """Check if all required modules are available"""
    print("Checking dependencies...")
    print("-" * 50)

    required = {
        'cadquery': 'CadQuery',
        'numpy': 'NumPy',
        'requests': 'Requests'
    }

    missing = []
    for module, name in required.items():
        try:
            __import__(module)
            print(f"✓ {name:20s} installed")
        except ImportError:
            print(f"✗ {name:20s} MISSING")
            missing.append(module)

    if missing:
        print()
        print("Missing dependencies. Install with:")
        if 'cadquery' in missing:
            print("  conda install -c conda-forge cadquery")
        if any(m in missing for m in ['numpy', 'requests']):
            print(f"  pip install {' '.join(m for m in missing if m != 'cadquery')}")
        return False

    print()
    return True


def test_basic_export():
    """Test basic CadQuery export"""
    print("Testing basic export...")
    print("-" * 50)

    try:
        import cadquery as cq
        from cadquery_exporter import CADModelExporter

        # Create a simple box
        print("Creating simple box...")
        box = cq.Workplane("XY").box(10, 10, 10)

        # Export
        print("Exporting to CAD_ModelData format...")
        exporter = CADModelExporter(box, model_name="Test Box")
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
        filename = "test_export.json"
        exporter.save_to_file(filename)
        print(f"  Saved to:   {filename}")

        # Verify JSON is valid
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


def test_server_connection():
    """Test connection to CAD Model Server (if running)"""
    print("Testing server connection...")
    print("-" * 50)

    try:
        import requests

        server_url = "http://localhost/health"
        print(f"Connecting to {server_url}...")

        response = requests.get(server_url, timeout=5)

        if response.status_code == 200:
            print("✓ Server is running!")
            print(f"  Response: {response.json()}")
            return True
        else:
            print(f"✗ Server returned status {response.status_code}")
            return False

    except requests.exceptions.ConnectionError:
        print("⚠ Server not running (this is OK for testing)")
        print("  To start server:")
        print("    cd CADModelServer")
        print("    docker-compose up -d")
        return None
    except Exception as e:
        print(f"⚠ Could not connect: {e}")
        return None


def test_upload():
    """Test upload to server (if available)"""
    print("Testing server upload...")
    print("-" * 50)

    try:
        import cadquery as cq
        import requests
        from cadquery_exporter import CADModelExporter

        # Check if server is running
        try:
            requests.get("http://localhost/health", timeout=2)
        except:
            print("⚠ Server not running, skipping upload test")
            return None

        # Create and upload model
        print("Creating model...")
        box = cq.Workplane("XY").box(15, 15, 15)

        print("Uploading to server...")
        exporter = CADModelExporter(box, model_name="Upload Test")
        response = exporter.upload_to_server("http://localhost/api/cadmodel")

        print("✓ Upload successful!")
        print(f"  Model ID: {response.get('id', 'N/A')}")
        print(f"  Name:     {response.get('modelName', 'N/A')}")

        return True

    except Exception as e:
        print(f"✗ Upload failed: {e}")
        return False


def run_all_tests():
    """Run all tests"""
    print("╔════════════════════════════════════════════╗")
    print("║  CadQuery Exporter - Test Suite            ║")
    print("╚════════════════════════════════════════════╝")
    print()

    results = []

    # Check imports
    if not check_imports():
        print()
        print("Please install missing dependencies first")
        return False

    # Test export
    results.append(("Export", test_basic_export()))
    print()

    # Test server connection
    results.append(("Server", test_server_connection()))
    print()

    # Test upload (only if server available)
    if results[-1][1] is True:
        results.append(("Upload", test_upload()))
        print()

    # Summary
    print("╔════════════════════════════════════════════╗")
    print("║  Test Summary                              ║")
    print("╚════════════════════════════════════════════╝")
    print()

    for name, result in results:
        if result is True:
            status = "✓ PASS"
        elif result is False:
            status = "✗ FAIL"
        else:
            status = "⚠ SKIP"
        print(f"  {name:15s} {status}")

    print()

    # Overall result
    failed = sum(1 for _, r in results if r is False)
    if failed == 0:
        print("✓ All tests passed!")
        return True
    else:
        print(f"✗ {failed} test(s) failed")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
