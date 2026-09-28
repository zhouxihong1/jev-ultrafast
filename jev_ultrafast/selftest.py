"""Prove the whole stack works, with no credentials and no external website.

Starts three things on loopback:

  * a local page          ``/fixture.html``
  * a mock Jev endpoint   ``/v1/systemone``
  * a mock text endpoint  ``/mock/chat/completions``

then points ``TYPESAFE_URL`` and ``TEXT_MODEL_URL`` at them and drives a real browser
through type -> submit -> done. Because the endpoints are supplied purely by environment
variables, a passing run proves the override took effect rather than being ignored.

    jev-selftest              # starts a dedicated browser if none is reachable
    jev-selftest --headless
    jev-selftest --no-launch  # require a browser that is already running
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).parent / "static" / "fixture.html"
WANTED = "Lisbon"
SEEN = {"typesafe": [], "text_model": []}


class MockHandler(BaseHTTPRequestHandler):
    """Just enough of both protocols to drive one real browser run."""

    def log_message(self, *_args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/fixture.html"):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/health"):
            self._json({"ok": True, "requests": {k: len(v) for k, v in SEEN.items()}})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        path = self.path.split("?")[0]

        if path.endswith("/systemone"):
            SEEN["typesafe"].append(
                {
                    "url": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "trace": self.headers.get("X-Trace"),
                    "model": body.get("model"),
                }
            )
            return self._json(self.decide(body))

        if path.endswith("/chat/completions"):
            SEEN["text_model"].append(
                {
                    "url": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "trace": self.headers.get("X-Trace"),
                    "model": body.get("model"),
                    "reasoning_off": "reasoning" in body or "thinking" in body,
                    "json_mode": body.get("response_format"),
                }
            )
            return self._json(
                {
                    "model": body.get("model"),
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    "choices": [{"message": {"content": json.dumps({"text": WANTED})}}],
                }
            )

        self._json({"error": "not found"}, 404)

    def decide(self, body):
        return decide(body)


def decide(body):
    """A tiny deterministic policy: type the destination, submit, then stop.

    Kept as a module function so its three branches can be tested without a server.
    """
    elements = body["state"]["elements"]
    page_text = body["state"]["page"]["text"]
    questions = body["questions"]
    operation_ids = list(questions["operation"]["criteria"])
    targets = {name: list(q["criteria"]) for name, q in questions.items() if name != "operation"}

    def index_of(label_part, question):
        for index, criteria in questions[question]["criteria"].items():
            if label_part.lower() in json.dumps(criteria).lower():
                return index
        return None

    destination = next((item for item in elements if "destination" in str(item.get("label", "")).lower()), None)
    submit = index_of("Find stays", "click_target") if "click_target" in questions else None

    choice, target_question, target_index = "DONE", None, None
    if (
        destination
        and destination.get("value") != WANTED
        and "TYPE_TEXT" in destination.get("operations", [])
        and "type_text_target" in questions
        and destination.get("index") in questions["type_text_target"]["criteria"]
    ):
        choice = "TYPE_TEXT"
        target_question, target_index = "type_text_target", destination["index"]
    elif submit and "places in" not in page_text and "CLICK" in operation_ids:
        choice, target_question, target_index = "CLICK", "click_target", submit

    answers = {"operation": pick(operation_ids, choice if choice in operation_ids else _fallback(operation_ids))}
    for name, ids in targets.items():
        chosen = target_index if name == target_question and target_index in ids else ids[0]
        answers[name] = pick(ids, chosen)
    return {"model": "mock-jev", "answers": answers, "usage": {"total_tokens": 0}}


def _fallback(ids):
    for preferred in ("CLICK", "TYPE_TEXT", "DONE", "BLOCKED"):
        if preferred in ids:
            return preferred
    return ids[0]


def pick(ids, chosen):
    """A peaked distribution over the offered ids, as the API contract requires."""
    if len(ids) == 1:
        return {"choice": ids[0], "confidence": 0.9, "probabilities": {ids[0]: 1.0}}
    share = round(0.1 / (len(ids) - 1), 6)
    probabilities = {i: (0.9 if i == chosen else share) for i in ids}
    probabilities[chosen] = round(1 - share * (len(ids) - 1), 6)
    return {"choice": chosen, "confidence": 0.9, "probabilities": probabilities}


def start_mock(port=0):
    """Serve the mock on 127.0.0.1:<port> (0 picks a free port). Returns the port."""
    server = ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def run(launch_browser=True, headless=False, keep_open=False, echo=print, real_decision=False):
    """Point the endpoints at the mock and drive one real run. Returns (checks, result).

    real_decision=True replaces the mock Jev endpoint with the live classifier.dev model while
    keeping the local page and the stub text helper. That is how to tell which half of the
    stack is actually at fault when a real provider misbehaves.
    """
    import os
    import time

    from . import chrome, config, task

    if launch_browser:
        reachable, detail = chrome.probe()
        echo(f"browser: {detail}")
        if not reachable:
            echo("browser: starting a dedicated automation Chrome")
            origin, message = chrome.launch(headless=headless)
            echo(f"browser: {message} ({origin})")
        chrome.apply_env()

    port = start_mock()
    base = f"http://127.0.0.1:{port}"

    # The text helper stays local in both modes: no free provider exists to borrow.
    os.environ["TEXT_MODEL_URL"] = f"{base}/mock/chat/completions"
    os.environ["TEXT_MODEL_API_KEY"] = "mock-text-key"
    os.environ["TEXT_MODEL"] = "mock-text-model"
    os.environ["TEXT_MODEL_REASONING"] = "none"
    os.environ["TEXT_MODEL_EXTRA_HEADERS"] = '{"X-Trace":"selftest"}'
    os.environ.setdefault("JEV_MAX_STEPS", "12")
    marker = "selftest"

    if real_decision:
        os.environ["JEV_BACKEND"] = "classifier"
        os.environ.pop("TYPESAFE_URL", None)
        os.environ.pop("TYPESAFE_API_KEY", None)
        os.environ["CLASSIFIER_USE_ENV_PROXY"] = "0"
        echo(f"decision endpoint: LIVE {config.classifier_url()}")
    else:
        os.environ["JEV_BACKEND"] = "typesafe"
        os.environ["TYPESAFE_URL"] = f"{base}/v1/systemone"
        os.environ["TYPESAFE_API_KEY"] = "mock-typesafe-key"
        os.environ["TYPESAFE_EXTRA_HEADERS"] = '{"X-Trace":"selftest"}'

    instruction = f"打开 {base}/fixture.html?scenario=travel 搜索 {WANTED} 并提交"
    echo(f"instruction: {instruction}")

    started = time.perf_counter()
    result = task.run_task(instruction, screenshots=False, keep_open=keep_open, preflight=True)
    elapsed = round((time.perf_counter() - started) * 1000)

    def all_seen(stream, **expected):
        return len(SEEN[stream]) > 0 and all(
            all(item.get(key) == value for key, value in expected.items()) for item in SEEN[stream]
        )

    common = {
        "custom text endpoint used": len(SEEN["text_model"]) > 0
        and all(item["url"] == "/mock/chat/completions" for item in SEEN["text_model"]),
        "text bearer + extra header": all_seen("text_model", authorization="Bearer mock-text-key", trace=marker),
        "model name + reasoning sent": len(SEEN["text_model"]) > 0
        and all(item["model"] == "mock-text-model" and item["reasoning_off"] for item in SEEN["text_model"]),
        "loop reached the page": result["steps"] > 0,
        "typed value came from the text helper": any(a["typed_text"] == WANTED for a in result["actions"]),
        "goal completed on the real page": "places in" in (result["page"]["text"] or ""),
        "status is done": result["status"] == "done",
    }
    if real_decision:
        models = {a.get("decided_by") for a in result["actions"]}
        checks = {
            "every decision came from the live model": bool(models)
            and all(model and model.startswith("jev-") for model in models),
            **common,
        }
    else:
        checks = {
            "custom Jev endpoint used": len(SEEN["typesafe"]) > 0
            and all(item["url"] == "/v1/systemone" for item in SEEN["typesafe"]),
            "Jev bearer + extra header": all_seen("typesafe", authorization="Bearer mock-typesafe-key", trace=marker),
            **common,
        }

    decision_source = "live classifier.dev" if real_decision else f"{len(SEEN['typesafe'])} mock requests"
    echo(f"\nJev endpoint  : {decision_source}")
    echo(f"Text endpoint : {len(SEEN['text_model'])} mock requests")
    for name, ok in checks.items():
        echo(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    echo(f"  total {elapsed} ms")
    if real_decision:
        echo(f"  decided by: {sorted(m for m in models if m)}")
    if result["error"]:
        echo(f"  error: {result['error']}")
        for check in result.get("checks", []):
            echo(f"  fix ({check['check']}): {check['fix']}")
    return checks, result
