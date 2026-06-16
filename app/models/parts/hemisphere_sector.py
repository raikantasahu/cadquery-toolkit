"""An angular sector of a (lower) hemisphere.

The lower hemisphere (``z <= 0``) of a sphere centered at the origin, kept only
over an azimuthal sector of ``sweep_angle`` degrees measured about +Z starting
from the +X half-plane (sweeping toward +Y). The contact pole sits at
``(0, 0, -radius)``.

  * ``sweep_angle = 360`` → the full lower hemisphere.
  * ``sweep_angle = 90``  → one octant (1/8) of a sphere — a quarter of the
    lower hemisphere bounded by the ``x = 0`` and ``y = 0`` planes, the contact
    body for the quarter-symmetry Hertzian model.

Built by revolving a quarter-disk profile (in the X-Z half-plane, radius
``radius``, in ``x >= 0, z <= 0``) about the Z axis, so the flat radial cut
faces land exactly on the start (``y = 0``) and end (rotated by
``sweep_angle``) planes, the ``z = 0`` sector disk is the truncated top, and
the spherical surface is the contact face.
"""

import math

import cadquery as cq


def hemisphere_sector(radius: float = 10.0, sweep_angle: float = 360.0) -> cq.Workplane:
    """An azimuthal sector of the lower hemisphere of radius ``radius``.

    Args:
        radius: Sphere radius. The contact pole lands at ``(0, 0, -radius)``.
        sweep_angle: Azimuthal extent in degrees, swept about +Z from the +X
            half-plane toward +Y. 360 gives the full lower hemisphere; 90 gives
            a sphere octant in ``x >= 0, y >= 0, z <= 0``.

    Sample use: hemisphere_sector(10.0, 90.0)
    """
    if not 0 < sweep_angle <= 360:
        raise ValueError(
            f"sweep_angle must be in (0, 360] degrees, got {sweep_angle!r}."
        )

    # Quarter-disk in the X-Z half-plane: top radius (0,0)->(R,0), spherical
    # arc down to the pole (0,-R), then back up the Z axis to close. Local
    # (u, v) on the XZ workplane map to global (X, Z), so this lies in
    # x >= 0, z <= 0. midarc is the arc's 45-degree point.
    midarc = radius / math.sqrt(2.0)
    profile = (
        cq.Workplane("XZ")
        .moveTo(0, 0)
        .lineTo(radius, 0)
        .threePointArc((midarc, -midarc), (0, -radius))
        .close()
    )
    # Revolve about +Z. The XZ workplane's local Y-axis is global +Z, which is
    # revolve's default axis (through the workplane origin), so no explicit axis
    # is given — passing one in local coords would be mis-mapped to the plane
    # normal. Positive angle sweeps +X toward +Y (right-hand rule).
    return profile.revolve(sweep_angle)
