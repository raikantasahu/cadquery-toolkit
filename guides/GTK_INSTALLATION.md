# Installing GTK GUI for CadQuery

This guide helps you install the GTK-based GUI which has much better text rendering on Linux, especially under conda environments.

## Why GTK?

The GTK version provides:
- **Crystal-clear text rendering** (native Linux font rendering)
- Native Linux look and feel
- Better integration with Linux Mint/GNOME
- Professional appearance
- No jagged text issues under conda

## Installation Methods

### Method 1: System Python with System Packages (Recommended)

This is the cleanest approach for Linux Mint:

```bash
# Install GTK3 Python bindings (system package)
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0

# Install CadQuery
pip install cadquery --break-system-packages

# Run the GTK GUI
python3 cadquery_gui_gtk.py
```

### Method 2: Install PyGObject via pip

If you're using a conda environment or virtual environment:

```bash
# Install system dependencies first
sudo apt install libgirepository1.0-dev gcc libcairo2-dev pkg-config python3-dev gir1.2-gtk-3.0

# Install PyGObject via pip
pip install pygobject --break-system-packages

# Install CadQuery
pip install cadquery --break-system-packages

# Run the GTK GUI
python cadquery_gui_gtk.py
```

### Method 3: Using Conda

```bash
# Create a new conda environment
conda create -n cqgui python=3.10
conda activate cqgui

# Install PyGObject and GTK from conda-forge
conda install -c conda-forge pygobject gtk3

# Install CadQuery
pip install cadquery

# Run the GTK GUI
python cadquery_gui_gtk.py
```

## Verifying Installation

Test that GTK works:

```bash
python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; print('GTK OK')"
```

If you see "GTK OK", you're ready to go!

## Troubleshooting

### Error: "No module named 'gi'"

Install the Python GTK bindings:
```bash
sudo apt install python3-gi
```

### Error: "Namespace Gtk not available"

Install the GTK3 introspection data:
```bash
sudo apt install gir1.2-gtk-3.0
```

### Error: "No module named 'cairo'"

Install Cairo Python bindings:
```bash
sudo apt install python3-gi-cairo
```

## Comparison: Tkinter vs GTK

| Feature | Tkinter (cadquery_gui.py) | GTK (cadquery_gui_gtk.py) |
|---------|---------------------------|---------------------------|
| Text rendering | Poor under conda | Excellent |
| Installation | Built-in | Requires packages |
| Linux integration | Basic | Native |
| Appearance | Generic | Professional |
| Font smoothing | Limited | Perfect |

## Running the GUI

Once installed, simply run:

```bash
python3 cadquery_gui_gtk.py
```

or

```bash
python cadquery_gui_gtk.py
```

The interface is identical to the tkinter version but with much better text rendering!

## File Naming

- `cadquery_gui.py` - Original tkinter version
- `cadquery_gui_gtk.py` - New GTK version (recommended for Linux)

Both versions have the same functionality and produce the same output files.
