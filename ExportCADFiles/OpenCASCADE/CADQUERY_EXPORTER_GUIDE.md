# CadQuery to CAD_ModelData Exporter - Complete Guide

## Overview

This exporter converts CadQuery 3D models to the CAD_ModelData JSON format for use with your CAD Model Server. It extracts:
- ✅ Vertices (3D coordinates)
- ✅ Edges (with interpolated curves)
- ✅ Faces (with triangulation)
- ✅ Volumes/Solids
- ✅ Geometric properties (volume, center of mass, bounding box)
- ✅ Moments of inertia

## Installation

### Step 1: Install CadQuery

CadQuery requires conda/mamba (cannot be installed with pip alone):

```bash
# Using conda
conda create -n cadquery python=3.9
conda activate cadquery
conda install -c conda-forge cadquery

# Or using mamba (faster)
mamba create -n cadquery python=3.9
mamba activate cadquery
mamba install -c conda-forge cadquery
```

### Step 2: Install Additional Dependencies

```bash
pip install numpy requests
```

### Step 3: Get the Exporter

```bash
# Copy these files to your project:
# - cadquery_exporter.py
# - cadquery_examples.py (optional)
```

## Quick Start

### Basic Usage

```python
import cadquery as cq
from cadquery_exporter import CADModelExporter

# Create a CadQuery model
result = cq.Workplane("XY").box(10, 10, 10)

# Export to CAD_ModelData
exporter = CADModelExporter(result, model_name="My Box")

# Save to JSON file
exporter.save_to_file("mybox.json")

# Get model data as dictionary
model_data = exporter.export()

# Print summary
print(f"Vertices: {len(model_data['vertexList'])}")
print(f"Faces: {len(model_data['faceList'])}")
print(f"Volume: {model_data['geometricVolume']:.2f} mm³")
```

### Upload to Server

```python
# Upload directly to your CAD Model Server
exporter.upload_to_server("http://localhost/api/cadmodel")

# Or use the convenience function
from cadquery_exporter import export_cadquery_model

model_data = export_cadquery_model(
    result,
    model_name="My Box",
    output_file="mybox.json",
    server_url="http://localhost/api/cadmodel"
)
```

## Detailed Examples

### Example 1: Simple Box

```python
import cadquery as cq
from cadquery_exporter import CADModelExporter

# Create a 20x20x10 box
box = cq.Workplane("XY").box(20, 20, 10)

# Export
exporter = CADModelExporter(box, model_name="Simple Box")
exporter.save_to_file("box.json")
```

### Example 2: Cylinder with Holes

```python
# Create a cylinder with a center hole and 4 mounting holes
cylinder = (
    cq.Workplane("XY")
    .circle(30)                    # Outer cylinder
    .extrude(40)
    .faces(">Z")
    .workplane()
    .circle(15)                    # Center hole
    .cutThruAll()
    .faces(">Z")
    .workplane()
    .pushPoints([               # 4 mounting holes
        (20, 0), (0, 20), 
        (-20, 0), (0, -20)
    ])
    .circle(4)
    .cutThruAll()
)

exporter = CADModelExporter(cylinder, model_name="Mounting Cylinder")
exporter.save_to_file("cylinder.json")
```

### Example 3: Bracket with Fillets

```python
# Create a mounting bracket
bracket = (
    cq.Workplane("XY")
    .box(50, 50, 5)               # Base plate
    .faces(">Z")
    .workplane()
    .rect(40, 40)
    .cutThruAll()                 # Center cutout
    .faces(">Y")
    .workplane()
    .move(0, 2.5)
    .rect(15, 5)
    .extrude(25)                  # Mounting tab
    .edges("|Z")
    .fillet(2)                    # Fillet edges
)

exporter = CADModelExporter(bracket, model_name="Mounting Bracket")
exporter.save_to_file("bracket.json")
```

### Example 4: Parametric Gear

```python
import math

# Gear parameters
num_teeth = 16
outer_radius = 25
inner_radius = 12
tooth_depth = 3
thickness = 6

# Generate gear profile points
points = []
for i in range(num_teeth * 2):
    angle = 2 * math.pi * i / (num_teeth * 2)
    radius = outer_radius if i % 2 == 0 else outer_radius - tooth_depth
    x = radius * math.cos(angle)
    y = radius * math.sin(angle)
    points.append((x, y))

# Create gear
gear = (
    cq.Workplane("XY")
    .polyline(points)
    .close()
    .extrude(thickness)
    .faces(">Z")
    .workplane()
    .circle(inner_radius)
    .cutThruAll()                 # Center hole
)

exporter = CADModelExporter(gear, model_name="Parametric Gear")
exporter.save_to_file("gear.json")
```

### Example 5: Lofted Shape

```python
# Create a loft between two profiles
loft = (
    cq.Workplane("XY")
    .rect(30, 30)                 # Bottom profile
    .workplane(offset=40)
    .circle(15)                   # Top profile
    .loft()
)

exporter = CADModelExporter(loft, model_name="Lofted Part")
exporter.save_to_file("loft.json")
```

## Advanced Usage

### Custom Units

```python
exporter = CADModelExporter(
    result,
    model_name="Metric Part",
    length_unit="mm",
    mass_unit="kg",
    angle_unit="degrees"
)
```

### Extract Specific Data

```python
model_data = exporter.export()

# Access vertices
for vertex in model_data['vertexList']:
    print(f"Vertex {vertex['persistentID']}: {vertex['location']}")

# Access geometric properties
print(f"Volume: {model_data['geometricVolume']}")
print(f"Center of Mass: {model_data['centerOfMass']}")
print(f"Bounding Box: {model_data['boundingBox']}")

# Access faces
for face in model_data['faceList']:
    print(f"Face {face['persistentID']}: Area = {face['area']:.2f}")
```

### Batch Export

```python
# Create multiple models
models = {
    "box": cq.Workplane("XY").box(10, 10, 10),
    "cylinder": cq.Workplane("XY").circle(5).extrude(20),
    "sphere": cq.Workplane("XY").sphere(8)
}

# Export all
for name, model in models.items():
    exporter = CADModelExporter(model, model_name=name)
    exporter.save_to_file(f"{name}.json")
    print(f"Exported {name}")
```

### Integration with Server

```python
import requests
from cadquery_exporter import CADModelExporter

# Create model
result = cq.Workplane("XY").box(10, 10, 10)
exporter = CADModelExporter(result, model_name="Test Part")

# Upload to server
try:
    response = exporter.upload_to_server("http://localhost/api/cadmodel")
    print(f"Uploaded! Model ID: {response['id']}")
    
    # Download it back
    model_id = response['id']
    download_response = requests.get(
        f"http://localhost/api/cadmodel/{model_id}/download"
    )
    
    with open("downloaded.json", "wb") as f:
        f.write(download_response.content)
    
    print("Downloaded model back from server")
    
except Exception as e:
    print(f"Server error: {e}")
```

## What Gets Exported

### Geometry

```python
model_data = {
    # Vertices - 3D coordinates
    "vertexList": [
        {"persistentID": "V0", "location": [0, 0, 0]},
        {"persistentID": "V1", "location": [10, 0, 0]},
        ...
    ],
    
    # Edges - connections with interpolated curves
    "edgeList": [
        {
            "persistentID": "E0",
            "start": 0,  # Vertex index
            "end": 1,    # Vertex index
            "vertexLocations": [0,0,0, 10,0,0, ...]  # Curve points
        },
        ...
    ],
    
    # Faces - triangulated surfaces
    "faceList": [
        {
            "persistentID": "F0",
            "area": 100.0,
            "edgeList": [0, 1, 2, 3],
            "vertexLocations": [...],  # Triangle vertices
            "connectivity": [0,1,2, 3,4,5, ...]  # Triangle indices
        },
        ...
    ],
    
    # Volumes/Solids
    "volumeList": [
        {"persistentID": "S0", "faceList": [0,1,2,3,4,5]}
    ],
    
    # Bodies (collection of volumes)
    "bodyList": [
        {"persistentID": "B0", "volumeList": [0]}
    ]
}
```

### Properties

```python
model_data = {
    "geometricVolume": 1000.0,           # Volume in mm³
    "centerOfMass": [5.0, 5.0, 5.0],     # Center of mass
    "boundingBox": [0,0,0, 10,10,10],    # [xmin,ymin,zmin, xmax,ymax,zmax]
    "volumeMomentsOfInertia": [...],     # Inertia tensor
    "lengthUnit": "mm",
    "massUnit": "kg",
    "angleUnit": "degrees"
}
```

## Running Examples

```bash
# Activate conda environment
conda activate cadquery

# Run all examples
python cadquery_examples.py

# This creates:
# - example1_box.json
# - example2_bracket.json
# - example3_cylinder.json
# - example4_gear.json
# - example5_loft.json
# - example6_upload.json
# - example7_complex.json
```

## Workflow Integration

### 1. Design → Export → Upload

```python
# Design in CadQuery
part = (
    cq.Workplane("XY")
    .box(50, 30, 10)
    .faces(">Z")
    .workplane()
    .circle(5)
    .cutThruAll()
)

# Export and upload
from cadquery_exporter import export_cadquery_model

export_cadquery_model(
    part,
    model_name="My Part",
    output_file="part.json",
    server_url="http://localhost/api/cadmodel"
)
```

### 2. Parametric Design Script

```python
def create_bracket(width, height, thickness, hole_diameter):
    """Parametric bracket generator"""
    return (
        cq.Workplane("XY")
        .box(width, height, thickness)
        .faces(">Z")
        .workplane()
        .circle(hole_diameter / 2)
        .cutThruAll()
    )

# Generate variants
for i, (w, h) in enumerate([(40, 30), (50, 40), (60, 50)]):
    bracket = create_bracket(w, h, 5, 6)
    
    exporter = CADModelExporter(bracket, model_name=f"Bracket_{w}x{h}")
    exporter.save_to_file(f"bracket_{i}.json")
```

### 3. Automated Export Pipeline

```python
import os
from pathlib import Path

def export_all_in_directory(output_dir="exports"):
    """Export all CadQuery models to a directory"""
    
    # Create output directory
    Path(output_dir).mkdir(exist_ok=True)
    
    # Define models
    models = {
        "box": cq.Workplane("XY").box(10, 10, 10),
        "cylinder": cq.Workplane("XY").circle(5).extrude(20),
        "cone": cq.Workplane("XY").circle(10).workplane(20).circle(2).loft()
    }
    
    # Export all
    for name, model in models.items():
        filepath = os.path.join(output_dir, f"{name}.json")
        exporter = CADModelExporter(model, model_name=name)
        exporter.save_to_file(filepath)
        print(f"✓ {filepath}")

export_all_in_directory()
```

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'cadquery'"

**Solution:** CadQuery must be installed via conda/mamba:
```bash
conda install -c conda-forge cadquery
```

### Issue: "ImportError: DLL load failed"

**Solution:** Make sure you're in the conda environment:
```bash
conda activate cadquery
```

### Issue: Empty or missing geometry

**Solution:** Check that your CadQuery model has actual geometry:
```python
# Debug your model
result = cq.Workplane("XY").box(10, 10, 10)
print(f"Vertices: {len(result.vertices().vals())}")
print(f"Faces: {len(result.faces().vals())}")
```

### Issue: "Server connection refused"

**Solution:** Make sure your CAD Model Server is running:
```bash
cd CADModelServer
docker-compose up -d
curl http://localhost/health
```

### Issue: Large file sizes

**Solution:** CadQuery models can generate detailed triangulation. Adjust mesh parameters:
```python
# In cadquery_exporter.py, modify _triangulate_face:
BRepMesh_IncrementalMesh(face, 0.5, False, 0.5, True)  # Coarser mesh
```

## Performance Tips

### For Large Models

```python
# Use coarser triangulation for large models
# Modify the exporter's _triangulate_face method
# to use larger tolerance values

# Export only what you need
model_data = exporter.export()

# Remove unnecessary data
del model_data['vertexLocations']  # If you don't need triangulation
```

### For Batch Processing

```python
import concurrent.futures

def export_model(name, model):
    exporter = CADModelExporter(model, model_name=name)
    exporter.save_to_file(f"{name}.json")
    return name

# Parallel export
with concurrent.futures.ThreadPoolExecutor() as executor:
    futures = {
        executor.submit(export_model, name, model): name
        for name, model in models.items()
    }
    
    for future in concurrent.futures.as_completed(futures):
        print(f"Exported {future.result()}")
```

## API Reference

### CADModelExporter

```python
class CADModelExporter:
    def __init__(self, cadquery_object, model_name, cad_name="CadQuery",
                 length_unit="mm", mass_unit="kg", angle_unit="degrees")
    
    def export() -> Dict[str, Any]
    def to_json(indent=2) -> str
    def save_to_file(filename, indent=2) -> None
    def upload_to_server(server_url, use_multipart=False) -> Dict[str, Any]
```

### Convenience Function

```python
def export_cadquery_model(cq_object, model_name, output_file=None, 
                         server_url=None) -> Dict[str, Any]
```

## Summary

**This exporter provides:**
- ✅ Complete geometry extraction (vertices, edges, faces, volumes)
- ✅ Geometric properties (volume, mass, inertia)
- ✅ Direct server upload capability
- ✅ JSON file export
- ✅ Support for complex CadQuery models
- ✅ Parametric design integration

**Perfect for:**
- Converting CadQuery designs to your CAD Model Server format
- Automated CAD model generation and archiving
- Integration with web-based CAD viewers
- Parametric design workflows
