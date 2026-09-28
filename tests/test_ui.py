"""The inspector is a real HTTP surface, so it is tested through HTTP.

Runs are stubbed: these tests must not need a browser. What is being checked is the API
contract, the token gate, the shape of what the page polls, and the element overlay maths.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from jev_ultrafast import task, ui


@pytest.fixture
def inspector(monkeypatch):
    """A manager and a running server on a free loopback port."""
    from http.server import ThreadingHTTPServer

    manager = ui.Manager()
    handler = type("Handler", (ui.Handler,), {"manager": manager})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.instruction = ""
    handler.origin = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"manager": manager, "origin": handler.origin, "token": ui.TOKEN, "handler": handler, "server": server}
    server.shutdown()


def call(inspector, method, path, payload=None, token=None, host=None):
    url = inspector["origin"] + path
    headers = {"Content-Type": "application/json"}
    if token is not False:
        headers["X-UI-Token"] = token or inspector["token"]
    if host:
        headers["Host"] = host
    request = urllib.request.Request(  # noqa: S310 - loopback only
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read() or b"{}")


def test_health_and_meta_describe_the_active_backend(inspector):
    status, body = call(inspector, "GET", "/api/state")
    assert status == 200 and body["status"] == "idle" and body["running"] is False
    status, body = call(inspector, "GET", "/api/meta")
    assert body["backend"] in {"classifier", "typesafe"}
    assert "url" in body["config"]["jev"]


def test_the_page_is_served_with_its_token_inlined(inspector):
    url = inspector["origin"] + "/"
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - loopback only
        html = response.read().decode("utf-8")
    assert "__TOKEN__" not in html
    assert inspector["token"] in html
    assert "运行观察台" in html


def test_a_prefilled_instruction_is_escaped_into_the_box(inspector):
    inspector["server"].instruction = '<script>alert("x")</script>百度搜索'
    with urllib.request.urlopen(inspector["origin"] + "/", timeout=10) as response:  # noqa: S310
        html = response.read().decode("utf-8")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html and "百度搜索" in html


def test_post_without_the_token_is_refused(inspector):
    with pytest.raises(urllib.error.HTTPError) as error:
        call(inspector, "POST", "/api/run", {"instruction": "百度搜索 x"}, token="wrong")
    assert error.value.code == 403


def test_plan_costs_nothing_and_returns_the_parsed_entry_point(inspector):
    status, body = call(inspector, "POST", "/api/plan", {"instruction": "百度搜索 上海天气"})
    assert status == 200
    assert body["plan"]["engine"] == "baidu" and body["plan"]["query"] == "上海天气"
    assert inspector["manager"].running() is False


def test_an_unparsable_instruction_is_a_400(inspector):
    with pytest.raises(urllib.error.HTTPError) as error:
        call(inspector, "POST", "/api/plan", {"instruction": "百度搜索"})
    assert error.value.code == 400
    payload = json.loads(error.value.read())
    assert "no keywords" in payload["error"]


def test_a_run_publishes_progress_and_finishes(inspector, monkeypatch):
    """The page polls /api/state, so the stubbed run must publish exactly that shape.

    `on_step` receives the agent's whole state, whose "page" key holds the observation.
    """
    seen = {}

    def fake_run_task(instruction, **options):
        seen["instruction"] = instruction
        seen["options"] = options
        page = {
            "url": "https://cn.bing.com/",
            "title": "搜索 - Microsoft 必应",
            "text": "搜索框 反馈",
            "w": 1120,
            "h": 780,
            "screenshot": "LzlqLzRBQVFTa1pKUmdBQkFRQUFBUUFCQUFELzJ3Q0VBQUFB",
            "actions": [
                {"id": "e1", "kind": "fill", "label": "输入搜索词", "role": "searchbox", "value": "", "node": 7,
                 "rect": {"x": 10, "y": 20, "w": 300, "h": 40}},
                {"id": "e2", "kind": "enter", "label": "输入搜索词", "role": "searchbox", "value": "", "node": 7,
                 "rect": {"x": 10, "y": 20, "w": 300, "h": 40}},
                {"id": "e3", "kind": "click", "label": "反馈", "role": "button", "value": "", "node": 30,
                 "rect": {"x": 700, "y": 600, "w": 60, "h": 30}},
                {"id": "wait", "kind": "wait", "label": "Wait"},
            ],
        }
        decisions = [
            {
                "choice": "e2",
                "operation": "ENTER",
                "target": "1",
                "confidence": 0.83,
                "operation_probabilities": {"ENTER": 0.83, "CLICK": 0.11, "DONE": 0.03},
                "target_probabilities": {"1": 0.94},
                "request": {"calls": 2, "backend": "classifier"},
                "model": "jev-1.13.0",
                "latency_ms": 260,
            }
        ]
        history = [
            {"step": 1, "operation": "TYPE_TEXT", "kind": "fill", "action": "输入搜索词",
             "text": "上海天气", "probability": 1.0, "confidence": 0.99, "model": "jev-1.13.0",
             "page_changed": True, "elapsed_ms": 4100},
        ]
        text_calls = [{"field": "输入搜索词", "value": "上海天气", "model": "deepseek-v4-flash",
                       "latency_ms": 900}]
        options["on_step"]({
            "page": page,
            "decisions": decisions,
            "history": history,
            "text_calls": text_calls,
            "status": "ready",
            "elapsed_ms": 4100,
            "goal": "搜索 上海天气 并提交",
        })
        seen["mid"] = inspector["manager"].snapshot()
        return {
            "instruction": instruction,
            "plan": {"url": "https://cn.bing.com/", "goal": "g", "source": "url-in-text",
                     "engine": None, "query": None, "extra": "", "notes": []},
            "status": "done", "error": None, "elapsed_ms": 9900, "steps": 1,
            "actions": [{"step": 1, "operation": "TYPE_TEXT", "action": "输入搜索词", "typed_text": "上海天气",
                         "probability": 1.0, "decided_by": "jev-1.13.0", "url": "https://cn.bing.com/"}],
            "text_calls": [{"field": "输入搜索词", "value": "上海天气", "model": "deepseek-v4-flash"}],
            "page": {"url": "https://cn.bing.com/search?q=x", "title": "上海天气 - 搜索", "text": "结果",
                     "text_truncated": False},
            "budget": 20,
        }

    monkeypatch.setattr(ui.task, "run_task", fake_run_task)
    instruction = "打开 https://cn.bing.com 搜索 上海天气"
    status, body = call(inspector, "POST", "/api/run", {"instruction": instruction, "steps": 20})
    assert status == 200 and body["plan"]["url"] == "https://cn.bing.com"
    assert seen["options"]["screenshots"] is True
    assert seen["options"]["max_actions"] == 20

    # What the page saw mid-run.
    assert seen["mid"]["running"] is True
    assert seen["mid"]["status"] == "ready"
    # The executor returns raw base64; an <img> needs a data URL or it renders as nothing.
    expected = "data:image/jpeg;base64,LzlqLzRBQVFTa1pKUmdBQkFRQUFBUUFCQUFELzJ3Q0VBQUFB"
    assert seen["mid"]["page"]["screenshot"] == expected
    assert [e["index"] for e in seen["mid"]["elements"]] == ["1", "2"]
    assert seen["mid"]["elements"][0]["operations"] == ["TYPE_TEXT", "ENTER"]
    assert seen["mid"]["elements"][0]["selected"] is True
    assert seen["mid"]["elements"][1]["selected"] is False
    assert seen["mid"]["controls"] == [{"id": "wait", "kind": "wait", "label": "Wait"}]
    assert seen["mid"]["decision"]["operation"] == "ENTER"
    assert seen["mid"]["decision"]["calls"] == 2
    assert "request" not in seen["mid"]["decision"]  # the model's request body is not sent to the page
    assert seen["mid"]["text_calls"][0]["value"] == "上海天气"
    assert seen["mid"]["actions"][0]["page_changed"] is True

    inspector["manager"].thread.join(timeout=5)
    final = inspector["manager"].snapshot()
    assert final["running"] is False and final["status"] == "done"
    assert final["result"]["final_url"].endswith("q=x")


def test_a_broken_run_reports_the_error_instead_of_hanging(inspector, monkeypatch):
    def explode(*_args, **_options):
        raise RuntimeError("browser harness is not running")

    monkeypatch.setattr(ui.task, "run_task", explode)
    call(inspector, "POST", "/api/run", {"instruction": "百度搜索 上海天气"})
    inspector["manager"].thread.join(timeout=5)
    state = inspector["manager"].snapshot()
    assert state["running"] is False and state["status"] == "error"
    assert "browser harness is not running" in state["error"]


def test_a_second_run_is_refused_while_one_is_in_flight(inspector, monkeypatch):
    release = threading.Event()

    def slow(instruction, **options):
        release.wait(timeout=5)
        options["on_step"]({"page": None, "history": [], "text_calls": [], "status": "ready", "elapsed_ms": 0,
                            "decisions": [], "goal": "g"})
        return {"instruction": instruction, "plan": {}, "status": "done", "error": None, "elapsed_ms": 1,
                "steps": 0, "actions": [], "text_calls": [], "page": {"url": None, "title": None, "text": ""}}

    monkeypatch.setattr(ui.task, "run_task", slow)
    call(inspector, "POST", "/api/run", {"instruction": "百度搜索 上海天气"})
    with pytest.raises(urllib.error.HTTPError) as error:
        call(inspector, "POST", "/api/run", {"instruction": "bing 上海天气"})
    assert error.value.code == 409
    release.set()
    inspector["manager"].thread.join(timeout=5)


def test_stop_asks_the_run_to_end_after_its_current_step(inspector, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow(instruction, **options):
        on_step = options["on_step"]
        started.set()
        release.wait(timeout=5)
        try:
            on_step({"page": None, "history": [], "text_calls": [], "status": "ready", "elapsed_ms": 0,
                     "decisions": [], "goal": "g"})
            return {"instruction": instruction, "plan": {}, "status": "ready", "error": None, "elapsed_ms": 1,
                    "steps": 0, "actions": [], "text_calls": [], "page": {"url": None, "title": None, "text": ""}}
        except task.StopRequested:
            return {"instruction": instruction, "plan": {}, "status": "stopped", "error": None, "elapsed_ms": 1,
                    "steps": 0, "actions": [], "text_calls": [], "page": {"url": None, "title": None, "text": ""}}

    monkeypatch.setattr(ui.task, "run_task", slow)
    call(inspector, "POST", "/api/run", {"instruction": "百度搜索 上海天气"})
    assert started.wait(timeout=5)
    status, body = call(inspector, "POST", "/api/stop", {})
    assert status == 200 and body["stopping"] is True
    release.set()
    inspector["manager"].thread.join(timeout=5)
    assert inspector["manager"].snapshot()["status"] == "stopped"


def test_stop_is_a_no_op_when_nothing_is_running(inspector):
    _status, body = call(inspector, "POST", "/api/stop", {})
    assert body["stopping"] is False


def test_run_task_reports_a_stop_as_its_own_status(monkeypatch):
    """StopRequested must not be reported as an error: the history so far is still valid."""
    class Agent:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self):
            yield {"page": {"url": "x", "title": "t", "text": ""}, "history": [], "text_calls": [],
                   "status": "ready", "elapsed_ms": 1, "decisions": [], "goal": "g"}

        def snapshot(self):
            return {"page": {"url": "x", "title": "t", "text": ""}, "status": "ready", "history": [],
                    "text_calls": [], "elapsed_ms": 5}

        def close(self):
            pass

    monkeypatch.setattr(task, "Agent", Agent)

    def stop_now(_state):
        raise task.StopRequested

    result = task.run_task("百度搜索 上海天气", preflight=False, on_step=stop_now)
    assert result["status"] == "stopped" and result["error"] is None


def test_element_view_numbers_by_first_appearance_and_keeps_geometry():
    page = {
        "actions": [
            {"id": "e1", "kind": "fill", "node": 7, "label": "输入搜索词", "role": "searchbox", "value": "",
             "rect": {"x": 1, "y": 2, "w": 3, "h": 4}},
            {"id": "e2", "kind": "enter", "node": 7, "label": "输入搜索词", "role": "searchbox", "value": "",
             "rect": {"x": 1, "y": 2, "w": 3, "h": 4}},
            {"id": "e3", "kind": "click", "node": 30, "label": "反馈", "role": "button", "value": "",
             "rect": {"x": 5, "y": 6, "w": 7, "h": 8}},
            {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560},
            {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
        ]
    }
    elements, controls = ui.element_view(page)
    assert [e["index"] for e in elements] == ["1", "2"]
    assert elements[0]["node"] == 7 and elements[0]["operations"] == ["TYPE_TEXT", "ENTER"]
    assert elements[0]["rect"] == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert elements[1]["operations"] == ["CLICK"]
    assert [c["id"] for c in controls] == ["scroll_down", "wait"]


def test_element_view_survives_a_page_without_actions():
    elements, controls = ui.element_view({})
    assert elements == [] and controls == []


def test_a_page_without_a_screenshot_reports_none():
    view = ui.live_state({"page": {"url": "u", "title": "t", "text": "", "actions": []}, "history": []})
    assert view["page"]["screenshot"] is None
