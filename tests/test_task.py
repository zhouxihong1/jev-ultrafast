"""One-sentence intake: what URL does a sentence produce, and what does a run return."""

import pytest

from jev_ultrafast import cli, task


def _browser_unavailable():
    return [
        {"check": "browser (CDP)", "ok": False, "detail": "not listening", "fix": "jev-browser start"},
    ]


def test_launch_chrome_forwards_headless_to_the_launcher(monkeypatch):
    """--headless was accepted in three places and passed on in none of them.

    chrome.launch() defaults to a visible window, so the documented "With --launch-browser,
    run it headless" quietly opened a window anyway.
    """
    launched = {}
    monkeypatch.setattr(task.config, "preflight", lambda probe_browser=False: _browser_unavailable())
    monkeypatch.setattr("jev_ultrafast.chrome.launch", lambda **kw: launched.update(kw))

    result = task.run_task("bing 上海天气", launch_chrome=True, headless=True)

    assert launched == {"headless": True}
    assert result["status"] == "setup-required"  # preflight still blocks, as intended


def test_launch_chrome_defaults_to_a_visible_window(monkeypatch):
    launched = {}
    monkeypatch.setattr(task.config, "preflight", lambda probe_browser=False: _browser_unavailable())
    monkeypatch.setattr("jev_ultrafast.chrome.launch", lambda **kw: launched.update(kw))

    task.run_task("bing 上海天气", launch_chrome=True)

    assert launched == {"headless": False}


def test_jev_run_forwards_headless(monkeypatch):
    captured = {}
    monkeypatch.setattr(task, "run_task", lambda *a, **kw: captured.update(kw) or {"status": "done"})

    exit_code = cli.run_main(["bing 上海天气", "--launch-browser", "--headless", "--json", "--quiet"])

    assert exit_code == 0
    assert captured["launch_chrome"] is True
    assert captured["headless"] is True


def test_baidu_search_sentence_becomes_a_results_url():
    plan = task.parse_instruction("百度搜索 上海天气")
    assert plan.source == "search" and plan.engine == "baidu"
    assert plan.query == "上海天气"
    assert plan.url.startswith("https://www.baidu.com/s?wd=")
    assert "%E4%B8%8A%E6%B5%B7" in plan.url          # the query is percent-encoded
    assert "上海天气" in plan.goal


@pytest.mark.parametrize(
    "sentence,engine,query",
    [
        ("百度搜索 上海天气", "baidu", "上海天气"),
        ("百度一下 上海天气", "baidu", "上海天气"),        # 一下 is read as the verb
        ("帮我用百度搜一下 上海天气", "baidu", "上海天气"),
        ("在知乎搜索 上海的咖啡店", "zhihu", "上海的咖啡店"),
        ("google latest llm benchmarks", "google", "latest llm benchmarks"),
        ("用必应查一下 LLM 基准", "bing", "LLM 基准"),
        ("搜狗查找 附近的餐厅", "sogou", "附近的餐厅"),
        ("github search browser-use", "github", "browser-use"),
    ],
)
def test_engine_and_query_are_extracted(sentence, engine, query):
    plan = task.parse_instruction(sentence)
    if engine is None:
        assert plan.source == "fallback-search" and plan.notes
    else:
        assert plan.engine == engine and plan.query == query


def test_a_sentence_without_an_engine_uses_the_configured_default(monkeypatch):
    monkeypatch.setenv("JEV_DEFAULT_SEARCH_ENGINE", "bing")
    plan = task.parse_instruction("搜索 上海天气")
    assert plan.engine == "bing" and plan.query == "上海天气"
    assert plan.url.startswith("https://www.bing.com/search?q=")
    assert plan.notes


def test_trailing_instruction_is_split_off_the_search_phrase():
    plan = task.parse_instruction("百度搜索 上海天气，然后打开第一条结果")
    assert plan.query == "上海天气"
    assert plan.extra == "然后打开第一条结果"
    assert plan.goal.endswith("Then: 然后打开第一条结果")


def test_bare_domain_is_opened_directly():
    plan = task.parse_instruction("打开 example.com/docs")
    assert plan.source == "bare-domain" and plan.url == "https://example.com/docs"


def test_url_inside_a_sentence_is_detected():
    plan = task.parse_instruction("看看 https://example.com/a 有什么新东西")
    assert plan.source == "url-in-text" and plan.url == "https://example.com/a"
    assert "新东西" in plan.goal


def test_explicit_url_and_goal_skip_parsing():
    plan = task.parse_instruction("ignored text", url="example.org", goal="Do the thing")
    assert plan.source == "explicit-url"
    assert plan.url == "https://example.org" and plan.goal == "Do the thing"


def test_plain_sentence_falls_back_to_a_search():
    plan = task.parse_instruction("上海哪家本帮菜好吃")
    assert plan.source == "fallback-search" and plan.engine == "baidu"
    assert plan.query == "上海哪家本帮菜好吃"
    assert plan.notes


def test_empty_instruction_is_rejected():
    with pytest.raises(task.InstructionError):
        task.parse_instruction("   ")


@pytest.mark.parametrize("sentence", ["百度搜索", "百度搜", "google search", "在知乎搜索"])
def test_engine_without_keywords_asks_for_them(sentence):
    """`jev-run 百度搜索` used to search for the character 索."""
    with pytest.raises(task.InstructionError, match="no keywords"):
        task.parse_instruction(sentence)


def test_a_verb_is_never_split_into_the_query():
    plan = task.parse_instruction("百度搜索 上海天气")
    assert plan.query == "上海天气"
    plan = task.parse_instruction("百度搜索上海天气")
    assert plan.query == "上海天气"


def test_a_bare_engine_does_not_eat_the_first_character_of_the_query():
    """The optional 上/里 suffix after an engine used to consume the 上 in 上海天气."""
    plan = task.parse_instruction("bing 上海天气")
    assert plan.query == "上海天气", plan.url
    assert "%E4%B8%8A%E6%B5%B7" in plan.url  # 上海, not 海

    plan = task.parse_instruction("google 里约")
    assert plan.query == "里约"


def test_an_engine_suffix_is_still_understood_when_a_verb_follows():
    plan = task.parse_instruction("百度上搜索 上海天气")
    assert plan.engine == "baidu" and plan.query == "上海天气"


def test_a_verb_is_still_allowed_as_a_deliberate_query():
    """A genuine verb-plus-query match never reaches the bare-engine branch."""
    plan = task.parse_instruction("百度搜索 搜索")
    assert plan.query == "搜索" and plan.engine == "baidu"
    plan = task.parse_instruction("google search search")
    assert plan.query == "search" and plan.engine == "google"


def test_engine_aliases_resolve_both_ways():
    assert task.engine_for("百度") == "baidu"
    assert task.engine_for("Baidu") == "baidu"
    assert task.engine_for("哔哩哔哩") == "bilibili"
    assert task.engine_for("not-an-engine") is None
    assert task.engine_for("") is None


class FakeAgent:
    """Stands in for the real loop so run_task's contract is tested offline."""

    def __init__(self, url, goal, *, record_dir=None, screenshots=False):
        self.url, self.goal, self.closed = url, goal, False
        self.state = {
            "page": {"url": url, "title": "Results", "text": "row " * 40},
            "status": "ready",
            "history": [],
            "text_calls": [],
            "elapsed_ms": 0,
        }

    def run(self):
        self.state["status"] = "done"
        self.state["history"] = [
            {
                "step": 1,
                "action": "Search box",
                "kind": "fill",
                "operation": "TYPE_TEXT",
                "target": "1",
                "probability": 1.0,
                "confidence": 1.0,
                "text": "上海天气",
                "url": self.url,
            }
        ]
        self.state["elapsed_ms"] = 42
        yield self.snapshot()

    def snapshot(self):
        return {**self.state}

    def close(self):
        self.closed = True


def test_run_task_returns_a_json_serialisable_result(monkeypatch):
    import json

    created = {}

    def factory(url, goal, **kwargs):
        created["agent"] = FakeAgent(url, goal, **kwargs)
        return created["agent"]

    monkeypatch.setattr(task, "Agent", factory)
    result = task.run_task("百度搜索 上海天气")
    json.dumps(result)  # must be serialisable for external callers
    assert result["status"] == "done"
    assert result["plan"]["engine"] == "baidu"
    assert result["steps"] == 1 and result["actions"][0]["typed_text"] == "上海天气"
    assert result["page"]["title"] == "Results"
    assert created["agent"].closed is True


def test_run_task_truncates_page_text_and_can_leave_the_tab_open(monkeypatch):
    agent = FakeAgent("https://example.test", "go")
    monkeypatch.setattr(task, "Agent", lambda url, goal, **kwargs: agent)
    result = task.run_task("go", url="https://example.test", text_limit=10, keep_open=True)
    assert result["page"]["text"] == "row row ro"
    assert result["page"]["text_truncated"] is True
    assert agent.closed is False


def test_run_task_reports_failures_instead_of_raising(monkeypatch):
    def explode(url, goal, **kwargs):
        raise RuntimeError("browser harness is not running")

    monkeypatch.setattr(task, "Agent", explode)
    result = task.run_task("百度搜索 上海天气")
    assert result["status"] == "error"
    assert "browser harness is not running" in result["error"]
    assert result["steps"] == 0


def test_max_actions_stops_the_loop_early(monkeypatch):
    agent = FakeAgent("https://example.test", "go")
    monkeypatch.setattr(task, "Agent", lambda url, goal, **kwargs: agent)
    result = task.run_task("go", url="https://example.test", max_actions=1)
    assert result["status"] == "budget"


def test_doctor_reports_endpoints_and_versions(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "t")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "x")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setattr(task, "_browser_status", lambda: {"cdp": "reachable", "targets": 0})
    monkeypatch.setattr(task.config, "load_env", lambda *_a, **_k: None)
    report = task.doctor()
    assert report["config_ok"] is True
    assert report["packages"]["browser-harness"] == "0.1.13"
    assert report["config"]["jev"]["url"].endswith("/v1/systemone")
    assert report["config"]["text_model"]["url"] == "https://api.example.test/v1/chat/completions"
    assert report["browser"]["cdp"] == "reachable"
