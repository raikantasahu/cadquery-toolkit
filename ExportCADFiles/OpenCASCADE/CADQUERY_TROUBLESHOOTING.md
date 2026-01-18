# CadQuery Exporter - Troubleshooting Guide

## Common Issues and Solutions

### Issue 1: TopExp_Explorer Constructor Error

**Error:**
```
__init__(): incompatible constructor arguments. The following argument types are supported:
    1. OCP.OCP.TopExp.TopExp_Explorer()
    2. OCP.OCP.TopExp.TopExp_Explorer(S: OCP.OCP.TopoDS.TopoDS_Shape, ToFind: OCP.OCP.TopAbs.TopAbs_ShapeEnum, ...)
```

**Cause:** Incorrect initialization of TopExp_Explorer with OCP enum types.

**Solution:** Use the two-step initialization pattern:

```python
# ❌ WRONG - Old API
from OCP.TopAbs import TopAbs_VERTEX
explorer = TopExp_Explorer(shape, TopAbs_VERTEX)

# ✅ CORRECT - New API
from OCP.TopAbs import TopAbs_ShapeEnum
explorer = TopExp_Explorer()
explorer.Init(shape, TopAbs_ShapeEnum.TopAbs_VERTEX)
```

**Fixed in Version:** The provided `cadquery_exporter.py` has been updated with the correct pattern.

---

### Issue 2: Import Errors with OCP

**Error:**
```
ImportError: cannot import name 'TopAbs_VERTEX' from 'OCP.TopAbs'
```

**Cause:** Changed enum structure in newer OCP versions.

**Solution:** Always use `TopAbs_ShapeEnum`:

```python
# ✅ CORRECT
from OCP.TopAbs import TopAbs_ShapeEnum

# Use it like this:
TopAbs_ShapeEnum.TopAbs_VERTEX
TopAbs_ShapeEnum.TopAbs_EDGE
TopAbs_ShapeEnum.TopAbs_FACE
TopAbs_ShapeEnum.TopAbs_SOLID
```

---

### Issue 3: CadQuery Not Found

**Error:**
```
ModuleNotFoundError: No module named 'cadquery'
```

**Solution:** CadQuery must be installed via conda:

```bash
# Create environment
conda create -n cadquery python=3.9
conda activate cadquery

# Install CadQuery
conda install -c conda-forge cadquery

# Verify installation
python -c "import cadquery as cq; print(cq.__version__)"
```

**Note:** `pip install cadquery` will NOT work! Must use conda.

---

### Issue 4: Shape Has No Geometry

**Error:**
```
Export successful but vertices/faces are empty
```

**Cause:** CadQuery object wasn't properly converted to a shape.

**Solution:** Ensure you're getting the actual shape:

```python
# ✅ CORRECT
result = cq.Workplane("XY").box(10, 10, 10)
exporter = CADModelExporter(result)  # result.val() called internally

# Also works:
shape = result.val()
exporter = CADModelExporter(shape)

# For assemblies:
compound = result.toCompound()
exporter = CADModelExporter(compound)
```

---

### Issue 5: Triangulation Errors

**Error:**
```
Error in _triangulate_face: ...
```

**Cause:** Face cannot be triangulated or has invalid geometry.

**Solution:** The exporter includes error handling, but you can adjust mesh tolerance:

```python
# In cadquery_exporter.py, modify _triangulate_face:

# Coarser mesh (faster, less accurate)
BRepMesh_IncrementalMesh(face, 1.0, False, 1.0, True)

# Finer mesh (slower, more accurate)
BRepMesh_IncrementalMesh(face, 0.01, False, 0.01, True)

# Default (balanced)
BRepMesh_IncrementalMesh(face, 0.1, False, 0.1, True)
```

---

### Issue 6: GCPnts_UniformAbscissa Errors

**Error:**
```
Error sampling edge curve
```

**Cause:** Some curves cannot be uniformly sampled.

**Solution:** The exporter catches this and falls back to endpoints:

```python
try:
    sampler = GCPnts_UniformAbscissa(curve_adaptor, num_points)
    # ... sample points
except:
    # Fallback: use start and end points only
    vertex_locations = [start_x, start_y, start_z, end_x, end_y, end_z]
```

**This is already handled** in the provided exporter.

---

### Issue 7: Version Compatibility

**Problem:** Different CadQuery/OCP versions have different APIs.

**Solution:** Check your versions:

```bash
# Check versions
python -c "import cadquery; print('CadQuery:', cadquery.__version__)"
python -c "import OCP; print('OCP:', OCP.__version__)"
```

**Recommended versions:**
- CadQuery: 2.4.0 or newer
- Python: 3.9 - 3.11
- OCP: Latest from conda-forge

**Update if needed:**
```bash
conda update -c conda-forge cadquery
```

---

### Issue 8: Memory Issues with Large Models

**Problem:** Large models cause memory errors or slow exports.

**Solution 1:** Reduce mesh density:
```python
# In _triangulate_face, use coarser mesh
BRepMesh_IncrementalMesh(face, 0.5, False, 0.5, True)
```

**Solution 2:** Export only what you need:
```python
# Skip triangulation if you don't need it
model_data = exporter.export()
del model_data['faceList']  # Remove face triangulation
```

**Solution 3:** Process in batches:
```python
# For assemblies, export components separately
for component in assembly.components:
    exporter = CADModelExporter(component)
    exporter.save_to_file(f"{component.name}.json")
```

---

### Issue 9: Server Upload Fails

**Error:**
```
requests.exceptions.ConnectionError: ...
```

**Solution:** Ensure server is running:

```bash
# Check server health
curl http://localhost/health

# If not running:
cd CADModelServer
docker-compose up -d

# Check logs
docker-compose logs -f api
```

**Test connection:**
```python
import requests
response = requests.get("http://localhost/health")
print(response.json())
```

---

### Issue 10: JSON Serialization Errors

**Error:**
```
TypeError: Object of type 'float32' is not JSON serializable
```

**Cause:** NumPy types in the data.

**Solution:** Already handled in the exporter, but if you modify it:

```python
import json
import numpy as np

# Custom encoder
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

# Use it
json.dumps(model_data, cls=NumpyEncoder)
```

---

## Debugging Tips

### Enable Verbose Output

Add debug prints to the exporter:

```python
def _extract_vertices(self):
    print(f"Extracting vertices from {type(self.shape)}")
    # ... rest of code
    print(f"Found {len(self.vertices_list)} vertices")
```

### Inspect Your CadQuery Model

Before exporting:

```python
import cadquery as cq

result = cq.Workplane("XY").box(10, 10, 10)

# Check what you have
print(f"Type: {type(result)}")
print(f"Shape: {type(result.val())}")
print(f"Vertices: {len(result.vertices().vals())}")
print(f"Edges: {len(result.edges().vals())}")
print(f"Faces: {len(result.faces().vals())}")
print(f"Solids: {len(result.solids().vals())}")
```

### Test Minimal Example

Start with the simplest possible model:

```python
import cadquery as cq
from cadquery_exporter import CADModelExporter

# Simplest possible model
box = cq.Workplane("XY").box(1, 1, 1)

# Try export
try:
    exporter = CADModelExporter(box, model_name="Test")
    model_data = exporter.export()
    print("✓ Export successful!")
    print(f"  Vertices: {len(model_data['vertexList'])}")
except Exception as e:
    print(f"✗ Export failed: {e}")
    import traceback
    traceback.print_exc()
```

### Verify JSON Output

Check the generated JSON is valid:

```python
import json

# Read back the file
with open("output.json", 'r') as f:
    data = json.load(f)

print(f"Model: {data['modelName']}")
print(f"Vertices: {len(data['vertexList'])}")
print(f"Volume: {data['geometricVolume']}")
```

---

## Getting Help

### Check the Test Script

Run the test script to verify installation:

```bash
python test_cadquery_export.py
```

### Check CadQuery Documentation

- CadQuery Docs: https://cadquery.readthedocs.io/
- CadQuery Examples: https://github.com/CadQuery/cadquery/tree/master/examples

### Common Patterns

**Working with Assemblies:**
```python
# For assemblies, iterate components
for name, component in assembly.traverse():
    if component.shape:
        exporter = CADModelExporter(component.shape, model_name=name)
        exporter.save_to_file(f"{name}.json")
```

**Custom Properties:**
```python
# Add custom parameters to the model
model_data = exporter.export()
model_data['parameterList'].append({
    "type": "PARAMETER_STRING",
    "name": "Material",
    "value": "Aluminum"
})
```

---

## Version-Specific Notes

### CadQuery 2.4.0+
- Uses updated OCP bindings
- TopExp_Explorer requires Init() pattern
- Some enum paths changed

### CadQuery 2.3.x and earlier
- May use older OCP API
- Direct TopExp_Explorer(shape, enum) might work
- Consider upgrading to 2.4.0+

---

## Summary

**Most common issues:**
1. ✅ **TopExp_Explorer** - Use `explorer.Init()` pattern
2. ✅ **Import errors** - Use `TopAbs_ShapeEnum.TopAbs_VERTEX`
3. ✅ **CadQuery not found** - Install via conda only
4. ✅ **Server connection** - Ensure server is running

**The updated exporter handles all these issues!**

Run `python test_cadquery_export.py` to verify everything works.
