"""The self-test is the 'does this install actually work' command, so its parts are tested."""

import json
import os
import urllib.error
import urllib.request

import jev_ultrafast.task as task_module
from jev_ultrafast import selftest

LIVE_CHECK = "decisions came from the live endpoint, not the mock"


def _result(decided_by, page_text="2 places in Lisbon"):
    return {
        "instruction": "x",
        "plan": {},
        "status": "done",
        "error": None,
        "elapsed_ms": 1,
        "steps": 1,
        "budget": 12,
        "actions": [
            {
                "step": 1,
                "operation": "CLICK",
                "action": "Find stays",
                "kind": "click",
                "target": "2",
                "probability": 1.0,
                "confidence": 1.0,
                "decided_by": decided_by,
                "typed_text": None,
                "url": "http://x/",
            }
        ],
        "text_calls": [],
        "page": {"url": "http://x/", "title": "t", "text": page_text, "text_truncated": False},
    }


def _stub_run_task(monkeypatch, decided_by, captured=None):
    def fake_run_task(instruction, **options):
        if captured is not None:
            captured["backend"] = os.environ.get("JEV_BACKEND")
            captured["typesafe_url"] = os.environ.get("TYPESAFE_URL")
            captured["options"] = options
        return _result(decided_by)

    monkeypatch.setattr(task_module, "run_task", fake_run_task)


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - loopback only
        return response.status, response.read()


def test_mock_serves_the_fixture_page_and_health():
    port = selftest.start_mock()
    status, body = get(f"http://127.0.0.1:{port}/fixture.html?scenario=travel")
    assert status == 200 and b"Find stays" in body
    status, body = get(f"http://127.0.0.1:{port}/health")
    assert status == 200 and json.loads(body)["ok"] is True


def test_mock_rejects_unknown_paths():
    port = selftest.start_mock()
    try:
        get(f"http://127.0.0.1:{port}/nope")
        raise AssertionError("expected an HTTP error")
    except urllib.error.HTTPError as error:
        assert error.code == 404


def test_pick_always_sums_to_one():
    for ids in (["a"], ["a", "b"], ["a", "b", "c", "d"]):
        answer = selftest.pick(ids, ids[0])
        assert answer["choice"] == ids[0]
        assert set(answer["probabilities"]) == set(ids)
        assert abs(sum(answer["probabilities"].values()) - 1) < 1e-6
        assert answer["probabilities"][ids[0]] == max(answer["probabilities"].values())


def test_fallback_prefers_a_real_operation():
    assert selftest._fallback(["BLOCKED", "CLICK"]) == "CLICK"
    assert selftest._fallback(["WAIT"]) == "WAIT"


def _questions(**criteria):
    return {name: {"criteria": value} for name, value in criteria.items()}


def _run_decide(body):
    return selftest.decide(body)


def test_decide_types_an_empty_destination():
    body = {
        "state": {
            "page": {"text": "Somewhere you can exhale."},
            "elements": [
                {"index": "1", "label": "Destination", "value": "", "operations": ["TYPE_TEXT"]},
            ],
        },
        "questions": _questions(
            operation={"CLICK": {}, "TYPE_TEXT": {}, "DONE": {}, "BLOCKED": {}},
            type_text_target={"1": {"element": "[1] Destination"}},
            click_target={"2": {"element": "[2] Find stays"}},
        ),
    }
    answer = _run_decide(body)
    assert answer["answers"]["operation"]["choice"] == "TYPE_TEXT"
    assert answer["answers"]["type_text_target"]["choice"] == "1"


def test_decide_submits_once_the_field_is_filled():
    body = {
        "state": {
            "page": {"text": "Somewhere you can exhale."},
            "elements": [
                {"index": "1", "label": "Destination", "value": selftest.WANTED, "operations": ["TYPE_TEXT"]},
            ],
        },
        "questions": _questions(
            operation={"CLICK": {}, "TYPE_TEXT": {}, "DONE": {}, "BLOCKED": {}},
            type_text_target={"1": {"element": "[1] Destination"}},
            click_target={"2": {"element": "[2] Find stays"}},
        ),
    }
    answer = _run_decide(body)
    assert answer["answers"]["operation"]["choice"] == "CLICK"
    assert answer["answers"]["click_target"]["choice"] == "2"


def test_decide_stops_once_the_results_are_visible():
    body = {
        "state": {
            "page": {"text": "2 places in Lisbon"},
            "elements": [
                {"index": "1", "label": "Destination", "value": selftest.WANTED, "operations": ["TYPE_TEXT"]},
            ],
        },
        "questions": _questions(
            operation={"CLICK": {}, "DONE": {}, "BLOCKED": {}},
            click_target={"2": {"element": "[2] Find stays"}},
        ),
    }
    answer = _run_decide(body)
    assert answer["answers"]["operation"]["choice"] == "DONE"


def test_real_decision_keeps_the_configured_endpoint(monkeypatch):
    """It used to force JEV_BACKEND=classifier and delete TYPESAFE_*.

    That made the mode test a different endpoint than the rest of the tooling used, and it
    broke silently once classifier.dev stopped serving the free anonymous allowance.
    """
    captured = {}
    _stub_run_task(monkeypatch, "jev-1.13.0", captured)
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    monkeypatch.setenv("TYPESAFE_URL", "https://example.test/v1/systemone")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    checks, result = selftest.run(launch_browser=False, echo=lambda *_: None, real_decision=True)

    assert captured["backend"] == "typesafe"
    assert captured["typesafe_url"] == "https://example.test/v1/systemone"
    assert checks[LIVE_CHECK] is True
    assert result["status"] == "done"


def test_real_decision_rejects_decisions_that_came_from_the_mock(monkeypatch):
    """A run whose decisions are still the mock's must not be reported as a live pass."""
    _stub_run_task(monkeypatch, selftest.MOCK_MODEL)
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    monkeypatch.setenv("TYPESAFE_URL", "https://example.test/v1/systemone")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    checks, _result_ = selftest.run(launch_browser=False, echo=lambda *_: None, real_decision=True)

    assert checks[LIVE_CHECK] is False


def test_mock_mode_points_the_jev_endpoint_at_the_mock(monkeypatch):
    """The default mode must not depend on any real provider."""
    captured = {}
    _stub_run_task(monkeypatch, selftest.MOCK_MODEL, captured)
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    monkeypatch.setenv("TYPESAFE_URL", "https://example.test/v1/systemone")

    selftest.run(launch_browser=False, echo=lambda *_: None, real_decision=False)

    assert captured["backend"] == "typesafe"
    assert captured["typesafe_url"].startswith("http://127.0.0.1:")
    assert captured["options"]["screenshots"] is False
