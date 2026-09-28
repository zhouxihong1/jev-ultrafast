"""ENTER exists because many forms have no visible submit control.

Bing's submit button is a 0x0 hidden input and its visible affordance is a bare <label>, so
before this operation the agent could type into a search box and then have nothing to click.
"""

from unittest.mock import Mock

import pytest

from jev_ultrafast import model
from jev_ultrafast.browser import browser_operation


def field(**overrides):
    action = {
        "id": "e1",
        "kind": "enter",
        "label": "输入搜索词",
        "role": "searchbox",
        "value": "上海天气",
        "node": 7,
    }
    action.update(overrides)
    return action


def page_with_enter():
    state = {
        "url": "https://cn.bing.com/",
        "title": "搜索 - Microsoft 必应",
        "text": "搜索",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "输入搜索词", "role": "searchbox", "value": "", "node": 7},
            {"id": "e2", "kind": "click", "label": "Open 输入搜索词", "role": "searchbox", "value": "", "node": 7},
            {"id": "e3", "kind": "enter", "label": "输入搜索词", "role": "searchbox", "value": "", "node": 7},
            {"id": "e4", "kind": "click", "label": "反馈", "role": "button", "value": "", "node": 30},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    from jev_ultrafast.browser import fingerprint

    state["fingerprint"] = fingerprint(state)
    return state


def test_enter_is_a_third_operation_on_the_same_element():
    elements, targets, controls = model.action_space(page_with_enter()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK", "ENTER"]
    assert targets["ENTER"]["1"]["id"] == "e3"
    # Enter acts on one observed field, so it is a targeted operation, not a bare control.
    assert "ENTER" not in controls
    assert "WAIT" in controls


def test_enter_targets_stay_inside_the_field_that_offers_them():
    _elements, targets, _controls = model.action_space(page_with_enter()["actions"])
    assert set(targets["ENTER"]) == {"1"}          # only the search box
    assert set(targets["CLICK"]) == {"1", "2"}     # the box and the footer button


def test_both_backends_can_choose_enter(monkeypatch):
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    monkeypatch.setenv("TYPESAFE_API_KEY", "t")

    def post(_url, _key, body, **_options):
        criteria = body["questions"]["operation"]["criteria"]
        assert "ENTER" in criteria
        probabilities = {key: 0.0 for key in criteria}
        probabilities["ENTER"] = 1.0
        return {
            "model": "test",
            "answers": {
                "operation": {"choice": "ENTER", "confidence": 1.0, "probabilities": probabilities},
                "enter_target": {"choice": "1", "confidence": 1.0, "probabilities": {"1": 1.0}},
            },
        }

    monkeypatch.setattr(model, "post_json", post)
    decision = model.choose(page_with_enter(), "搜索 上海天气", [])
    assert decision["operation"] == "ENTER" and decision["choice"] == "e3"


def test_classifier_labels_explain_enter(monkeypatch):
    monkeypatch.setenv("JEV_BACKEND", "classifier")
    seen = {}

    def fake(input_text, labels):
        seen.setdefault("labels", list(labels))
        chosen = next(label for label in labels if label.startswith("ENTER"))
        return chosen, {label: 1.0 if label == chosen else 0.0 for label in labels}, {"model": "jev-1.13.0"}

    monkeypatch.setattr(model, "classify", fake)
    decision = model.choose(page_with_enter(), "搜索 上海天气", [])
    assert any(label.startswith("ENTER | Press Enter") for label in seen["labels"])
    assert decision["operation"] == "ENTER"


def test_executor_sends_a_real_enter_key_sequence(monkeypatch):
    import jev_ultrafast.browser as browser

    calls = []

    def cdp(method, **params):
        if method == "Runtime.evaluate":
            return {"result": {"value": True}}
        calls.append((method, params))
        return {}

    monkeypatch.setattr(browser, "cdp", cdp)
    result = browser_operation({"operation": "act", "session": "s", "action": field(), "text": None})
    assert result == {"executed": "e1"}
    key_events = [params for method, params in calls if method == "Input.dispatchKeyEvent"]
    assert [event["type"] for event in key_events] == ["rawKeyDown", "char", "keyUp"]
    assert all(event["key"] == "Enter" and event["windowsVirtualKeyCode"] == 13 for event in key_events)
    assert key_events[1]["text"] == "\r"
    # Enter must not be preceded by a synthetic mouse click on the field.
    assert not [params for method, params in calls if method == "Input.dispatchMouseEvent"]


def test_executor_refuses_when_the_field_cannot_take_focus(monkeypatch):
    import jev_ultrafast.browser as browser

    calls = []
    monkeypatch.setattr(browser, "cdp", lambda method, **params: (
        calls.append(method) or {"result": {"value": None}}
    ))
    with pytest.raises(browser.StalePage, match="cannot take focus"):
        browser_operation({"operation": "act", "session": "s", "action": field(), "text": None})
    assert "Input.dispatchKeyEvent" not in calls


def test_executor_rejects_a_non_node_target():
    with pytest.raises(ValueError, match="Invalid observed node"):
        browser_operation({"operation": "act", "session": "s", "action": field(node="7"), "text": None})


def test_enter_uses_node_scoped_freshness(monkeypatch):
    """A stale Enter must not submit a field whose contents changed since the decision."""
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.evaluate = Mock(return_value=["page-key", ["guard"]])
    page = {"page_key": "page-key", "guards": {"7": ["guard"]}, "marker": "marker"}
    assert b.fresh(page, field()) is True
    b.evaluate = Mock(return_value=["other-key", ["guard"]])
    assert b.fresh(page, field()) is False


def test_a_failed_screenshot_never_fails_the_run(monkeypatch):
    """The picture is for the inspector; the decision comes from the element table."""
    import jev_ultrafast.browser as browser

    page_state = {"url": "u", "title": "t", "text": "x", "actions": [], "scroll": {"y": 0}}

    def cdp(method, **params):
        if method == "Runtime.evaluate":
            return {"result": {"value": page_state}}
        if method == "Page.captureScreenshot":
            raise RuntimeError("Page.captureScreenshot timed out after 5s waiting for the daemon")
        return {}

    monkeypatch.setattr(browser, "cdp", cdp)
    info = browser.browser_operation({"operation": "observe", "session": "s", "screenshot": True})
    assert info["actions"] == page_state["actions"]
    assert "screenshot" not in info


def test_a_transient_screenshot_failure_is_retried(monkeypatch):
    import jev_ultrafast.browser as browser

    page_state = {"url": "u", "title": "t", "text": "x", "actions": [], "scroll": {"y": 0}}
    attempts = []

    def cdp(method, **params):
        if method == "Runtime.evaluate":
            return {"result": {"value": page_state}}
        if method == "Page.captureScreenshot":
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("busy")
            return {"data": "QUJD"}
        return {}

    monkeypatch.setattr(browser, "cdp", cdp)
    info = browser.browser_operation({"operation": "observe", "session": "s", "screenshot": True})
    assert len(attempts) == 2 and info["screenshot"] == "QUJD"
