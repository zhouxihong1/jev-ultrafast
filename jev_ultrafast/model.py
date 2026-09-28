"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values.

Two decision wire formats are supported, selected by JEV_BACKEND:

  typesafe    POST {base}/v1/systemone with {model, state, questions} - one request
              returns the operation head and every target head together.
  classifier  POST https://classifier.dev/ with {input, labels} - the same model
              (jev-1.13.0, provider typesafe) behind a plain classification facade.
              It takes one string and returns one label, so the operation and its target
              become two requests, and a single-candidate target needs no request at all.

Every host, path, model name, header, and timeout comes from .config.
"""

import json
import math
import os
import time

import httpx

from . import config
from .questions import NEXT_ACTION, TARGET, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=25)
# classifier.dev answers "Anonymous proxy traffic requires a funded API key" when a request
# arrives through a proxy, so that endpoint gets a client that ignores proxy environment
# variables unless CLASSIFIER_USE_ENV_PROXY is set.
DIRECT_CLIENT = httpx.Client(http2=True, timeout=25, trust_env=False)


def post_json(url, key, body, *, headers=None, timeout=None, client=None):
    sent = {"Authorization": f"Bearer {key}"} if key else {}
    sent.update(headers or {})
    sender = client or CLIENT
    for attempt in range(3):
        try:
            response = sender.post(url, json=body, headers=sent, timeout=timeout or 25)
        except httpx.HTTPError:
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in {429, 529, 503} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue
        if response.is_error:
            raise RuntimeError(
                f"Model provider returned HTTP {response.status_code} from {url}; no action executed."
            )
        return response.json()
    raise RuntimeError("Model unavailable")


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT", "enter": "ENTER"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def operation_menu(state, goal, history):
    """The shared view of what can be done: elements, per-operation targets, controls."""
    elements, targets, controls = action_space(state["actions"])
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
        "ENTER": (
            "Press Enter in an editable field to submit its form or confirm the value. "
            "Use this when a populated field has no visible submit control."
        ),
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    return elements, targets, controls, operations


def choose(state, goal, history):
    """Dispatch to whichever decision backend is configured."""
    if config.backend() == "classifier":
        return choose_classifier(state, goal, history)
    return choose_typesafe(state, goal, history)


def choose_typesafe(state, goal, history):
    elements, targets, controls, operations = operation_menu(state, goal, history)
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    body = {
        "model": config.typesafe_model(),
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": elements,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    endpoint = config.typesafe_url()
    started = time.perf_counter()
    result = post_json(
        endpoint,
        config.typesafe_key(),
        body,
        headers=config.typesafe_headers(),
        timeout=config.typesafe_timeout(),
    )
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target_answer = validate_choice(result["answers"].get(operation.lower() + "_target", {}), targets[operation])
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }


def normalise_scores(scores, ids, chosen):
    """Force a classifier's scores into the peaked, summing-to-one map the loop checks."""
    values = {key: max(0.0, float(scores.get(key, 0) or 0)) for key in ids}
    total = sum(values.values())
    if total <= 0:
        values = {key: 0.0 for key in ids}
        values[chosen] = 1.0
        total = 1.0
    values = {key: value / total for key, value in values.items()}
    # The API returns its own choice; make sure that label really is the argmax we report.
    top = max(values.values())
    if values[chosen] < top:
        values[chosen] = top
        total = sum(values.values())
        values = {key: value / total for key, value in values.items()}
    return values


def classify(input_text, labels):
    """One classifier.dev call. Returns (label, scores, raw response)."""
    body = {"input": input_text, "labels": labels}
    if tier := config.classifier_tier():
        body["tier"] = tier
    headers = {}
    if key := config.classifier_key():
        headers["Authorization"] = f"Bearer {key}"
    result = post_json(
        config.classifier_url(),
        key or "",
        body,
        headers=headers,
        timeout=config.classifier_timeout(),
        client=None if config.classifier_trust_env_proxy() else DIRECT_CLIENT,
    )
    if os.environ.get("JEV_DEBUG_CLASSIFIER"):
        print(json.dumps({"labels": labels, "input_chars": len(input_text), "response": result})[:2000])
    try:
        first = result["results"][0]
        label = str(first["label"])
        scores = {str(k): v for k, v in (first.get("scores") or {}).items()}
        if not scores:
            scores = {label: first.get("confidence", 1.0)}
    except (KeyError, IndexError, TypeError):
        error = result.get("error") or result.get("code") or result
        raise RuntimeError(f"Classifier returned no usable result: {error}") from None
    if label not in labels:
        raise RuntimeError(f"Classifier chose {label!r}, which is not one of the offered labels.")
    return label, scores, result


LABEL_SEPARATOR = " | "


def make_labels(options):
    """Build classifier labels that carry their own meaning, plus the reverse lookup.

    A bare index like "3" tells a classifier nothing: it has to map label-space back to a
    line of the input, and in practice it guesses. The native TypeSafe protocol avoids this
    by keying criteria to structured descriptions. Here the description rides inside the
    label instead, and the leading token before the separator maps back.

    The key prefix also keeps the labels distinct, which the API requires.
    """
    labels, lookup = [], {}
    for key, description in options:
        label = f"{key}{LABEL_SEPARATOR}{description}"[:160]
        labels.append(label)
        lookup[label] = key
    return labels, lookup


def resolve_label(returned, lookup):
    """Accept the full label or just its leading key, and reject anything else."""
    if returned in lookup:
        return lookup[returned]
    head = returned.split(LABEL_SEPARATOR)[0].strip()
    for label, key in lookup.items():
        if label.split(LABEL_SEPARATOR)[0].strip() == head:
            return key
    raise RuntimeError(f"Classifier chose {returned!r}, which is not one of the offered labels.")


def describe_element(index, element):
    value = element.get("value", "")
    state = ", ".join(f"{k}={element[k]}" for k in ("checked", "selected", "expanded") if k in element)
    described = f'[{index}] {element.get("role", "element")} "{element["label"]}"'
    if value:
        described += f" value={value!r}"
    return described + (f" ({state})" if state else "")


def element_lines(elements):
    lines = []
    for element in elements:
        lines.append(describe_element(element["index"], element))
        for option in element.get("options", []):
            lines.append(f"    option {option['index']}: {option['label']}")
    return lines


PAGE_PLACEHOLDER = "%%PAGE_TEXT%%"


def classifier_input(state, goal, history, elements, question, max_chars):
    """Compose the single string a classifier can read: rules, goal, page, elements, question.

    The page text absorbs whatever is left of the budget once the parts that must survive
    whole - the rules, the element table, the question - have been written. Measuring a
    placeholder instead of the real text makes the trim exact.
    """
    parts = [
        NEXT_ACTION,
        "",
        "GOAL:",
        goal,
        "",
        "CURRENT PAGE",
        f"url: {state['url']}",
        f"title: {state['title']}",
        "",
        "visible text:",
        PAGE_PLACEHOLDER,
        "",
        "NUMBERED ELEMENTS",
        *element_lines(elements),
        "",
        "RECENT ACTIONS",
        *[
            f"{h.get('step', '?')}. {h.get('operation') or h.get('kind')} {h.get('action')}"
            + (f" typed {h['text']!r}" if h.get("text") else "")
            for h in history[-8:]
        ],
        "",
        "QUESTION",
        *question,
    ]
    skeleton = "\n".join(parts)
    room = max(0, max_chars - len(skeleton) + len(PAGE_PLACEHOLDER))
    return skeleton.replace(PAGE_PLACEHOLDER, (state.get("text") or "")[:room])


def choose_classifier(state, goal, history):
    """Two classification requests: which operation, then which element it acts on."""
    elements, targets, controls, operations = operation_menu(state, goal, history)
    max_chars = config.classifier_max_input()
    started = time.perf_counter()
    calls = []

    operation_labels, operation_lookup = make_labels([(key, operations[key]) for key in sorted(operations)])
    question = [
        "Which single operation advances the goal on the CURRENT page?",
        "Answer with exactly one of these labels:",
        *[f"- {label}" for label in operation_labels],
    ]
    label, scores, raw = classify(
        classifier_input(state, goal, history, elements, question, max_chars), operation_labels
    )
    calls.append(raw)
    operation = resolve_label(label, operation_lookup)
    if operation not in operations:
        raise RuntimeError(f"Classifier chose an unknown operation {operation!r}.")
    # Re-key to operation names so this matches what the typesafe backend reports.
    by_label = normalise_scores(scores, operation_labels, label)
    operation_probabilities = {operation_lookup[text]: value for text, value in by_label.items()}
    confidence = operation_probabilities[operation]

    target, target_probabilities, target_confidence = None, {}, None
    if operation in targets:
        candidates = targets[operation]
        order = sorted(candidates, key=lambda index: int(index.split(":")[0]))
        if len(candidates) == 1:
            # One candidate is not a question, and the API needs at least two labels.
            target = order[0]
            target_probabilities = {target: 1.0}
            target_confidence = 1.0
        else:
            target_labels, target_lookup = make_labels(
                [(index, describe_element(index.split(":")[0], candidates[index])) for index in order]
            )
            question = [
                f"The next operation is {operation}: {operations[operation]}",
                "Which element should it act on? Answer with exactly one of these labels:",
                *[f"- {label}" for label in target_labels],
            ]
            label, scores, raw = classify(
                classifier_input(state, goal, history, elements, question, max_chars), target_labels
            )
            calls.append(raw)
            target = resolve_label(label, target_lookup)
            # Re-key to indices so this matches what the typesafe backend reports.
            by_label = normalise_scores(scores, target_labels, label)
            target_probabilities = {target_lookup[text]: value for text, value in by_label.items()}
            target_confidence = target_probabilities[target]
        choice = candidates[target]["id"]
        probabilities = {a["id"]: target_probabilities.get(index, 0.0) for index, a in candidates.items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities = {choice: confidence}

    last = calls[-1]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": confidence,
        "probabilities": probabilities,
        "operation_probabilities": operation_probabilities,
        "target_probabilities": target_probabilities,
        "target_confidence": target_confidence,
        "raw_answers": {f"call_{i + 1}": call.get("results") for i, call in enumerate(calls)},
        "model": last.get("model", "classifier"),
        "usage": last.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": {"backend": "classifier", "url": config.classifier_url(), "calls": len(calls)},
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def field_text(context):
    if not config.env("TEXT_MODEL_API_KEY") and not config.text_key_optional():
        raise ValueError(
            "TYPE_TEXT needs TEXT_MODEL_API_KEY; no text is hardcoded or guessed by the executor."
        )
    endpoint, model = config.text_url(), config.text_model()
    body = {
        "model": model,
        "max_tokens": config.text_max_tokens(),
        **config.text_reasoning(),
        **({"response_format": {"type": "json_object"}} if config.text_json_mode() else {}),
        **({"temperature": config.text_temperature()} if config.text_temperature() is not None else {}),
        "messages": [
            {"role": "system", "content": TEXT_VALUE},
            {
                "role": "user",
                "content": json.dumps(context),
            },
        ],
    }
    started = time.perf_counter()
    result = post_json(
        endpoint,
        config.text_key(),
        body,
        headers=config.text_headers(),
        timeout=config.text_timeout(),
    )
    try:
        output = json.loads(result["choices"][0]["message"]["content"])
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError, IndexError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, {
        "model": model,
        "endpoint": endpoint,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
    }
