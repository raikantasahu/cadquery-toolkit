Here are the standard dimensions for common hex nuts. These follow ISO 4032 for metric and USS/ANSI for inch sizes.

**Metric Hex Nuts (ISO 4032):**

| Size | hole_diameter | width | height |
|------|---------------|-------|--------|
| M3   | 3.0           | 5.5   | 2.4    |
| M4   | 4.0           | 7.0   | 3.2    |
| M5   | 5.0           | 8.0   | 4.0    |
| M6   | 6.0           | 10.0  | 5.0    |
| M8   | 8.0           | 13.0  | 6.5    |
| M10  | 10.0          | 16.0  | 8.0    |
| M12  | 12.0          | 18.0  | 10.0   |
| M14  | 14.0          | 21.0  | 11.0   |
| M16  | 16.0          | 24.0  | 13.0   |
| M20  | 20.0          | 30.0  | 16.0   |
| M24  | 24.0          | 36.0  | 19.0   |

**Inch Hex Nuts (USS/ANSI):**

| Size  | hole_diameter | width  | height |
|-------|---------------|--------|--------|
| 1/4"  | 6.35          | 11.11  | 5.56   |
| 5/16" | 7.94          | 12.70  | 6.75   |
| 3/8"  | 9.53          | 14.29  | 8.33   |
| 1/2"  | 12.70         | 19.05  | 11.11  |
| 5/8"  | 15.88         | 23.81  | 13.49  |
| 3/4"  | 19.05         | 28.58  | 16.67  |
| 1"    | 25.40         | 38.10  | 21.83  |

Your default values (width=13.0, height=5.0, hole_diameter=8.0) are a reasonable approximation of an M8 nut—the actual M8 is 13.0 wide but 6.5 tall, so you might adjust the height default slightly.

You could also add a convenience factory or presets:

```python
HEX_NUT_SIZES = {
    "M6":  {"width": 10.0, "height": 5.0,  "hole_diameter": 6.0},
    "M8":  {"width": 13.0, "height": 6.5,  "hole_diameter": 8.0},
    "M10": {"width": 16.0, "height": 8.0,  "hole_diameter": 10.0},
    "M12": {"width": 18.0, "height": 10.0, "hole_diameter": 12.0},
}

def hex_nut_standard(size: str, chamfer: bool = True):
    """Create a standard hex nut by size designation."""
    params = HEX_NUT_SIZES[size]
    return hex_nut(**params, chamfer=chamfer)
```
