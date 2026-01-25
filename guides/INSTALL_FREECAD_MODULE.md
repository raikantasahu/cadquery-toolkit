# Installing FreeCAD Python Module

## The Goal

You need Python to be able to `import FreeCAD` so the exporter can work.

## Best Method: Conda (Recommended) ✅

This is the **easiest and most reliable** way to get FreeCAD working in Python:

```bash
# Create new environment (or use existing cadquery environment)
conda create -n cadquery python=3.9
conda activate cadquery

# Install both CadQuery and FreeCAD via conda
conda install -c conda-forge cadquery freecad

# Verify it works
python -c "import FreeCAD; print('FreeCAD version:', FreeCAD.Version())"
python -c "import cadquery; print('CadQuery version:', cadquery.__version__)"
```

**Expected output:**
```
FreeCAD version: ['0', '21', '2', ...]
CadQuery version: 2.4.0
```

**This is the recommended approach!** Everything is managed by conda and just works.

---

## Alternative Methods (If Conda Doesn't Work)

### Method 2: System Package + PYTHONPATH (Ubuntu/Debian)

#### Step 1: Install FreeCAD system package
```bash
sudo apt update
sudo apt install freecad python3-freecad
```

#### Step 2: Find FreeCAD Python path
```bash
# Find where FreeCAD installed its Python modules
dpkg -L python3-freecad | grep -i freecad.so

# Common locations:
# /usr/lib/freecad/lib/FreeCAD.so
# /usr/lib/python3/dist-packages/
```

#### Step 3: Add to PYTHONPATH
```bash
# Test which path works
python3 -c "import sys; sys.path.append('/usr/lib/freecad/lib'); import FreeCAD; print(FreeCAD.Version())"

# If that works, add to your environment
echo 'export PYTHONPATH="/usr/lib/freecad/lib:$PYTHONPATH"' >> ~/.bashrc
source ~/.bashrc

# Verify
python3 -c "import FreeCAD; print('Success!')"
```

### Method 3: macOS with Homebrew

#### Step 1: Install FreeCAD
```bash
brew install --cask freecad
```

#### Step 2: Add to PYTHONPATH
```bash
# Add FreeCAD's lib directory to PYTHONPATH
echo 'export PYTHONPATH="/Applications/FreeCAD.app/Contents/Resources/lib:$PYTHONPATH"' >> ~/.zshrc
source ~/.zshrc

# Verify
python3 -c "import FreeCAD; print('Success!')"
```

### Method 4: Windows

#### Option A: Via Conda (Recommended)
```powershell
conda create -n cadquery python=3.9
conda activate cadquery
conda install -c conda-forge freecad cadquery
```

#### Option B: Manual Installation
1. Install FreeCAD from https://www.freecad.org/downloads.php
2. Find installation directory (e.g., `C:\Program Files\FreeCAD 0.21\bin`)
3. Add to PYTHONPATH:
   ```powershell
   # PowerShell
   $env:PYTHONPATH = "C:\Program Files\FreeCAD 0.21\bin;$env:PYTHONPATH"
   
   # Or add permanently via System Environment Variables
   ```

---

## Quick Test Script

Save this as `test_freecad_import.py`:

```python
#!/usr/bin/env python3
"""Test if FreeCAD module is importable"""

print("Testing FreeCAD import...")
print("-" * 50)

try:
    import FreeCAD
    print("✓ FreeCAD imported successfully!")
    print(f"  Version: {'.'.join(FreeCAD.Version()[:3])}")
    
    import Part
    print("✓ Part module imported successfully!")
    
    import Mesh
    print("✓ Mesh module imported successfully!")
    
    print()
    print("✓ All FreeCAD modules working!")
    print()
    print("You can now use cadquery_freecad_exporter.py")
    
except ImportError as e:
    print(f"✗ FreeCAD import failed: {e}")
    print()
    print("Solutions:")
    print("  1. Install via conda (recommended):")
    print("     conda install -c conda-forge freecad")
    print()
    print("  2. Add FreeCAD to PYTHONPATH:")
    print("     export PYTHONPATH='/usr/lib/freecad/lib:$PYTHONPATH'")
    print()
    print("  3. Check installation:")
    print("     freecad --version")
```

Run it:
```bash
python test_freecad_import.py
```

---

## Troubleshooting

### Issue 1: "ModuleNotFoundError: No module named 'FreeCAD'"

**Solution:** FreeCAD Python module is not in your PYTHONPATH.

**Fix with Conda (easiest):**
```bash
conda install -c conda-forge freecad
```

**Fix manually:**
```bash
# Find FreeCAD installation
which freecad  # Linux/macOS
where freecad  # Windows

# Find the lib directory containing FreeCAD.so or FreeCAD.pyd
find /usr -name "FreeCAD.so" 2>/dev/null

# Add to PYTHONPATH (example for Ubuntu)
export PYTHONPATH="/usr/lib/freecad/lib:$PYTHONPATH"
```

### Issue 2: "ImportError: libFreeCAD.so.0.21: cannot open shared object file"

**Cause:** FreeCAD shared libraries not found.

**Solution (Ubuntu/Debian):**
```bash
# Install missing packages
sudo apt install freecad python3-freecad

# Update library cache
sudo ldconfig
```

### Issue 3: Python version mismatch

**Cause:** FreeCAD compiled for different Python version.

**Solution:** Use conda to ensure compatible versions:
```bash
conda create -n cadquery python=3.9
conda activate cadquery
conda install -c conda-forge freecad
```

### Issue 4: Works in system Python but not conda

**Solution:** Install FreeCAD in the conda environment:
```bash
conda activate cadquery
conda install -c conda-forge freecad
```

Don't mix system Python and conda Python!

### Issue 5: macOS - "Architecture mismatch"

**Solution:** Ensure you're using the right architecture:
```bash
# Check your architecture
uname -m

# For Apple Silicon (M1/M2):
arch -arm64 python -c "import FreeCAD"

# For Intel:
arch -x86_64 python -c "import FreeCAD"
```

---

## Verification Steps

### Step 1: Check FreeCAD Application
```bash
# Check if FreeCAD is installed
freecad --version

# Should show something like:
# FreeCAD 0.21.2, Libs: 0.21.2
```

### Step 2: Check Python Import
```bash
# Try importing FreeCAD
python -c "import FreeCAD"

# If no error, you're good!
```

### Step 3: Check All Required Modules
```bash
python << 'EOF'
import FreeCAD
import Part
import Mesh
print("✓ All modules imported successfully!")
print(f"FreeCAD version: {FreeCAD.Version()}")
EOF
```

### Step 4: Test the Exporter
```bash
# Run the test script
python test_freecad_export.py
```

---

## Recommended Setup (Complete)

Here's the **complete recommended setup** from scratch:

```bash
# 1. Install conda/mamba (if not already installed)
# Download from: https://docs.conda.io/en/latest/miniconda.html

# 2. Create dedicated environment
conda create -n cadquery python=3.9
conda activate cadquery

# 3. Install all required packages
conda install -c conda-forge cadquery freecad
pip install numpy requests

# 4. Verify everything works
python -c "import cadquery as cq; print('CadQuery:', cq.__version__)"
python -c "import FreeCAD; print('FreeCAD:', FreeCAD.Version())"

# 5. Test the exporter
python << 'EOF'
import cadquery as cq
from cadquery_freecad_exporter import FreeCADExporter

box = cq.Workplane("XY").box(10, 10, 10)
exporter = FreeCADExporter(box, model_name="Test")
print("✓ Exporter works!")
EOF
```

**This should work on all platforms!**

---

## Platform-Specific Notes

### Ubuntu/Linux Mint
- ✅ `conda install -c conda-forge freecad` works perfectly
- ✅ System package `apt install python3-freecad` also works
- Choose one approach, don't mix them

### macOS
- ✅ Conda is most reliable
- ⚠️ Homebrew FreeCAD requires PYTHONPATH setup
- Apple Silicon: Use conda with `osx-arm64` packages

### Windows
- ✅ Conda is strongly recommended
- ⚠️ Manual installation requires PATH/PYTHONPATH setup
- Use PowerShell or Windows Terminal

---

## Quick Reference

| Platform | Best Method | Command |
|----------|-------------|---------|
| **Any** | Conda | `conda install -c conda-forge freecad` |
| **Ubuntu** | APT | `sudo apt install python3-freecad` |
| **macOS** | Conda | `conda install -c conda-forge freecad` |
| **Windows** | Conda | `conda install -c conda-forge freecad` |

---

## Summary

**Easiest path to success:**

1. **Install conda** (if not already)
2. **Create environment:** `conda create -n cadquery python=3.9`
3. **Activate:** `conda activate cadquery`
4. **Install everything:** `conda install -c conda-forge cadquery freecad`
5. **Test:** `python -c "import FreeCAD; print('Success!')"`

**That's it!** You now have a working FreeCAD Python module and can use the exporter.

---

## Next Steps

Once FreeCAD is installed and importable:

```bash
# Test the exporter
python test_freecad_export.py

# Use it in your code
python << 'EOF'
import cadquery as cq
from cadquery_freecad_exporter import FreeCADExporter

result = cq.Workplane("XY").box(10, 10, 10)
exporter = FreeCADExporter(result, model_name="MyBox")
exporter.save_to_file("mybox.json")
print("✓ Created mybox.json")
EOF
```

Good luck! The conda approach should work first try. 🎯
