"""Hertzian line-contact verification model: cylinder on an elastic block.

A quarter-symmetry FE model for verifying Hertzian (cylinder-on-elastic-half-
space) *line* contact against the closed-form solution. A cylinder pressed
against a flat block touches along a line, so the problem has two symmetry
planes and only one quarter need be modeled:

    x = 0   the cross-section plane through the contact line, halving the
            circular section into the modeled x >= 0 half.
    y = 0   the plane perpendicular to the cylinder axis, halving the length
            into the modeled y in [0, length] half.

The two modeled bodies are:

    cylinder-quarter   a quarter of the cylinder (lower-right quadrant of the
                       section, x >= 0, z <= 0), radius ``cylinder_radius``,
                       contact line along the Y axis at z = -R. The upper half
                       is irrelevant to the contact and is truncated at z = 0,
                       where the load is applied.
    foundation-quarter a quarter of a rectangular elastic block sitting just
                       under the contact line, its top face at z = -R. Stands
                       in for the elastic half-space; make it large vs. the
                       contact half-width ``b`` for the half-space
                       approximation to hold.

The bodies touch along the line x = 0, z = -R (zero initial gap), the natural
starting configuration for an FE contact solve.

Faces that the FE solver needs (named later via the mesh-config ``owners`` map
or the picker, not here):
    cylinder : x=0 symmetry plane, y=0 symmetry end-cap, y=length end-cap,
               z=0 load-top, cylindrical contact face.
    block    : x=0 symmetry plane, y=0 symmetry plane, z=-R contact-top, fixed
               bottom face, and the outer side faces (x = block_half_width,
               y = block_half_length).

Units = mm; Z is the contact/load axis, Y is the cylinder axis.
"""

import cadquery as cq


def hertzian_cylinder_on_block_quarter_symmetry(
    cylinder_radius: float = 10.0,
    cylinder_half_length: float = 20.0,
    block_half_width: float = 30.0,
    block_depth: float = 30.0,
) -> cq.Assembly:
    """Quarter-symmetry cylinder-on-elastic-block Hertzian line-contact model.

    Args:
        cylinder_radius: Radius R of the contacting cylinder.
        cylinder_half_length: Cylinder extent in +Y from the y = 0 symmetry
            plane (the full cylinder would be twice this). The block shares
            this length so both bodies are bounded by the same y = 0 and
            y = cylinder_half_length planes.
        block_half_width: Block extent in +X from the symmetry plane (the full
            block would be twice this). Keep it large relative to the expected
            contact half-width for a valid half-space approximation.
        block_depth: Block extent in -Z below its top face (at z = -R).

    Sample use: hertzian_cylinder_on_block_quarter_symmetry(10.0, 20.0, 30.0, 30.0)
    """
    from models.parts import get_part_function

    cylinder_sector = get_part_function("cylinder_sector")
    if cylinder_sector is None:
        raise RuntimeError(
            "hertzian_cylinder_on_block_quarter_symmetry requires the part "
            "'cylinder_sector' to be registered."
        )

    # 90-degree sector = one cylinder quarter (x >= 0, z <= 0), axis along +Y.
    cylinder = cylinder_sector(
        radius=cylinder_radius,
        length=cylinder_half_length,
        sweep_angle=90.0,
    )
    block = _quarter_block(
        half_width=block_half_width,
        length=cylinder_half_length,
        depth=block_depth,
        top_z=-cylinder_radius,  # top face meets the contact line at z = -R
    )

    cylinder_color = cq.Color(0.70, 0.45, 0.40)
    block_color = cq.Color(0.45, 0.55, 0.70)

    assy = cq.Assembly(name="hertzian_cylinder_on_block_quarter_symmetry")
    assy.add(cylinder, name="cylinder-quarter", color=cylinder_color)
    assy.add(block, name="foundation-quarter", color=block_color)
    return assy


def _quarter_block(
    half_width: float, length: float, depth: float, top_z: float
) -> cq.Workplane:
    """First-quadrant block: x in [0, half_width], y in [0, length],
    z in [top_z - depth, top_z]."""
    return (
        cq.Workplane("XY")
        .box(half_width, length, depth, centered=False)
        .translate((0, 0, top_z - depth))
    )
