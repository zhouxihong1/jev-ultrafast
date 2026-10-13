"""Live inspector for the one-sentence flow.

Serves a single page plus a small JSON API on 127.0.0.1. The page shows what the agent is
looking at, what it decided, and what it did, as the run happens:

    GET  /                the inspector
    GET  /api/state       the current run, polled by the page
    POST /api/plan        parse a sentence without starting anything (no browser, no cost)
    POST /api/run         start a run
    POST /api/stop        end the current run after its current step

Loopback-only, and every POST needs the per-process token that the page carries in a meta
tag, the same pattern the upstream demo uses. Screenshots are captured for the page only:
the model still decides from the structured element table.
"""

import html
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import config, task

ROOT = Path(__file__).parent
TOKEN = secrets.token_urlsafe(32)

OPERATION_OF_KIND = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT", "enter": "ENTER"}
CONTROL_KINDS = {"scroll", "wait"}


def element_view(page):
    """The numbered elements a decision was made over, with geometry for the overlay.

    Built here rather than reused from model.action_space: that one is the model's view and
    deliberately carries no node identity or geometry.
    """
    order, by_node, controls = [], {}, []
    for action in page.get("actions", []):
        kind = action.get("kind")
        if kind in CONTROL_KINDS:
            controls.append({"id": action["id"], "kind": kind, "label": action.get("label", kind)})
            continue
        node = action["node"]
        if node not in by_node:
            by_node[node] = {
                "index": str(len(order) + 1),
                "node": node,
                "role": action.get("role"),
                "label": action.get("label", ""),
                "value": action.get("value", ""),
                "operations": [],
                "rect": action.get("rect"),
                "selected": False,
            }
            order.append(by_node[node])
        element = by_node[node]
        operation = OPERATION_OF_KIND.get(kind)
        if operation and operation not in element["operations"]:
            element["operations"].append(operation)
        if kind == "select":
            element.setdefault("options", []).append(action.get("label"))
    return order, controls


def decision_view(state, chosen_node=None):
    """The most recent decision, minus the oversized request bodies."""
    decisions = state.get("decisions") or []
    if not decisions:
        return None
    last = decisions[-1]
    return {
        "operation": last.get("operation"),
        "target": last.get("target"),
        "choice": last.get("choice"),
        "confidence": last.get("confidence"),
        "operation_probabilities": last.get("operation_probabilities") or {},
        "target_probabilities": last.get("target_probabilities") or {},
        "target_confidence": last.get("target_confidence"),
        "latency_ms": last.get("latency_ms"),
        "model": last.get("model"),
        "calls": (last.get("request") or {}).get("calls"),
        "chosen_node": chosen_node,
    }


def history_view(history):
    return [
        {
            "step": item.get("step"),
            "operation": item.get("operation"),
            "kind": item.get("kind"),
            "action": item.get("action"),
            "typed_text": item.get("text"),
            "probability": item.get("probability"),
            "confidence": item.get("confidence"),
            "decided_by": item.get("model"),
            "page_changed": item.get("page_changed"),
            "elapsed_ms": item.get("elapsed_ms"),
        }
        for item in history
    ]


def text_calls_view(calls):
    return [
        {
            "field": call.get("field"),
            "value": call.get("value"),
            "model": call.get("model"),
            "latency_ms": call.get("latency_ms"),
        }
        for call in calls
    ]


def live_state(state):
    """Project the agent's state onto what the page needs."""
    page = state.get("page") or {}
    elements, controls = element_view(page)
    chosen = (state.get("decisions") or [{}])[-1].get("choice") if state.get("decisions") else None
    for element in elements:
        element["selected"] = bool(chosen) and any(
            action.get("id") == chosen
            for action in page.get("actions", [])
            if action.get("node") == element["node"]
        )
    # The executor returns raw base64; an <img> needs it spelled out as a data URL.
    raw_shot = page.get("screenshot")
    return {
        "status": state.get("status", "idle"),
        "goal": state.get("goal"),
        "elapsed_ms": state.get("elapsed_ms", 0),
        "steps": len(state.get("history") or []),
        "page": {
            "url": page.get("url"),
            "title": page.get("title"),
            "text": page.get("text", ""),
            "screenshot": f"data:image/jpeg;base64,{raw_shot}" if raw_shot else None,
            "width": page.get("w"),
            "height": page.get("h"),
        },
        "elements": elements,
        "controls": controls,
        "decision": decision_view(state),
        "actions": history_view(state.get("history") or []),
        "text_calls": text_calls_view(state.get("text_calls") or []),
    }


class Manager:
    """Runs at most one task at a time and keeps the latest view for the page to poll."""

    def __init__(self, launch_browser=False, headless=False):
        self.launch_browser = launch_browser
        self.headless = headless
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.thread = None
        self.state = self._idle()
        self.started_at = None

    @staticmethod
    def _idle():
        return {"status": "idle", "running": False, "instruction": "", "plan": None, "checks": []}

    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def snapshot(self):
        with self.lock:
            view = dict(self.state)
        if self.running() and self.started_at:
            view["elapsed_ms"] = max(view.get("elapsed_ms", 0), round((time.perf_counter() - self.started_at) * 1000))
        return view

    def _publish(self, **fields):
        with self.lock:
            self.state.update(fields)

    def start(self, instruction, url=None, goal=None, steps=None, keep_open=False):
        if self.running():
            raise ValueError("A run is already in progress")
        instruction = (instruction or "").strip()
        if not instruction and not url:
            raise ValueError("Enter an instruction, for example: 百度搜索 上海天气")
        plan = task.parse_instruction(instruction, url=url, goal=goal)  # raises InstructionError
        self.stop_flag.clear()
        self.started_at = time.perf_counter()
        self._publish(status="starting", running=True, instruction=instruction, plan=plan.as_dict(), error=None,
                      checks=[], message=None)
        self.thread = threading.Thread(
            target=self._run,
            args=(instruction, url, goal, steps, keep_open),
            daemon=True,
            name="jev-ui-run",
        )
        self.thread.start()
        return plan.as_dict()

    def _run(self, instruction, url, goal, steps, keep_open):
        try:
            result = task.run_task(
                instruction,
                url=url,
                goal=goal,
                max_actions=steps,
                keep_open=keep_open,
                screenshots=True,
                launch_chrome=self.launch_browser,
                on_step=self._on_step,
            )
        except task.InstructionError as exc:
            self._publish(status="error", running=False, error=str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - the page is the only place to report it
            self._publish(status="error", running=False, error=f"{type(exc).__name__}: {exc}")
            return
        finally:
            self.started_at = None
        self._publish(
            status=result["status"],
            running=False,
            error=result.get("error"),
            checks=result.get("checks", []),
            plan=result["plan"],
            result={
                "status": result["status"],
                "steps": result["steps"],
                "elapsed_ms": result["elapsed_ms"],
                "actions": result["actions"],
                "text_calls": result["text_calls"],
                "final_url": result["page"]["url"],
                "final_title": result["page"]["title"],
                "page_text": result["page"]["text"],
            },
        )

    def _on_step(self, state):
        if self.stop_flag.is_set():
            raise task.StopRequested
        if self.started_at:
            state = {**state, "elapsed_ms": round((time.perf_counter() - self.started_at) * 1000)}
        self._publish(running=True, **live_state(state))

    def stop(self):
        if not self.running():
            return False
        self.stop_flag.set()
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "jev-ultrafast-ui"
    manager: Manager = None
    origin = ""

    def _send(self, status, content, mime="application/json"):
        body = content if isinstance(content, bytes) else content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status=200):
        self._send(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def _authorised(self):
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_address[1]}", self.origin} and (
            self.headers.get("X-UI-Token") == TOKEN
        )

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            page = (ROOT / "static" / "ui.html").read_text(encoding="utf-8")
            page = page.replace("__TOKEN__", TOKEN).replace(
                "__INSTRUCTION__", html.escape(getattr(self.server, "instruction", ""))
            )
            return self._send(200, page, "text/html; charset=utf-8")
        if path == "/api/state":
            return self._json(self.manager.snapshot())
        if path == "/api/meta":
            return self._json({"config": config.summary(), "backend": config.backend()})
        self._json({"error": "Not found"}, 404)

    def do_POST(self):
        if not self._authorised():
            return self._json({"error": "Local inspector requests only"}, 403)
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if 0 < length < 65536 else {}
        except ValueError:
            return self._json({"error": "Body must be JSON"}, 400)

        try:
            if path == "/api/plan":
                plan = task.parse_instruction(body.get("instruction", ""), url=body.get("url"), goal=body.get("goal"))
                return self._json({"plan": plan.as_dict()})
            if path == "/api/run":
                plan = self.manager.start(
                    body.get("instruction", ""),
                    url=body.get("url"),
                    goal=body.get("goal"),
                    steps=body.get("steps"),
                    keep_open=bool(body.get("keep_open")),
                )
                return self._json({"plan": plan})
            if path == "/api/stop":
                return self._json({"stopping": self.manager.stop()})
        except task.InstructionError as exc:
            return self._json({"error": str(exc)}, 400)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 409)
        self._json({"error": "Not found"}, 404)

    def log_message(self, *_args):
        pass


def serve(host="127.0.0.1", port=8788, launch_browser=False, headless=False, open_browser=False,
          instruction="", echo=print):
    origin = f"http://{host}:{port}"
    Handler.manager = Manager(launch_browser=launch_browser, headless=headless)
    Handler.origin = origin
    server = ThreadingHTTPServer((host, port), Handler)
    server.instruction = instruction or ""
    echo(f"Jev Ultrafast inspector: {origin}")
    echo(f"  decision backend: {config.backend()}")
    if open_browser:
        import webbrowser

        threading.Timer(0.4, lambda: webbrowser.open(origin)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
