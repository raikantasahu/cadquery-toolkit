"""Bolted single-lap joint assembly.

Two overlapping plates joined by one or more ``double_headed_hex_bolt``
instances passing through aligned holes — a single-lap (two-plate, one-shear-
plane) configuration. The plates are stacked so their lap regions overlap;
each bolt's shank passes through both plates, with a hex head seated on each
outer face of the stack.

``num_bolts`` bolts are arranged in a single transverse row across the plate
width (the Y axis, perpendicular to the X load axis), evenly spaced and
symmetric about the plate centerline. The bolt count is bounded only by
geometry: the limiting dimension is the hex head, not the hole. Each head's
largest extent is its across-corners size (``head_width / cos(30 deg)``), so
adjacent heads stay clear of each other and of the plate edges only while
``num_bolts <= floor(plate_width / head_across_corners)``.

Geometry (units = mm, X is the load axis):

    Plate 1 (lower): unrotated; its lap end faces +X (toward Plate 2);
                     spans z in [0, plate_thickness].
    Plate 2 (upper): rotated 180 deg around Z so its lap end faces -X;
                     spans z in [plate_thickness, 2*plate_thickness].
    Bolts: upper head seated on plate 2's top face (z = 2*plate_thickness);
           shank spans the grip through both plates; lower head seated on
           plate 1's bottom face (z = 0). The hole row is symmetric in Y,
           so the same hole pattern aligns after plate 2's 180 deg rotation.

Children: ``bottom-plate``, ``top-plate``, and ``bolt-1`` .. ``bolt-N``.

The bolt's secondary dimensions (pitch, head width, head height) are
derived from the bolt diameter using approximate ISO metric proportions —
adequate for visualization and meshing; not a strict standard lookup.
"""

import math

import cadquery as cq


def bolted_single_lap_joint(
    plate_thickness: float = 6.0,
    plate_width: float = 60.0,
    bolt_diameter: float = 12.0,
    lap_length: float = 50.0,
    grip_length: float = 80.0,
    num_bolts: int = 1,
) -> cq.Assembly:
    # Imported inside the function so the assembly module's import-time
    # cost stays minimal (parts registry is only touched when the assembly
    # is actually invoked).
    from models.parts import get_part_function

    double_headed_hex_bolt = get_part_function("double_headed_hex_bolt")
    if double_headed_hex_bolt is None:
        raise RuntimeError(
            "bolted_single_lap_joint requires the part "
            "'double_headed_hex_bolt' to be registered."
        )

    if int(num_bolts) != num_bolts or num_bolts < 1:
        raise ValueError(
            f"num_bolts must be an integer >= 1, got {num_bolts!r}."
        )
    num_bolts = int(num_bolts)

    # The hex head, not the hole, is the limiting footprint. Use the head's
    # across-corners dimension (its largest extent, independent of how the
    # hexagon is rotated) so heads can never interfere. These proportions must
    # stay in sync with the double_headed_hex_bolt(...) call below.
    head_width = 1.5 * bolt_diameter            # hex across-flats (wrench size)
    head_height = 0.65 * bolt_diameter
    head_across_corners = head_width / math.cos(math.radians(30))

    # Bolts sit in a single transverse row, evenly spaced across the width
    # with each head at the center of an equal Y-segment of width
    # plate_width / num_bolts. That segment must be at least one head footprint
    # wide for adjacent heads to clear each other and stay within the plate.
    max_bolts = int(plate_width // head_across_corners)
    if num_bolts > max_bolts:
        raise ValueError(
            f"num_bolts={num_bolts} does not fit: {num_bolts} hex heads "
            f"{head_across_corners:.2f} mm across corners would interfere "
            f"within a {plate_width} mm wide plate. Maximum is {max_bolts}."
        )

    plate_length = grip_length + lap_length
    half_lap = lap_length / 2
    plate_offset_x = plate_length - half_lap   # distance from plate origin to its hole line
    hole_x = plate_length - half_lap           # hole X in the plate's local frame

    # Y positions of the holes/bolts: center of each equal-width segment,
    # symmetric about y = 0 (single hole at y = 0 when num_bolts == 1).
    segment = plate_width / num_bolts
    bolt_ys = [
        -plate_width / 2 + segment / 2 + i * segment for i in range(num_bolts)
    ]

    plate = _plate_with_hole_row(
        length=plate_length,
        width=plate_width,
        thickness=plate_thickness,
        hole_diameter=bolt_diameter,
        hole_x=hole_x,
        hole_ys=bolt_ys,
    )

    # Shank between the two heads spans the grip (both plate thicknesses)
    # so a head seats on each outer face of the stack.
    grip = 2 * plate_thickness
    bolt = double_headed_hex_bolt(
        diameter=bolt_diameter,
        length=grip,
        pitch=0.15 * bolt_diameter,
        head_width=head_width,
        head_height=head_height,
    )

    plate_color = cq.Color(0.40, 0.50, 0.70)
    bolt_color = cq.Color(0.75, 0.75, 0.78)

    assy = cq.Assembly(name="bolted_single_lap_joint")

    # Plate 1: unrotated, translated so its hole line lands at world x = 0.
    assy.add(
        plate,
        name="bottom-plate",
        color=plate_color,
        loc=cq.Location(cq.Vector(-plate_offset_x, 0, 0)),
    )

    # Plate 2: rotated 180 deg around Z (so its lap end faces -X), then
    # translated so its hole line lands at world x = 0 and it sits directly
    # on top of plate 1. Composition order is "rotate then translate".
    # The hole row is symmetric in Y, so the rotated pattern still aligns.
    assy.add(
        plate,
        name="top-plate",
        color=plate_color,
        loc=(
            cq.Location(cq.Vector(plate_offset_x, 0, plate_thickness))
            * cq.Location(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), 180)
        ),
    )

    # One bolt per hole: upper head seated on top of plate 2; shank spans the
    # grip and the lower head seats under plate 1 (at z = 0).
    for index, bolt_y in enumerate(bolt_ys, start=1):
        assy.add(
            bolt,
            name=f"bolt-{index}",
            color=bolt_color,
            loc=cq.Location(cq.Vector(0, bolt_y, 2 * plate_thickness)),
        )

    return assy


def _plate_with_hole_row(
    length: float,
    width: float,
    thickness: float,
    hole_diameter: float,
    hole_x: float,
    hole_ys: list,
) -> cq.Workplane:
    """Rectangular plate (x in [0, length], centered in y, z in [0, thickness])
    with a row of through-holes at ``hole_x`` for each Y in ``hole_ys``."""
    plate = cq.Workplane("XY").box(
        length, width, thickness, centered=(False, True, False)
    )
    holes = (
        cq.Workplane("XY")
        .pushPoints([(hole_x, y) for y in hole_ys])
        .circle(hole_diameter / 2)
        .extrude(thickness)
    )
    return plate.cut(holes)
