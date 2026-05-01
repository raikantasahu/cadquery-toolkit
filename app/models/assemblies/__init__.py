"""assemblies — parametric assembly functions.

Auto-discovers all assembly functions from Python files in this directory.
To add a new assembly, create a new ``.py`` file with a function that
returns a CadQuery ``Assembly``. The function name should match the file
name (e.g., ``bolted_joint.py`` contains ``def bolted_joint(...)``).

Static YAML assemblies in this directory are not part of this registry;
they are loaded separately via ``app/assembly.py:load_assembly``.

Usage:
    from models.assemblies import get_assembly_function, get_available_assemblies

    names = get_available_assemblies()
    func = get_assembly_function('bolted_joint')
    assy = func(plate_thickness=8)
"""

from typing import Callable, Dict, List, Optional

from models._registry import discover


_assembly_registry: Dict[str, Callable] = {}


def _discover_assemblies() -> None:
    global _assembly_registry
    _assembly_registry = discover(
        __file__,
        __name__,
        decorator_attr="_is_assembly",
        kind_label="assembly",
    )


def assembly(func: Callable) -> Callable:
    """Decorator to explicitly mark a function as an assembly."""
    func._is_assembly = True
    return func


def get_available_assemblies() -> List[str]:
    """Return a list of available assembly names."""
    if not _assembly_registry:
        _discover_assemblies()
    return sorted(_assembly_registry.keys())


def get_assembly_function(name: str) -> Optional[Callable]:
    """Get an assembly function by name."""
    if not _assembly_registry:
        _discover_assemblies()
    return _assembly_registry.get(name)


def get_all_assemblies() -> Dict[str, Callable]:
    """Return all assembly functions as a dictionary."""
    if not _assembly_registry:
        _discover_assemblies()
    return _assembly_registry.copy()


def reload_assemblies() -> None:
    """Force reload of all assembly modules."""
    _discover_assemblies()


# Auto-discover on import
_discover_assemblies()
