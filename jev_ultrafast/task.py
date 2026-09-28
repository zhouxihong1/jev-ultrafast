"""One sentence in, a finished browser run out.

This is the external entry point. It turns a short instruction such as
``百度搜索 上海天气`` into a start URL plus a goal, runs the normal agent loop,
and returns a JSON-serialisable result. Nothing here bypasses the loop: the model
still chooses every operation, and the executor still owns every input.
"""

import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from . import config
from .agent import Agent

# name -> (human aliases, results URL template, human label)
ENGINES = {
    "baidu": (("百度", "baidu"), "https://www.baidu.com/s?wd={q}", "Baidu"),
    "google": (("谷歌", "google"), "https://www.google.com/search?q={q}", "Google"),
    "bing": (("必应", "bing"), "https://www.bing.com/search?q={q}", "Bing"),
    "sogou": (("搜狗", "sogou"), "https://www.sogou.com/web?query={q}", "Sogou"),
    "so": (("360搜索", "360", "so.com"), "https://www.so.com/s?q={q}", "360 Search"),
    "duckduckgo": (("duckduckgo", "ddg"), "https://duckduckgo.com/?q={q}", "DuckDuckGo"),
    "zhihu": (("知乎", "zhihu"), "https://www.zhihu.com/search?type=content&q={q}", "Zhihu"),
    "weibo": (("微博", "weibo"), "https://s.weibo.com/weibo?q={q}", "Weibo"),
    "bilibili": (("b站", "哔哩哔哩", "bilibili"), "https://search.bilibili.com/all?keyword={q}", "Bilibili"),
    "taobao": (("淘宝", "taobao"), "https://s.taobao.com/search?q={q}", "Taobao"),
    "jd": (("京东", "jd"), "https://search.jd.com/Search?keyword={q}", "JD"),
    "github": (("github",), "https://github.com/search?q={q}", "GitHub"),
    "youtube": (("youtube",), "https://www.youtube.com/results?search_query={q}", "YouTube"),
    "wikipedia": (("维基百科", "wikipedia", "wiki"), "https://en.wikipedia.org/w/index.php?search={q}", "Wikipedia"),
}

DEFAULT_ENGINE = "baidu"

VERBS = "搜索|搜一下|搜搜|搜|查找|查询|查一下|查|检索|找一下|找|一下|search|look up"
VERB_SET = set(VERBS.split("|"))
POLITE = r"(?:请|帮我|帮忙|麻烦|给我|我要|我想)?"
LEAD = r"(?:打开|去|用|在|上|从)?"

# Every engine alias, longest first, so "360搜索" wins over "360" and "wikipedia" over "wiki".
ALIASES = sorted((alias for aliases, _t, _l in ENGINES.values() for alias in aliases), key=len, reverse=True)
ALIAS_PATTERN = "|".join(re.escape(alias) for alias in ALIASES)

# The verb is atomic: without (?>...) the engine would backtrack out of "搜索" into "搜" and
# leave "索" as the query, so "百度搜索" would search for the character 索.
VERB_GROUP = rf"(?>(?:{VERBS}))"

# Engine named as a known alias, then a search verb: "百度搜索 X", "用必应查一下 X".
# Matching the alias list explicitly - rather than a loose character class - is what keeps
# "用必应查一下" from being read as the engine "必应查".
ENGINE_VERB_RE = re.compile(
    rf"^\s*{POLITE}\s*{LEAD}\s*(?P<engine>{ALIAS_PATTERN})\s*(?:上|里|上面|里面)?\s*"
    rf"{VERB_GROUP}\s*[:：]?\s*(?P<query>.+?)\s*$",
    re.IGNORECASE,
)

# Verb only, no engine named: "搜索 X", "帮我查一下 X" -> the configured default engine.
VERB_ONLY_RE = re.compile(
    rf"^\s*{POLITE}\s*{LEAD}\s*{VERB_GROUP}\s*[:：]?\s*(?P<query>.+?)\s*$",
    re.IGNORECASE,
)

# "<engine> <query>" with no verb at all: "google latest llm benchmarks".
# No optional 上/里 suffix here: with nothing to separate them from the query it would eat a
# leading character, so "bing 上海天气" would search for "海天气".
BARE_ENGINE_RE = re.compile(
    rf"^\s*{POLITE}\s*{LEAD}\s*(?P<engine>{ALIAS_PATTERN})\s*[:：]?\s*(?P<query>.+?)\s*$",
    re.IGNORECASE,
)

URL_RE = re.compile(r"https?://[^\s，,。；;\"'）)]+")
BARE_DOMAIN_RE = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?$", re.IGNORECASE)
SPLIT_RE = re.compile(r"[，,；;]|然后| afterwards| then ")
# Leading filler left behind once a URL has been pulled out of the sentence.
LEAD_STRIP_RE = re.compile(
    r"^\s*(?:请|帮我|帮忙|麻烦|给我|我要|我想)?\s*(?:打开|访问|去|看看|进入|open|visit|go to|navigate to)\s*",
    re.IGNORECASE,
)


def tidy(text):
    """Collapse whitespace and drop the leading verb that referred to the URL."""
    return LEAD_STRIP_RE.sub("", re.sub(r"\s+", " ", text or "")).strip(" ，,。;；\"'")


class InstructionError(ValueError):
    """The instruction cannot be turned into a start URL."""


class StopRequested(Exception):
    """Raised from an ``on_step`` callback to end a run early and cleanly."""


@dataclass
class Plan:
    url: str
    goal: str
    source: str
    engine: str | None = None
    query: str | None = None
    extra: str = ""
    notes: list = field(default_factory=list)

    def as_dict(self):
        return {
            "url": self.url,
            "goal": self.goal,
            "source": self.source,
            "engine": self.engine,
            "query": self.query,
            "extra": self.extra,
            "notes": list(self.notes),
        }


def engine_for(name):
    """Resolve an engine alias to its key, or None when the token is not an engine."""
    token = (name or "").strip().lower().strip("的")
    if not token:
        return None
    if token in ENGINES:
        return token
    for key, (aliases, _template, _label) in ENGINES.items():
        if token in {alias.lower() for alias in aliases}:
            return key
    return None


def search_url(engine, query):
    _aliases, template, _label = ENGINES[engine]
    return template.format(q=quote_plus(query))


def split_extra(text):
    """Peel a trailing instruction off the search phrase: '百度搜索X，然后打开第一条'."""
    parts = SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 1:
        return text.strip(), ""
    head = parts[0].strip()
    tail = text[len(parts[0]):].lstrip("，,；; ").strip()
    return head, tail


def goal_for(engine, query, extra=""):
    label = ENGINES[engine][2] if engine else "the site"
    goal = f'Search {label} for "{query}" and confirm the results for "{query}" are visible.'
    goal += (
        " The browser already points at the results page;"
        " if those results are already shown, do not repeat the search."
    )
    if extra:
        goal += f" Then: {extra}"
    return goal


def keyword_error(text, query):
    """Reject an engine plus a verb with no keywords, e.g. `百度搜索` or `google search`.

    A genuine request like `百度搜索 上海天气` is matched earlier by ENGINE_VERB_RE, because
    the verb is atomic there. Reaching this point with a bare verb as the query means the
    sentence ended right after the verb, so there is nothing to search for.
    """
    if query in VERB_SET:
        raise InstructionError(
            f"{text!r} names a search engine but no keywords. Try: jev-run \"{text} 上海天气\""
        )
    return None


def parse_instruction(text, *, url=None, goal=None):
    """Turn one sentence into a start URL plus a goal. Never invents a search engine silently."""
    text = (text or "").strip()
    if not text and not url:
        raise InstructionError("Nothing to do: supply an instruction or --url")

    if url:
        resolved = url if "://" in url else "https://" + url.lstrip("/")
        return Plan(
            url=resolved,
            goal=goal or (text or f"Open {resolved} and report what is visible."),
            source="explicit-url",
        )

    match = URL_RE.search(text)
    if match:
        resolved = match.group(0)
        remainder = tidy(text[: match.start()] + " " + text[match.end():])
        return Plan(
            url=resolved,
            goal=goal or remainder or f"Open {resolved} and report what is visible.",
            source="url-in-text",
            extra=remainder,
        )

    head, extra = split_extra(text)

    opened = re.match(r"^\s*(?:请|帮我|帮忙|麻烦)?\s*(?:打开|访问|去|open)\s*(?P<target>[^\s]+)\s*(?P<rest>.*)$",
                      head, re.IGNORECASE)
    if opened:
        target = opened.group("target").strip("，,。;；\"'")
        if BARE_DOMAIN_RE.match(target):
            rest = (opened.group("rest") or "").strip()
            tail = tidy(" ".join(part for part in (rest, extra) if part))
            return Plan(
                url="https://" + target,
                goal=goal or tail or f"Open https://{target} and report what is visible.",
                source="bare-domain",
                extra=tail,
            )

    search = ENGINE_VERB_RE.match(head) or VERB_ONLY_RE.match(head)
    if search:
        query = search.group("query").strip(" ，,。;；\"'")
        named = engine_for(search.groupdict().get("engine"))
        # "搜索 上海天气" names no engine, so the configured default applies.
        if named is None:
            configured = config.env("JEV_DEFAULT_SEARCH_ENGINE", DEFAULT_ENGINE)
            engine = engine_for(configured) or DEFAULT_ENGINE
            notes = [f"no engine named; used {engine}"]
        else:
            engine, notes = named, []
        if not query:
            raise InstructionError(f"No search keywords found in {text!r}")
        return Plan(
            url=search_url(engine, query),
            goal=goal or goal_for(engine, query, extra),
            source="search",
            engine=engine,
            query=query,
            extra=extra,
            notes=notes,
        )

    bare = BARE_ENGINE_RE.match(head)
    if bare:
        engine = engine_for(bare.group("engine"))
        query = bare.group("query").strip(" ，,。;；\"'")
        if engine and query:
            keyword_error(head, query)
            return Plan(
                url=search_url(engine, query),
                goal=goal or goal_for(engine, query, extra),
                source="engine-query",
                engine=engine,
                query=query,
                extra=extra,
                notes=["no search verb; read the sentence as <engine> <query>"],
            )

    configured = config.env("JEV_DEFAULT_SEARCH_ENGINE", DEFAULT_ENGINE)
    engine = engine_for(configured) or DEFAULT_ENGINE
    return Plan(
        url=search_url(engine, text),
        goal=goal or goal_for(engine, text, extra),
        source="fallback-search",
        engine=engine,
        query=text,
        extra=extra,
        notes=[f"no search verb found; treated the whole sentence as a {engine} query"],
    )


def run_task(
    instruction,
    *,
    url=None,
    goal=None,
    record_dir=None,
    screenshots=False,
    on_step=None,
    max_actions=None,
    text_limit=8000,
    keep_open=False,
    preflight=True,
    launch_chrome=False,
):
    """Run one instruction end to end and return a JSON-serialisable result.

    The returned ``page`` block is the last observed page, which is what an external
    caller usually wants: for a search it holds the visible result text.

    With ``preflight`` (the default) the environment is checked before anything is
    launched, so a missing key or an undrivable browser returns a list of fixes instead
    of a slow, opaque failure. ``launch_chrome`` starts a dedicated automation browser
    when no CDP endpoint is configured.
    """
    plan = parse_instruction(instruction, url=url, goal=goal)
    budget = max_actions or config.max_steps()

    if preflight and launch_chrome and not config.preflight(probe_browser=True)[-1]["ok"]:
        try:
            from . import chrome

            chrome.launch()
        except Exception:  # noqa: BLE001 - the preflight below reports the real problem
            pass

    if preflight:
        blocked = [check for check in config.preflight(probe_browser=True) if not check["ok"]]
        if blocked:
            return _blocked_result(instruction, plan, blocked, budget)

    started = time.perf_counter()
    error, cut_short, stopped = None, False, False
    agent = None
    try:
        agent = Agent(plan.url, plan.goal, record_dir=record_dir, screenshots=screenshots)
        for state in agent.run():
            if on_step:
                on_step(state)
            if max_actions and len(state["history"]) >= max_actions:
                cut_short = True
                break
    except StopRequested:
        # An operator asked to stop. Not a failure: the history so far is still returned.
        stopped = True
    except Exception as exc:  # noqa: BLE001 - surfaced in the result, never swallowed
        error = f"{type(exc).__name__}: {exc}"
    finally:
        final = agent.snapshot() if agent else {
            "page": None, "status": "error", "history": [], "text_calls": [], "elapsed_ms": 0
        }
        if agent and not keep_open:
            agent.close()
    page = final["page"] or {}
    if error:
        status = "error"
    elif stopped:
        status = "stopped"
    elif cut_short:
        status = "budget"
    else:
        status = final["status"]
    return {
        "instruction": instruction,
        "plan": plan.as_dict(),
        "status": status,
        "error": error,
        "elapsed_ms": final["elapsed_ms"] or round((time.perf_counter() - started) * 1000),
        "steps": len(final["history"]),
        "actions": [
            {
                "step": h["step"],
                "action": h["action"],
                "kind": h["kind"],
                "operation": h.get("operation"),
                "target": h.get("target"),
                "probability": h.get("probability"),
                "confidence": h.get("confidence"),
                "decided_by": h.get("model"),
                "typed_text": h.get("text"),
                "url": h.get("url"),
            }
            for h in final["history"]
        ],
        "text_calls": [
            {"field": call["field"], "value": call["value"], "model": call.get("model")}
            for call in final["text_calls"]
        ],
        "page": {
            "url": page.get("url"),
            "title": page.get("title"),
            "text": (page.get("text") or "")[:text_limit],
            "text_truncated": len(page.get("text") or "") > text_limit,
        },
        "budget": budget,
    }


def _blocked_result(instruction, plan, blocked, budget):
    """A run that never started, with the exact fix for each missing prerequisite."""
    return {
        "instruction": instruction,
        "plan": plan.as_dict(),
        "status": "setup-required",
        "error": "; ".join(f"{check['check']}: {check['detail']}" for check in blocked),
        "checks": blocked,
        "elapsed_ms": 0,
        "steps": 0,
        "actions": [],
        "text_calls": [],
        "page": {"url": None, "title": None, "text": "", "text_truncated": False},
        "budget": budget,
    }


def live_probe(timeout=20.0):
    """Make one minimal real call per endpoint, so 'configured' is not mistaken for 'working'.

    Costs a token or two and is never part of a normal run: `jev-doctor --live` asks for it.
    """
    from . import model

    report = {}

    try:
        if config.backend() == "classifier":
            label, _scores, raw = model.classify("ping", ["a", "b"])
            report["jev"] = {
                "ok": True,
                "detail": f"{raw.get('model', 'classifier')} answered {label!r}",
                "url": config.classifier_url(),
            }
        else:
            body = {
                "model": config.typesafe_model(),
                "state": {
                    "page": {"url": "about:blank", "title": "ping", "text": "ping"},
                    "elements": [],
                    "recent_actions": [],
                },
                "questions": {
                    "operation": {
                        "type": "choice",
                        "criteria": {"DONE": "nothing to do", "BLOCKED": "cannot proceed"},
                    }
                },
            }
            result = model.post_json(
                config.typesafe_url(),
                config.typesafe_key(),
                body,
                headers=config.typesafe_headers(),
                timeout=timeout,
            )
            report["jev"] = {
                "ok": True,
                "detail": f"{result.get('model', 'typesafe')} answered",
                "url": config.typesafe_url(),
            }
    except Exception as exc:  # noqa: BLE001 - a probe reports, it never raises
        report["jev"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "url": config.typesafe_url()}

    try:
        response = model.CLIENT.post(
            config.text_url(),
            json={
                "model": config.text_model(),
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
            headers=config.text_headers(),
            timeout=timeout,
        )
        if response.is_error:
            report["text_model"] = {
                "ok": False,
                "detail": f"HTTP {response.status_code}: {response.text[:240]}",
                "url": config.text_url(),
            }
        else:
            report["text_model"] = {
                "ok": True,
                "detail": f"{config.text_model()} returned a completion",
                "url": config.text_url(),
            }
    except Exception as exc:  # noqa: BLE001 - a probe reports, it never raises
        report["text_model"] = {
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "url": config.text_url(),
        }
    return report


def doctor(env_file=None, probe_browser=True, live=False):
    """Report the settings and versions that decide whether a run is reproducible."""
    import platform
    import sys
    from importlib.metadata import PackageNotFoundError, version

    report = {"python": sys.version.split()[0], "platform": platform.platform(), "packages": {}, "config": {}}
    for name in ("jev-ultrafast", "browser-harness", "cdp-use", "fetch-use", "httpx", "pillow", "websockets"):
        try:
            report["packages"][name] = version(name)
        except PackageNotFoundError:
            report["packages"][name] = None
    loaded = config.load_env(env_file)
    report["env_file"] = str(loaded) if loaded else None
    try:
        report["config"] = config.summary()
        report["config_ok"] = True
    except config.ConfigError as exc:
        report["config"] = {"error": str(exc)}
        report["config_ok"] = False
    if not probe_browser:
        return report
    report["browser"] = _browser_status()
    report["checks"] = config.preflight()
    report["ready"] = all(check["ok"] for check in report["checks"])
    if live:
        report["live"] = live_probe()
        report["live_ok"] = all(entry["ok"] for entry in report["live"].values())
    return report


def _browser_status():
    """Where the browser stands. Uses the fast CDP probe, so it never blocks for 30s."""
    from . import chrome

    reachable, detail = chrome.probe()
    return {
        "cdp": "reachable" if reachable else "unavailable",
        "detail": detail,
        "url": chrome.configured_url(),
        "binary": chrome.find_chrome() or "not found",
        "fix": None if reachable else "Run: jev-browser start",
    }
