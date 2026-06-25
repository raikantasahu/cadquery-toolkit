"""An angular sector of a (lower) cylinder, extruded along its axis.

The lower part (``z <= 0``) of a circular cylinder whose axis runs along +Y,
cross-section centered on the Y axis with radius ``radius``, kept only over an
angular sector of ``sweep_angle`` degrees measured about the axis starting from
the +X half-plane (sweeping down toward -Z). The contact line sits along the Y
axis at ``(0, 0, -radius)`` and the solid spans ``y in [0, length]``.

  * ``sweep_angle = 180`` → the full lower half-cylinder (``z <= 0``), the
    contact body for a single-symmetry-plane line-contact model.
  * ``sweep_angle = 90``  → one quarter of the cylinder — the lower-right
    quadrant (``x >= 0, z <= 0``) bounded by the ``x = 0`` plane, the contact
    body for the quarter-symmetry line-contact (Hertzian) model.

Built by extruding a sector-of-a-disk profile (in the X-Z cross-section plane,
radius ``radius``, in ``z <= 0``) along +Y, so the flat radial cut face lands
on the ``x = 0`` plane (for ``sweep_angle = 90``), the ``z = 0`` rectangle is
the truncated top, the two disk end caps land on ``y = 0`` and ``y = length``,
and the cylindrical surface is the contact face.
"""

import math

import cadquery as cq


def cylinder_sector(
    radius: float = 10.0, length: float = 20.0, sweep_angle: float = 180.0
) -> cq.Workplane:
    """An angular sector of the lower half of a Y-axis cylinder.

    Args:
        radius: Cylinder radius. The contact line lands along the Y axis at
            ``z = -radius``.
        length: Axial extent in +Y; the solid spans ``y in [0, length]``.
        sweep_angle: Angular extent in degrees of the cross-section sector,
            swept about the axis from the +X half-plane down toward -Z. 180
            gives the full lower half-cylinder; 90 gives a quarter cylinder in
            ``x >= 0, z <= 0``.

    Sample use: cylinder_sector(10.0, 20.0, 90.0)
    """
    if not 0 < sweep_angle <= 180:
        raise ValueError(
            f"sweep_angle must be in (0, 180] degrees, got {sweep_angle!r}."
        )

    # Sector-of-a-disk in the X-Z cross-section plane: top radius (0,0)->(R,0),
    # circular arc down to the sector end, then back to the center to close.
    # Local (u, v) on the XZ workplane map to global (X, Z), so this lies in
    # z <= 0 (and in x >= 0 when sweep_angle <= 90). midarc is the arc's
    # half-angle point.
    theta = math.radians(sweep_angle)
    end = (radius * math.cos(theta), -radius * math.sin(theta))
    midarc = (radius * math.cos(theta / 2.0), -radius * math.sin(theta / 2.0))
    profile = (
        cq.Workplane("XZ")
        .moveTo(0, 0)
        .lineTo(radius, 0)
        .threePointArc(midarc, end)
        .close()
    )
    # The XZ workplane normal is global -Y, so extrude(length) builds the solid
    # over y in [-length, 0]; shift it to y in [0, length] so the y = 0 end cap
    # lands on the symmetry plane.
    return profile.extrude(length).translate((0, length, 0))
