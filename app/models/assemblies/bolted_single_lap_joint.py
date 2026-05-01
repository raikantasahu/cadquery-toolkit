"""Bolted single-lap joint assembly.

Two ``plate_with_hole`` instances joined by one ``hex_bolt`` passing
through aligned holes — a single-lap (two-plate, one-shear-plane)
configuration. The plates are stacked so their lap regions overlap; the
bolt's shank passes through both plates from the top, with the head
seated on the upper plate's top face.

Geometry (units = mm, X is the load axis):

    Plate 1 (lower): unrotated; its lap end faces +X (toward Plate 2);
                     spans z in [0, plate_thickness].
    Plate 2 (upper): rotated 180 deg around Z so its lap end faces -X;
                     spans z in [plate_thickness, 2*plate_thickness].
    Bolt: head bottom seated at z = 2*plate_thickness; shank extends
          downward, passing through both plates.

Children: ``plate1``, ``plate2``, ``bolt``.

The bolt's secondary dimensions (pitch, head width, head height) are
derived from the bolt diameter using approximate ISO metric proportions —
adequate for visualization and meshing; not a strict standard lookup.
"""

import cadquery as cq


def bolted_single_lap_joint(
    plate_thickness: float = 6.0,
    plate_width: float = 60.0,
    bolt_diameter: float = 12.0,
    lap_length: float = 50.0,
    grip_length: float = 80.0,
    bolt_length: float = 30.0,
) -> cq.Assembly:
    # Imported inside the function so the assembly module's import-time
    # cost stays minimal (parts registry is only touched when the assembly
    # is actually invoked).
    from models.parts import get_part_function

    plate_with_hole = get_part_function("plate_with_hole")
    hex_bolt = get_part_function("hex_bolt")
    if plate_with_hole is None or hex_bolt is None:
        raise RuntimeError(
            "bolted_single_lap_joint requires the parts 'plate_with_hole' "
            "and 'hex_bolt' to be registered."
        )

    plate_length = grip_length + lap_length
    half_lap = lap_length / 2
    plate_offset_x = plate_length - half_lap   # distance from plate origin to its hole

    plate = plate_with_hole(
        length=plate_length,
        width=plate_width,
        thickness=plate_thickness,
        hole_diameter=bolt_diameter,
        edge_distance=half_lap,
    )
    bolt = hex_bolt(
        diameter=bolt_diameter,
        length=bolt_length,
        pitch=0.15 * bolt_diameter,
        head_width=1.5 * bolt_diameter,
        head_height=0.65 * bolt_diameter,
    )

    plate_color = cq.Color(0.40, 0.50, 0.70)
    bolt_color = cq.Color(0.75, 0.75, 0.78)

    assy = cq.Assembly(name="bolted_single_lap_joint")

    # Plate 1: unrotated, translated so its hole lands at world origin.
    assy.add(
        plate,
        name="plate1",
        color=plate_color,
        loc=cq.Location(cq.Vector(-plate_offset_x, 0, 0)),
    )

    # Plate 2: rotated 180 deg around Z (so its lap end faces -X), then
    # translated so its hole lands at world origin and it sits directly
    # on top of plate 1. Composition order is "rotate then translate".
    assy.add(
        plate,
        name="plate2",
        color=plate_color,
        loc=(
            cq.Location(cq.Vector(plate_offset_x, 0, plate_thickness))
            * cq.Location(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), 180)
        ),
    )

    # Bolt: head bottom seated at the top of plate 2; shank extends down
    # through both plates.
    assy.add(
        bolt,
        name="bolt",
        color=bolt_color,
        loc=cq.Location(cq.Vector(0, 0, 2 * plate_thickness)),
    )

    return assy
