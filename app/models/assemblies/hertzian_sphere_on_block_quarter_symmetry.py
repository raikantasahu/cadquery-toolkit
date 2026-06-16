"""Hertzian contact verification model: sphere on an elastic block.

A quarter-symmetry FE model for verifying Hertzian (sphere-on-elastic-half-
space) contact against the closed-form solution. Only one quarter of the
problem is modeled, exploiting the two vertical symmetry planes ``x = 0`` and
``y = 0`` through the contact axis (Z):

    sphere-octant      1/8 of a sphere (a quarter of the lower hemisphere),
                       radius ``sphere_radius``, contact pole at (0, 0, -R).
                       The upper hemisphere is irrelevant to the contact and
                       is truncated at z = 0, where the load is applied.
    foundation-quarter a quarter of a rectangular elastic block sitting just
                       under the pole, its top face at z = -R. Stands in for
                       the elastic half-space; make it large vs. the contact
                       radius ``a`` for the half-space approximation to hold.

The bodies touch at the single point (0, 0, -R) (zero initial gap), the
natural starting configuration for an FE contact solve.

Faces that the FE solver needs (named later via the mesh-config ``owners``
map or the picker, not here):
    sphere : x=0 / y=0 symmetry planes, z=0 load-top, spherical contact face.
    block  : x=0 / y=0 symmetry planes, z=-R contact-top, fixed bottom face,
             and the two outer side faces (x = block_half_width,
             y = block_half_width).

Units = mm; Z is the contact/load axis.
"""

import cadquery as cq


def hertzian_sphere_on_block_quarter_symmetry(
    sphere_radius: float = 10.0,
    block_half_width: float = 30.0,
    block_depth: float = 30.0,
) -> cq.Assembly:
    """Quarter-symmetry sphere-on-elastic-block Hertzian contact model.

    Args:
        sphere_radius: Radius R of the contacting sphere.
        block_half_width: Block extent in +X and +Y from the symmetry axis
            (the full block would be twice this). Keep it large relative to
            the expected contact radius for a valid half-space approximation.
        block_depth: Block extent in -Z below its top face (at z = -R).

    Sample use: hertzian_sphere_on_block_quarter_symmetry(10.0, 30.0, 30.0)
    """
    from models.parts import get_part_function

    hemisphere_sector = get_part_function("hemisphere_sector")
    if hemisphere_sector is None:
        raise RuntimeError(
            "hertzian_sphere_on_block_quarter_symmetry requires the part "
            "'hemisphere_sector' to be registered."
        )

    # 90-degree sector = one sphere octant (x >= 0, y >= 0, z <= 0).
    sphere = hemisphere_sector(radius=sphere_radius, sweep_angle=90.0)
    block = _quarter_block(
        half_width=block_half_width,
        depth=block_depth,
        top_z=-sphere_radius,   # top face meets the sphere's pole at (0,0,-R)
    )

    sphere_color = cq.Color(0.70, 0.45, 0.40)
    block_color = cq.Color(0.45, 0.55, 0.70)

    assy = cq.Assembly(name="hertzian_sphere_on_block_quarter_symmetry")
    assy.add(sphere, name="sphere-octant", color=sphere_color)
    assy.add(block, name="foundation-quarter", color=block_color)
    return assy


def _quarter_block(half_width: float, depth: float, top_z: float) -> cq.Workplane:
    """First-quadrant block: x,y in [0, half_width], z in [top_z - depth, top_z]."""
    return (
        cq.Workplane("XY")
        .box(half_width, half_width, depth, centered=False)
        .translate((0, 0, top_z - depth))
    )
