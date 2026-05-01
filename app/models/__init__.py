"""models — parametric parts and assemblies.

Subpackages:
    parts       — parametric parts (callables returning ``cq.Workplane``)
    assemblies  — parametric assemblies (callables returning ``cq.Assembly``)
    common      — shared helpers (empty for now; populated as patterns emerge)

This top-level package is a namespace only. Discovery happens lazily inside
each subpackage when it is first imported, so importing ``models`` alone has
no side effects.
"""
