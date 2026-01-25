# FreeCAD-Based CadQuery Exporter - Complete Guide

## Why Use FreeCAD Instead of OCP?

### Advantages of FreeCAD Approach ✅

1. **Stable API** - FreeCAD's Python API is well-documented and stable
2. **Easier Installation** - Standard package managers (apt, brew, etc.)
3. **No OCP Version Issues** - Avoids enum/import problems
4. **Better Documentation** - Extensive FreeCAD Python documentation
5. **More Features** - Access to FreeCAD's full geometry toolset
6. **Proven** - Widely used in production environments

### Comparison

| Feature | OCP Direct | FreeCAD |
|---------|-----------|---------|
| **Stability** | ⚠️ API changes | ✅ Very stable |
| **Installation** | ⚠️ Conda only | ✅ Multiple methods |
| **Documentation** | ⚠️ Limited | ✅ Extensive |
| **Type Issues** | ❌ Enum problems | ✅ No issues |
| **Learning Curve** | ❌ Steep | ✅ Moderate |

## Installation

### Step 1: Install FreeCAD

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install freecad
```

#### macOS
```bash
brew install --cask freecad
```

#### Windows
Download installer from: https://www.freecad.org/downloads.php

#### Or via Conda (alternative)
```bash
conda install -c conda-forge freecad
```

### Step 2: Install CadQuery
```bash
conda create -n cadquery python=3.9
conda activate cadquery
conda install -c conda-forge cadquery
```

### Step 3: Install Additional Dependencies
```bash
pip install numpy requests
```

### Step 4: Verify Installation

```bash
python3 -c "import FreeCAD; print('FreeCAD:', FreeCAD.Version())"
python3 -c "import cadquery as cq; print('CadQuery:', cq.__version__)"
```

**Expected output:**
```
FreeCAD: ['0', '21', '2', ...]
CadQuery: 2.4.0
```

## Quick Start

### Basic Usage

```python
import cadquery as cq
from cadquery_freecad_exporter import FreeCADExporter

# Create a CadQuery model
box = cq.Workplane("XY").box(10, 10, 10)

# Export to CAD_ModelData
exporter = FreeCADExporter(box, model_name="My Box")
exporter.save_to_file("mybox.json")

# Get model data
model_data = exporter.export()
print(f"Vertices: {len(model_data['vertexList'])}")
print(f"Volume: {model_data['geometricVolume']}")
```

### Upload to Server

```python
# Upload directly to your CAD Model Server
exporter.upload_to_server("http://localhost/api/cadmodel")

# Or use convenience function
from cadquery_freecad_exporter import export_cadquery_model

model_data = export_cadquery_model(
    box,
    model_name="My Box",
    output_file="box.json",
    server_url="http://localhost/api/cadmodel"
)
```

## Examples

### Example 1: Simple Box

```python
import cadquery as cq
from cadquery_freecad_exporter import FreeCADExporter

# Create box
box = cq.Workplane("XY").box(20, 20, 10)

# Export
exporter = FreeCADExporter(box, model_name="Simple Box")
exporter.save_to_file("box.json")

print("✓ Exported!")
```

### Example 2: Cylinder with Holes

```python
import cadquery as cq
from cadquery_freecad_exporter import FreeCADExporter

# Create cylinder with holes
cylinder = (
    cq.Workplane("XY")
    .circle(30)
    .extrude(40)
    .faces(">Z")
    .workplane()
    .circle(15)
    .cutThruAll()
    .faces(">Z")
    .workplane()
    .pushPoints([(20, 0), (0, 20), (-20, 0), (0, -20)])
    .circle(4)
    .cutThruAll()
)

exporter = FreeCADExporter(cylinder, model_name="Cylinder")
exporter.save_to_file("cylinder.json")
```

### Example 3: Complex Bracket

```python
import cadquery as cq
from cadquery_freecad_exporter import FreeCADExporter

# Create bracket
bracket = (
    cq.Workplane("XY")
    .box(50, 50, 5)
    .faces(">Z")
    .workplane()
    .rect(40, 40)
    .cutThruAll()
    .faces(">Y")
    .workplane()
    .move(0, 2.5)
    .rect(15, 5)
    .extrude(25)
    .edges("|Z")
    .fillet(2)
)

exporter = FreeCADExporter(bracket, model_name="Bracket")
model_data = exporter.export()

print(f"Bracket Properties:")
print(f"  Volume: {model_data['geometricVolume']:.2f} mm³")
print(f"  Bounding Box: {model_data['boundingBox']}")
print(f"  Center of Mass: {model_data['centerOfMass']}")

exporter.save_to_file("bracket.json")
```

### Example 4: Parametric Part

```python
import cadquery as cq
from cadquery_freecad_exporter import FreeCADExporter

def create_gear(num_teeth=12, outer_radius=25, inner_radius=12, 
                tooth_depth=3, thickness=6):
    """Create parametric gear"""
    import math
    
    points = []
    for i in range(num_teeth * 2):
        angle = 2 * math.pi * i / (num_teeth * 2)
        radius = outer_radius if i % 2 == 0 else outer_radius - tooth_depth
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        points.append((x, y))
    
    gear = (
        cq.Workplane("XY")
        .polyline(points)
        .close()
        .extrude(thickness)
        .faces(">Z")
        .workplane()
        .circle(inner_radius)
        .cutThruAll()
    )
    
    return gear

# Create different sized gears
for teeth, radius in [(12, 25), (16, 30), (20, 35)]:
    gear = create_gear(num_teeth=teeth, outer_radius=radius)
    exporter = FreeCADExporter(gear, model_name=f"Gear_{teeth}T")
    exporter.save_to_file(f"gear_{teeth}.json")
    print(f"✓ Created gear with {teeth} teeth")
```

### Example 5: Batch Export

```python
import cadquery as cq
from cadquery_freecad_exporter import FreeCADExporter

# Create multiple models
models = {
    "box": cq.Workplane("XY").box(10, 10, 10),
    "cylinder": cq.Workplane("XY").circle(5).extrude(20),
    "sphere": cq.Workplane("XY").sphere(8),
    "cone": cq.Workplane("XY").circle(10).workplane(20).circle(2).loft()
}

# Export all
for name, model in models.items():
    exporter = FreeCADExporter(model, model_name=name)
    exporter.save_to_file(f"{name}.json")
    print(f"✓ Exported {name}")
```

## How It Works

### Internal Process

```
┌─────────────────┐
│ CadQuery Model  │
└────────┬────────┘
         │
         │ Export to STEP (temporary file)
         ▼
┌─────────────────┐
│ STEP File       │
└────────┬────────┘
         │
         │ Import into FreeCAD
         ▼
┌─────────────────┐
│ FreeCAD Shape   │
└────────┬────────┘
         │
         │ Extract geometry using FreeCAD API
         ▼
┌─────────────────┐
│ CAD_ModelData   │
└─────────────────┘
```

### Key Steps

1. **Export to STEP** - CadQuery has built-in STEP export
2. **Import to FreeCAD** - FreeCAD reads STEP file
3. **Extract Geometry** - Use FreeCAD's stable API
   - Vertices: `shape.Vertexes`
   - Edges: `shape.Edges`
   - Faces: `shape.Faces`
   - Solids: `shape.Solids`
4. **Calculate Properties** - FreeCAD provides:
   - Volume: `shape.Volume`
   - Center of Mass: `shape.CenterOfMass`
   - Bounding Box: `shape.BoundBox`
   - Inertia: `shape.MatrixOfInertia`
5. **Triangulation** - `face.tessellate()`
6. **Export JSON** - Convert to CAD_ModelData format

## Advantages Over OCP Direct

### No Type Issues

```python
# FreeCAD - Simple and clear
for vertex in shape.Vertexes:
    point = vertex.Point
    x, y, z = point.x, point.y, point.z

# OCP Direct - Complex enum issues
from OCP.TopAbs import TopAbs_ShapeEnum  # Which enum?
explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_VERTEX)  # Confusing!
```

### Better Documentation

```python
# FreeCAD - Well documented
# https://wiki.freecad.org/Part_API
shape.Volume              # Volume of the shape
shape.CenterOfMass        # Center of mass
shape.BoundBox            # Bounding box
shape.Faces               # All faces
face.Area                 # Face area
face.tessellate(0.1)      # Triangulate face

# All clearly documented with examples!
```

### Easier Geometry Access

```python
# FreeCAD - Intuitive
for edge in shape.Edges:
    start = edge.firstVertex()
    end = edge.lastVertex()
    length = edge.Length
    curve = edge.Curve

# OCP Direct - Requires deep knowledge of OCP internals
```

## Performance Comparison

| Operation | OCP Direct | FreeCAD |
|-----------|-----------|---------|
| **Setup Time** | Fast | Slower (STEP export/import) |
| **Extraction** | Fast | Fast |
| **Memory** | Low | Moderate (temporary STEP file) |
| **Reliability** | ⚠️ Version dependent | ✅ Very reliable |

**Verdict:** FreeCAD is slightly slower due to STEP file I/O, but **much more reliable**.

## Troubleshooting

### Issue: "FreeCAD not found"

**Solution:** Make sure FreeCAD is installed and Python can find it:

```bash
# Check FreeCAD installation
which freecad  # Linux/macOS
where freecad  # Windows

# Test import
python3 -c "import FreeCAD; print(FreeCAD.Version())"
```

If FreeCAD is installed but Python can't import it:

```bash
# Find FreeCAD's Python path
find /usr -name "FreeCAD.so" 2>/dev/null

# Add to PYTHONPATH (example for Ubuntu)
export PYTHONPATH="/usr/lib/freecad/lib:$PYTHONPATH"
```

### Issue: "STEP export failed"

**Solution:** Ensure CadQuery object has valid geometry:

```python
# Check your model
result = cq.Workplane("XY").box(10, 10, 10)
print(f"Has shape: {hasattr(result, 'val')}")
print(f"Vertices: {len(result.vertices().vals())}")
```

### Issue: "Temporary file permission error"

**Solution:** Ensure write permissions in temp directory:

```python
import tempfile
print(f"Temp dir: {tempfile.gettempdir()}")

# Or specify custom temp dir
import os
os.environ['TMPDIR'] = '/path/to/writable/dir'
```

### Issue: "Triangulation failed"

**Solution:** Adjust tessellation tolerance:

```python
# In cadquery_freecad_exporter.py, modify _triangulate_face:
mesh_data = face.tessellate(0.5)  # Coarser (faster)
mesh_data = face.tessellate(0.01)  # Finer (slower, more accurate)
```

## Comparison with OCP Exporter

### When to Use FreeCAD Exporter

✅ **Use FreeCAD when:**
- You want stable, reliable exports
- You're new to CadQuery/OCP
- You need good documentation
- You encounter OCP version issues
- You're on Linux/macOS (easy install)

### When to Use OCP Direct

✅ **Use OCP direct when:**
- Maximum performance is critical
- You're already familiar with OCP
- You need to avoid temporary files
- You're in a restricted environment (no FreeCAD)

## Integration with Workflow

### Development Workflow

```python
# During development - use FreeCAD (reliable)
from cadquery_freecad_exporter import FreeCADExporter

result = cq.Workplane("XY").box(10, 10, 10)
exporter = FreeCADExporter(result, model_name="Test")
exporter.save_to_file("test.json")
```

### Production Pipeline

```python
# In production - batch export
import os
from pathlib import Path

def export_all_models(output_dir="exports"):
    Path(output_dir).mkdir(exist_ok=True)
    
    models = {
        "part1": create_part1(),
        "part2": create_part2(),
        "assembly": create_assembly()
    }
    
    for name, model in models.items():
        exporter = FreeCADExporter(model, model_name=name)
        filepath = os.path.join(output_dir, f"{name}.json")
        exporter.save_to_file(filepath)
        print(f"✓ {filepath}")

export_all_models()
```

## API Reference

### FreeCADExporter Class

```python
class FreeCADExporter:
    def __init__(self, cadquery_object, model_name="CadQuery Model",
                 cad_name="CadQuery", length_unit="mm", 
                 mass_unit="kg", angle_unit="degrees")
    
    def export() -> Dict[str, Any]
    def to_json(indent=2) -> str
    def save_to_file(filename, indent=2) -> None
    def upload_to_server(server_url, use_multipart=False) -> Dict[str, Any]
```

### Convenience Function

```python
def export_cadquery_model(cq_object, model_name="CadQuery Model",
                         output_file=None, server_url=None) -> Dict[str, Any]
```

## Summary

**FreeCAD-based exporter provides:**

✅ **Stable API** - No OCP version issues  
✅ **Easy Installation** - Standard package managers  
✅ **Great Documentation** - FreeCAD wiki  
✅ **Reliable Exports** - Production-tested  
✅ **Simple Code** - Intuitive API  

**Perfect for:**
- Production environments
- Teams new to CadQuery
- Reliable, maintainable code
- Long-term projects

The FreeCAD approach trades a small performance cost for **significantly better reliability and ease of use**! 🎯
