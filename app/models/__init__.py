"""
models - CadQuery model functions module

This module auto-discovers all model functions from Python files in this directory.
To add a new model, simply create a new .py file with a function that returns a CadQuery object.

The function name becomes the model name. Each file should contain one primary function
with the same name as the file (e.g., box.py contains def box(...)).

Usage:
    from models import get_model_function, get_available_models

    # List available models
    models = get_available_models()

    # Get a specific model function
    box_func = get_model_function('box')
    result = box_func(10, 20, 30)
"""

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Callable, Dict, List, Optional


# Registry of model functions
_model_registry: Dict[str, Callable] = {}


def _discover_models():
    """Auto-discover all model functions from Python files in this directory."""
    global _model_registry
    _model_registry.clear()

    package_dir = Path(__file__).parent

    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name.startswith('_'):
            continue  # Skip private modules

        try:
            module = importlib.import_module(f'.{module_info.name}', package=__name__)

            # Look for a function with the same name as the module
            if hasattr(module, module_info.name):
                func = getattr(module, module_info.name)
                if callable(func):
                    _model_registry[module_info.name] = func

            # Also check for any function marked with @model decorator
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if hasattr(obj, '_is_model') and obj._is_model:
                    _model_registry[name] = obj

        except Exception as e:
            print(f"Warning: Failed to load model module '{module_info.name}': {e}")


def model(func: Callable) -> Callable:
    """Decorator to explicitly mark a function as a model."""
    func._is_model = True
    return func


def get_available_models() -> List[str]:
    """Return a list of available model names."""
    if not _model_registry:
        _discover_models()
    return sorted(_model_registry.keys())


def get_model_function(name: str) -> Optional[Callable]:
    """Get a model function by name."""
    if not _model_registry:
        _discover_models()
    return _model_registry.get(name)


def get_all_models() -> Dict[str, Callable]:
    """Return all model functions as a dictionary."""
    if not _model_registry:
        _discover_models()
    return _model_registry.copy()


def reload_models():
    """Force reload of all model modules."""
    _discover_models()


# Auto-discover on import
_discover_models()
