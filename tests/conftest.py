"""Keep the offline suite deterministic: no ambient Jev configuration leaks in."""

import pytest

PREFIXES = ("JEV_", "BU_", "TYPESAFE_", "TEXT_MODEL_", "BROWSER_HARNESS_")


@pytest.fixture(autouse=True)
def clean_jev_environment(monkeypatch):
    import os

    for name in list(os.environ):
        if name.startswith(PREFIXES):
            monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def hermetic_state(monkeypatch):
    """No browser state file, and no real CDP probe, unless a test asks for one."""
    from jev_ultrafast import chrome

    monkeypatch.setattr(chrome, "read_state", lambda: {})
    monkeypatch.setattr(chrome, "write_state", lambda _data: None)
    yield


@pytest.fixture(autouse=True)
def ready_preflight(monkeypatch):
    """The suite tests behaviour, not this machine's readiness. Override to test the check itself."""
    from jev_ultrafast import config

    monkeypatch.setattr(config, "preflight", lambda *a, **k: [])
    yield
