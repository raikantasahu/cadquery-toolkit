"""T11 (cap face) — extruded-hex cap face resolved by geometry (Feature R3).

The cap face is named by its centroid (geometric), resolved via the resolver
instead of a PersistentID == gmsh-tag-1 assumption.
"""
from mesher import create_mesh
from mesher.gmsh_mesher import ExtrusionSpec
from models.parts import get_part_function


def test_cap_face_by_centroid():
    # box(10,20,30) centered: top face at z=15, centroid (0,0,15), area 200.
    box = get_part_function("box")(10, 20, 30)
    mesher, stats = create_mesh(
        box, "hex8", 5.0, model_name="box",
        extrusion=ExtrusionSpec(cap_face_at=(0.0, 0.0, 15.0),
                                cap_face_area=200.0, num_layers=3))
    try:
        assert stats["element_count"] > 0
        assert "Hexahedron" in stats["element_types"]
    finally:
        mesher.finalize()
