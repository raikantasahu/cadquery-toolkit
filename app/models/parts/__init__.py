"""parts — parametric part functions.

Auto-discovers all part functions from Python files in this directory.
To add a new part, create a new ``.py`` file with a function that returns a
CadQuery ``Workplane``. The function name should match the file name
(e.g., ``box.py`` contains ``def box(...)``).

Usage:
    from models.parts import get_part_function, get_available_parts

    parts = get_available_parts()
    box_func = get_part_function('box')
    result = box_func(10, 20, 30)
"""

from typing import Callable, Dict, List, Optional

from models._registry import discover


_part_registry: Dict[str, Callable] = {}


def _discover_parts() -> None:
    global _part_registry
    _part_registry = discover(
        __file__, __name__, decorator_attr="_is_part", kind_label="part"
    )


def part(func: Callable) -> Callable:
    """Decorator to explicitly mark a function as a part."""
    func._is_part = True
    return func


def get_available_parts() -> List[str]:
    """Return a list of available part names."""
    if not _part_registry:
        _discover_parts()
    return sorted(_part_registry.keys())


def get_part_function(name: str) -> Optional[Callable]:
    """Get a part function by name."""
    if not _part_registry:
        _discover_parts()
    return _part_registry.get(name)


def get_all_parts() -> Dict[str, Callable]:
    """Return all part functions as a dictionary."""
    if not _part_registry:
        _discover_parts()
    return _part_registry.copy()


def reload_parts() -> None:
    """Force reload of all part modules."""
    _discover_parts()


# Auto-discover on import
_discover_parts()
