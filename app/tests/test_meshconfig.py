"""Shared mesh-config basics parser (Core-UI-Separation Phase 4)."""
import pytest

from meshconfig import parse_mesh_basics


def _err(msg):
    raise ValueError(msg)


def test_defaults():
    assert parse_mesh_basics({}, _err) == ("tet4", 5.0, None)


def test_valid_values_coerced():
    assert parse_mesh_basics(
        {"elementType": "hex8", "elementSize": 2, "relativeSagTolerance": 0.01},
        _err) == ("hex8", 2.0, 0.01)


def test_unknown_element_type_errors():
    with pytest.raises(ValueError):
        parse_mesh_basics({"elementType": "tet5"}, _err)


def test_nonpositive_sag_errors():
    with pytest.raises(ValueError):
        parse_mesh_basics({"relativeSagTolerance": 0}, _err)


def test_generate_consumes_meshconfig(fixtures):
    """The mesher's typed contract: GmshMesher.generate(MeshConfig) meshes."""
    from mesher import GmshMesher, MeshConfig, MeshType
    mesher = GmshMesher(fixtures["hertz"]["model"], model_name="h")
    try:
        stats = mesher.generate(MeshConfig(MeshType.TET4, element_size=8.0))
        assert stats["element_count"] > 0
    finally:
        mesher.finalize()
