"""The self-test is the 'does this install actually work' command, so its parts are tested."""

import json
import urllib.error
import urllib.request

from jev_ultrafast import selftest


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
