"""Preflight must turn a broken environment into a list of fixes, not a slow failure."""

import pytest

from jev_ultrafast import chrome, config, task

# Captured at import time, before any autouse fixture replaces it.
REAL_PREFLIGHT = config.preflight


@pytest.fixture
def real_preflight(monkeypatch):
    """Undo the suite-wide stub so the genuine check runs."""
    monkeypatch.setattr(config, "preflight", REAL_PREFLIGHT)
    yield


def test_preflight_names_every_missing_piece(real_preflight, monkeypatch):
    monkeypatch.setattr(chrome, "probe", lambda *a, **k: (False, "nothing is listening on http://127.0.0.1:9333"))
    checks = config.preflight()
    by_name = {check["check"]: check for check in checks}
    assert set(by_name) == {"jev endpoint", "text model endpoint", "browser (CDP)"}
    for name, check in by_name.items():
        assert check["ok"] is False, name
        assert check["fix"], name
    assert "TYPESAFE_API_KEY" in by_name["jev endpoint"]["detail"]
    assert "jev-browser start" in by_name["browser (CDP)"]["fix"]


def test_preflight_passes_when_keys_and_browser_are_present(real_preflight, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "t")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "x")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setattr(chrome, "probe", lambda *a, **k: (True, "Chrome/144 at http://127.0.0.1:9333"))
    checks = config.preflight()
    assert all(check["ok"] for check in checks), checks


def test_preflight_accepts_a_keyless_local_gateway(real_preflight, monkeypatch):
    monkeypatch.setenv("TYPESAFE_ALLOW_NO_KEY", "1")
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "ollama")
    monkeypatch.setattr(chrome, "probe", lambda *a, **k: (True, "stub"))
    checks = config.preflight()
    assert all(check["ok"] for check in checks), checks


def test_run_task_stops_before_the_browser_when_not_ready(monkeypatch, real_preflight):
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "ollama")
    monkeypatch.setattr(chrome, "probe", lambda *a, **k: (False, "nothing listening"))

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("run_task must not construct an Agent when preflight fails")

    monkeypatch.setattr(task, "Agent", must_not_run)
    result = task.run_task("百度搜索 上海天气")

    assert result["status"] == "setup-required"
    assert result["steps"] == 0 and result["actions"] == []
    assert {check["check"] for check in result["checks"]} == {"jev endpoint", "browser (CDP)"}
    assert all(check["fix"] for check in result["checks"])
    # The sentence is still parsed, so the user can see what would have run.
    assert result["plan"]["engine"] == "baidu"


def test_run_task_can_skip_preflight(monkeypatch):
    calls = {}

    class FakeAgent:
        def __init__(self, url, goal, **_kwargs):
            calls["url"] = url

        def run(self):
            return iter(())

        def snapshot(self):
            return {
                "page": {"url": "x", "title": "t", "text": ""},
                "status": "done",
                "history": [],
                "text_calls": [],
                "elapsed_ms": 1,
            }

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(task, "Agent", FakeAgent)
    result = task.run_task("百度搜索 上海天气", preflight=False)
    assert result["status"] == "done" and calls["closed"] is True
