"""Shared discovery helper for the parts and assemblies registries.

Auto-discovers callables from Python files in a package directory:

  * A function whose name matches the file name (e.g. ``box.py`` contains
    ``def box(...)``) is registered under that name.
  * A function decorated to set a marker attribute (e.g. ``@part`` sets
    ``_is_part = True``) is also registered, even if its name does not
    match the file. The marker attribute name is passed via
    ``decorator_attr``.

The helper returns a fresh dictionary; it does not mutate any global
state. Callers own the registry they assign to.
"""

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


def discover(
    package_file: str,
    package_name: str,
    decorator_attr: Optional[str] = None,
    kind_label: str = "module",
) -> Dict[str, Callable]:
    """Discover callables in the directory containing ``package_file``.

    Parameters
    ----------
    package_file
        The ``__file__`` attribute of the calling package's
        ``__init__.py``. The directory to scan is derived from this.
    package_name
        The ``__name__`` attribute of the calling package; used as the
        anchor for relative imports of the discovered modules.
    decorator_attr
        Optional attribute name marking a function for registration
        (e.g. ``"_is_part"``). When set, any function in any scanned
        module having this attribute set to a truthy value is registered
        under its own ``__name__``, in addition to the file-name
        convention.
    kind_label
        Word used in warning messages when a module fails to import
        (e.g. ``"part"``, ``"assembly"``).

    Returns
    -------
    Dict[str, Callable]
        A fresh dict mapping registered names to callables.
    """
    package_dir = Path(package_file).parent
    registry: Dict[str, Callable] = {}

    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name.startswith("_"):
            continue  # Skip private modules

        try:
            module = importlib.import_module(
                f".{module_info.name}", package=package_name
            )

            # File-name convention: register a function whose name matches
            # the module name.
            if hasattr(module, module_info.name):
                func = getattr(module, module_info.name)
                if callable(func):
                    registry[module_info.name] = func

            # Decorator opt-in: register any function flagged via the
            # decorator marker attribute.
            if decorator_attr:
                for name, obj in inspect.getmembers(module, inspect.isfunction):
                    if getattr(obj, decorator_attr, False):
                        registry[name] = obj

        except Exception:
            # A broken model module would otherwise vanish silently from the
            # GUI dropdown / CLI registry. Log it loudly, naming the module,
            # with the traceback so the author can fix it.
            logger.warning(
                "Failed to load %s module '%s' — it will be missing from the "
                "registry.", kind_label, module_info.name, exc_info=True)

    return registry
