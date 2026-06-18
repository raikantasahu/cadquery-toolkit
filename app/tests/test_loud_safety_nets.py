"""Tier 3 — silent failures are now loud (loud-safety-net pass).

A broken model module used to vanish from the registry with only a print(); it
must now log loudly (naming the module) and the other models must still load
(graceful degradation, not a silent disappearance).
"""
import logging

import models._registry as reg
import models.parts


def test_registry_logs_loudly_on_module_failure(monkeypatch, caplog):
    real = reg.importlib.import_module

    def fake(name, package=None):
        if name == ".box":          # simulate one broken model module
            raise RuntimeError("boom")
        return real(name, package=package)

    monkeypatch.setattr(reg.importlib, "import_module", fake)
    with caplog.at_level(logging.WARNING):
        registry = reg.discover(
            models.parts.__file__, "models.parts",
            decorator_attr="_is_part", kind_label="part")

    assert "box" not in registry          # the broken module is excluded
    assert registry                       # ...but the rest still load
    assert any("box" in r.getMessage() and "Failed to load" in r.getMessage()
               for r in caplog.records), \
        [r.getMessage() for r in caplog.records]
