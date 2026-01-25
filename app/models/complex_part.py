"""Complex part model"""

import cadquery as cq

def complex_part(add_fillets: bool = True):
    """Create a more complex part

    Args:
        add_fillets: Whether to add edge fillets

    Sample use: complex_part(True)
    """
    # Create a complex part with multiple features
    result = (
        cq.Workplane("XY")
        .box(50, 50, 10)  # Base
        .faces(">Z")
        .workplane()
        .pushPoints([(-15, 15), (15, 15), (-15, -15), (15, -15)])
        .circle(3)
        .cutThruAll()  # Corner holes
        .faces(">Z")
        .workplane()
        .circle(10)
        .extrude(15)  # Center boss
        .faces(">Z")
        .workplane()
        .circle(5)
        .cutThruAll()  # Center hole through everything
    )

    if add_fillets:
        result = result.edges("|Z").fillet(1)  # Fillet edges

    return result
