"""The classifier backend speaks a different wire format, so it needs its own contract tests.

The fake below answers exactly the way classifier.dev does: {"results":[{"label","confidence",
"scores"}],"model":"jev-1.13.0"}. No network.
"""

import json

import pytest

from jev_ultrafast import model

CLASSIFIER_RESPONSE = {
    "tier": "fast",
    "model": "jev-1.13.0",
    "modelsUsed": ["jev-1.13.0"],
    "results": [],
    "usage": {"input_tokens": 100, "output_tokens": 5, "total_tokens": 105},
}


def page():
    """A local page with two fillable fields and one button.

    Two fill fields matter: a single candidate target is answered without a request, so a
    fixture with one field could not exercise the second classification call.
    """
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "From", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "fill", "label": "To", "role": "textbox", "value": "", "node": 11},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "e4", "kind": "click", "label": "Reset", "role": "button", "value": "", "node": 21},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    from jev_ultrafast.browser import fingerprint

    state["fingerprint"] = fingerprint(state)
    return state


class FakeClassifier:
    """Picks whatever the scripted plan says, and records every request.

    Labels now carry their own description, so a script entry may be either the full label
    or just its leading key, which mirrors what a real model may return.
    """

    def __init__(self, picks):
        self.picks = list(picks)
        self.requests = []

    def __call__(self, input_text, labels):
        self.requests.append({"input": input_text, "labels": labels})
        wanted = self.picks.pop(0) if self.picks else labels[0]
        chosen = next(
            (label for label in labels if label == wanted or label.split(" | ")[0].strip() == wanted),
            None,
        )
        assert chosen, f"test script picked {wanted!r}, not offered in {labels}"
        scores = {label: round(0.02, 4) for label in labels}
        scores[chosen] = round(1 - 0.02 * (len(labels) - 1), 4)
        response = json.loads(json.dumps(CLASSIFIER_RESPONSE))
        response["results"] = [{"label": chosen, "confidence": 0.9, "scores": scores, "ms": 12}]
        return chosen, scores, response


@pytest.fixture
def classifier(monkeypatch):
    monkeypatch.setenv("JEV_BACKEND", "classifier")

    def install(picks):
        fake = FakeClassifier(picks)
        monkeypatch.setattr(model, "classify", fake)
        return fake

    return install


def test_operation_and_target_are_two_classifier_requests(classifier):
    fake = classifier(["TYPE_TEXT", "2"])
    decision = model.choose(page(), "Find a book", [])
    assert decision["operation"] == "TYPE_TEXT" and decision["target"] == "2"
    assert decision["choice"] == "e2"
    assert len(fake.requests) == 2
    # Labels carry the element text, because a bare index means nothing to a classifier.
    assert any(label.startswith("CLICK |") for label in fake.requests[0]["labels"])
    assert [label.split(" | ")[0] for label in fake.requests[1]["labels"]] == ["1", "2"]
    assert "From" in fake.requests[1]["labels"][0]
    assert decision["request"]["calls"] == 2


def test_labels_carry_their_description_and_resolve_back_to_a_key():
    labels, lookup = model.make_labels([("1", '[1] textbox "From"'), ("2", '[2] textbox "To"')])
    assert labels[1] == '2 | [2] textbox "To"'
    assert model.resolve_label(labels[1], lookup) == "2"          # the full label
    assert model.resolve_label("2", lookup) == "2"                # a bare key
    assert model.resolve_label('2 | [2] textbox "To" ', lookup) == "2"
    assert model.resolve_label("1", lookup) == "1"


def test_identical_descriptions_still_produce_distinct_labels():
    """The API needs distinct labels, and a key prefix guarantees that."""
    labels, lookup = model.make_labels([("1", "same"), ("2", "same"), ("3", "other")])
    assert labels == ["1 | same", "2 | same", "3 | other"]
    assert len(set(labels)) == 3
    assert set(lookup) == set(labels)
    assert model.resolve_label("2 | same", lookup) == "2"


def test_a_label_outside_the_offered_set_is_rejected():
    _labels, lookup = model.make_labels([("1", "a"), ("2", "b")])
    with pytest.raises(RuntimeError, match="not one of the offered labels"):
        model.resolve_label("9", lookup)


def test_the_classifier_sees_the_goal_page_and_elements(classifier):
    fake = classifier(["CLICK", "4"])
    decision = model.choose(page(), "Open the search results", [{"action": "Reset", "kind": "click", "step": 1}])
    assert decision["choice"] == "e4"
    text = fake.requests[0]["input"]
    assert "Open the search results" in text
    assert "https://example.test/" in text
    assert "[1]" in text and "From" in text
    assert "1. click Reset" in text


def test_a_single_candidate_target_needs_no_second_request(classifier):
    """`too_few_labels` would reject a one-label request, and the answer is forced anyway."""
    state = page()
    state["actions"] = [a for a in state["actions"] if a["id"] in {"e1", "wait"}]
    fake = classifier(["TYPE_TEXT"])
    decision = model.choose(state, "Find a book", [])
    assert len(fake.requests) == 1
    assert decision["target"] == "1" and decision["choice"] == "e1"
    # The executor reads probabilities[choice], so it must be populated.
    assert decision["probabilities"] == {"e1": 1.0}
    assert decision["target_confidence"] == 1.0


def test_a_terminal_operation_needs_no_target_request(classifier):
    fake = classifier(["DONE"])
    decision = model.choose(page(), "Find a book", [])
    assert decision["operation"] == "DONE" and decision["choice"] == "DONE"
    assert len(fake.requests) == 1
    assert decision["probabilities"] == {"DONE": decision["confidence"]}
    assert decision["target"] is None


def test_control_operations_still_report_their_action_id(classifier):
    classifier(["WAIT"])
    decision = model.choose(page(), "Find a book", [])
    assert decision["operation"] == "WAIT" and decision["choice"] == "wait"


def test_probabilities_are_normalised_and_keyed_by_index(classifier):
    fake = classifier(["TYPE_TEXT", "1"])
    decision = model.choose(page(), "Find a book", [])
    assert len(fake.requests) == 2
    assert abs(sum(decision["operation_probabilities"].values()) - 1) < 1e-6
    assert decision["operation_probabilities"]["TYPE_TEXT"] == max(decision["operation_probabilities"].values())
    assert abs(sum(decision["target_probabilities"].values()) - 1) < 1e-6
    # Both backends report target probabilities keyed by element index.
    assert set(decision["target_probabilities"]) == {"1", "2"}
    assert decision["probabilities"]["e1"] == decision["target_probabilities"]["1"]


@pytest.mark.parametrize(
    "scores,ids,chosen,expected_sum",
    [
        ({"a": 0, "b": 0}, ["a", "b"], "a", 1.0),          # all-zero scores still work
        ({"a": 3, "b": 1}, ["a", "b"], "b", 1.0),          # API chosen label is forced to the top
        ({"a": 0.5, "b": 0.5, "c": 9}, ["a", "b"], "a", 1.0),  # unknown labels are dropped
    ],
)
def test_normalise_scores_always_yields_a_valid_distribution(scores, ids, chosen, expected_sum):
    values = model.normalise_scores(scores, ids, chosen)
    assert set(values) == set(ids)
    assert abs(sum(values.values()) - expected_sum) < 1e-6
    assert values[chosen] == max(values.values())


def test_a_label_outside_the_offered_menu_is_rejected(monkeypatch):
    """The real classify() guards the label before the loop can act on it."""
    monkeypatch.setattr(
        model,
        "post_json",
        lambda *a, **k: {"results": [{"label": "INVENTED", "scores": {"INVENTED": 1}}]},
    )
    with pytest.raises(RuntimeError, match="not one of the offered labels"):
        model.classify("text", ["a", "b"])


def test_an_operation_outside_the_menu_is_rejected(monkeypatch, classifier):
    def rogue(_input, labels):
        return "NOT_OFFERED", {}, {"model": "x", "results": [{"label": "NOT_OFFERED"}]}

    monkeypatch.setattr(model, "classify", rogue)
    with pytest.raises(RuntimeError, match="not one of the offered labels"):
        model.choose(page(), "Find a book", [])


def test_dispatch_follows_the_backend_setting(monkeypatch):
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    monkeypatch.setenv("TYPESAFE_API_KEY", "t")

    def fake_post(url, key, body, **_options):
        assert url.endswith("/v1/systemone")
        raise AssertionError("typesafe backend should be used")

    monkeypatch.setattr(model, "post_json", fake_post)
    with pytest.raises(AssertionError, match="typesafe backend"):
        model.choose(page(), "Find a book", [])


def test_input_budget_trims_the_page_text_not_the_question(monkeypatch, classifier):
    monkeypatch.setenv("CLASSIFIER_MAX_INPUT", "3000")
    state = page()
    state["text"] = "long page text " * 500
    fake = classifier(["DONE"])
    model.choose(state, "Find a book", [])
    text = fake.requests[0]["input"]
    assert len(text) <= 3000
    # The parts a decision cannot do without survive whole.
    assert "GOAL:" in text and "NUMBERED ELEMENTS" in text and "QUESTION" in text
    assert "- DONE |" in text and "- BLOCKED |" in text
    assert "long page text" in text


def test_classify_uses_a_direct_connection_and_parses_the_response(monkeypatch):
    captured = {}

    def fake_post(url, key, body, **options):
        captured.update({"url": url, "key": key, "body": body, "options": options})
        return {"model": "jev-1.13.0", "results": [{"label": "b", "confidence": 0.8, "scores": {"a": 0.2, "b": 0.8}}]}

    monkeypatch.setattr(model, "post_json", fake_post)
    label, scores, raw = model.classify("some text", ["a", "b"])
    assert label == "b" and scores == {"a": 0.2, "b": 0.8}
    assert captured["url"] == "https://classifier.dev/"
    assert captured["body"] == {"input": "some text", "labels": ["a", "b"]}
    # Anonymous traffic must not leave through a proxy: classifier.dev rejects that.
    assert captured["options"]["client"] is model.DIRECT_CLIENT
    assert captured["key"] == ""


def test_classify_sends_a_funded_key_and_tier_when_configured(monkeypatch):
    captured = {}

    def fake_post(url, key, body, **options):
        captured.update({"key": key, "body": body})
        return {"results": [{"label": "a", "scores": {"a": 1}}]}

    monkeypatch.setattr(model, "post_json", fake_post)
    monkeypatch.setenv("CLASSIFIER_API_KEY", "funded")
    monkeypatch.setenv("CLASSIFIER_TIER", "smart")
    model.classify("t", ["a", "b"])
    assert captured["key"] == "funded"
    assert captured["body"]["tier"] == "smart"


def test_classify_reports_an_api_error_clearly(monkeypatch):
    monkeypatch.setattr(
        model,
        "post_json",
        lambda *a, **k: {"error": "Provide at least 2 labels", "code": "too_few_labels"},
    )
    with pytest.raises(RuntimeError, match="Classifier returned no usable result"):
        model.classify("t", ["only-one"])
