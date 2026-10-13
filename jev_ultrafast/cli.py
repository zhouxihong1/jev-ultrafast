"""Command line entry points.

    jev-run "百度搜索 上海天气"          one sentence, whole run
    jev-run --url https://x --goal "..."  explicit target
    jev-run "..." --plan-only             print the parsed plan, no browser
    jev-run "..." --json                  machine-readable result
    jev-browser start|status|stop         start a browser the harness can drive
    jev-selftest                          prove the whole stack without any key
    jev-doctor                            endpoints, versions, browser status
    jev-serve                             local HTTP API for other programs

Also runnable without installation:  python -m jev_ultrafast.cli run "..."
"""

import argparse
import json
import sys

from . import chrome, config, task


def _configure_console():
    """Never let a console codepage turn a result into a traceback.

    On a Chinese Windows install cmd.exe reports cp936, which cannot encode every glyph a
    page may contain. Replacing the few unencodable characters is better than crashing at
    the end of a successful run. Run `chcp 65001` for full fidelity.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _load_env(args):
    loaded = config.load_env(getattr(args, "env_file", None))
    if loaded and not getattr(args, "quiet", False):
        print(f"env: {loaded}", file=sys.stderr)
    return loaded


def _print_checks(checks, stream=sys.stderr):
    print("\nNot ready to run:", file=stream)
    for check in checks:
        print(f"  x {check['check']}: {check['detail']}", file=stream)
        print(f"    fix: {check['fix']}", file=stream)
    print("\nThen re-run the same command.", file=stream)


def _on_step(state, stream, quiet):
    if quiet or not state["history"]:
        return
    last = state["history"][-1]
    typed = f'  typed="{last["text"]}"' if last.get("text") else ""
    print(
        f'  [{last["step"]:>2}] {last.get("operation") or last["kind"]:<9} '
        f'{last["action"][:64]}{typed}',
        file=stream,
        flush=True,
    )


def _human_report(result):
    plan, page = result["plan"], result["page"]
    lines = [
        f'instruction : {result["instruction"]}',
        f'start url   : {plan["url"]}',
        f'plan source : {plan["source"]}'
        + (f'  (engine={plan["engine"]}, query={plan["query"]!r})' if plan["engine"] else ""),
        f'goal        : {plan["goal"]}',
        f'status      : {result["status"]}',
        f'elapsed     : {result["elapsed_ms"]} ms   steps: {result["steps"]}',
    ]
    if plan["notes"]:
        lines.append("notes       : " + "; ".join(plan["notes"]))
    if result["error"]:
        lines.append(f'error       : {result["error"]}')
    lines.append(f'final url   : {page.get("url")}')
    lines.append(f'final title : {page.get("title")}')
    text = (page.get("text") or "").strip()
    if text:
        lines.append("page text   :")
        lines.extend("  " + row for row in text.splitlines()[:25])
        if page.get("text_truncated"):
            lines.append("  ... (truncated; use --json or --text-limit)")
    return "\n".join(lines)


def run_main(argv=None):
    parser = argparse.ArgumentParser(prog="jev-run", description="Run one browser task from one sentence.")
    parser.add_argument("instruction", nargs="*", help='e.g. "百度搜索 上海天气"')
    parser.add_argument("--url", help="Override the start URL.")
    parser.add_argument("--goal", help="Override the generated goal.")
    parser.add_argument("--steps", type=int, help="Action budget for this run (default JEV_MAX_STEPS or 60).")
    parser.add_argument("--text-limit", type=int, default=8000, help="Characters of final page text to return.")
    parser.add_argument("--record", help="Directory for screenshot frames.")
    parser.add_argument("--screenshots", action="store_true", help="Capture screenshots during the loop.")
    parser.add_argument("--keep-open", action="store_true", help="Leave the browser tab open when finished.")
    parser.add_argument(
        "--plan-only", action="store_true", help="Print the parsed plan and exit; no browser, no API call."
    )
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON.")
    parser.add_argument("--extract", help="Write the JSON result to file.")
    parser.add_argument("--env-file", help="Explicit .env path.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output on stderr.")
    parser.add_argument(
        "--launch-browser", action="store_true", help="Start a dedicated automation browser if none is reachable."
    )
    parser.add_argument("--headless", action="store_true", help="With --launch-browser, run it headless.")
    parser.add_argument("--no-preflight", action="store_true", help="Skip the pre-run readiness check.")
    _configure_console()
    args = parser.parse_args(argv)

    instruction = " ".join(args.instruction).strip()
    _load_env(args)

    try:
        plan = task.parse_instruction(instruction, url=args.url, goal=args.goal)
    except task.InstructionError as exc:
        print(f"jev-run: {exc}", file=sys.stderr)
        return 2

    if args.plan_only:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
        return 0

    if not args.quiet:
        print(f"→ {plan.url}\n  goal: {plan.goal}", file=sys.stderr, flush=True)

    if args.launch_browser and not args.quiet:
        print("checking browser...", file=sys.stderr, flush=True)
    result = task.run_task(
        instruction,
        url=args.url,
        goal=args.goal,
        record_dir=args.record,
        screenshots=args.screenshots,
        max_actions=args.steps,
        text_limit=args.text_limit,
        keep_open=args.keep_open,
        on_step=None if args.quiet else lambda state: _on_step(state, sys.stderr, False),
        preflight=not args.no_preflight,
        launch_chrome=args.launch_browser,
    )
    if args.extract:
        with open(args.extract, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)

    if result["status"] == "setup-required":
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(_human_report(result))
            _print_checks(result["checks"])
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_human_report(result))
    return 0 if result["status"] in {"done", "budget", "stopped"} else 1


def browser_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="jev-browser",
        description="Start a Chrome that Browser Harness can drive, on a dedicated profile and port.",
    )
    parser.add_argument("action", choices=["start", "status", "stop", "restart"], nargs="?", default="status")
    parser.add_argument("--port", type=int, help="CDP port (default 9333).")
    parser.add_argument("--profile", help="User data directory for the dedicated profile.")
    parser.add_argument("--headless", action="store_true", help="Run without a visible window.")
    parser.add_argument("--wait", type=float, default=20.0, help="Seconds to wait for the CDP endpoint.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--env-file")
    _configure_console()
    args = parser.parse_args(argv)
    _load_env(args)

    try:
        if args.action == "stop":
            outcome = chrome.stop()
        elif args.action in {"start", "restart"}:
            if args.action == "restart":
                chrome.stop()
            origin, message = chrome.launch(
                port=args.port, profile=args.profile, headless=args.headless, wait=args.wait
            )
            outcome = (
                f"{message}\n  {chrome.export_hint(origin)}\n"
                f"  remembered in {chrome.STATE}, so jev-run picks it up automatically"
            )
        else:
            state = chrome.status()
            if args.json:
                print(json.dumps(state, ensure_ascii=False, indent=2))
                return 0 if state["reachable"] else 1
            outcome = (
                f"reachable   : {state['reachable']}\n"
                f"detail      : {state['detail']}\n"
                f"cdp url     : {state['cdp_url']}\n"
                f"binary      : {state['binary']}\n"
                f"profile     : {state['profile']}\n"
                f"port / pid  : {state['port']} / {state['pid']}"
            )
    except chrome.ChromeError as exc:
        print(f"jev-browser: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"action": args.action, "result": outcome}, ensure_ascii=False))
        return 0
    print(outcome)
    if args.action == "stop":
        return 0
    return 0 if chrome.status()["reachable"] else 1


def selftest_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="jev-selftest",
        description="Drive a real browser through mock endpoints. No API key, no external site.",
    )
    parser.add_argument("--no-launch", action="store_true", help="Require an already running browser.")
    parser.add_argument("--headless", action="store_true", help="Start the browser headless if it is not running.")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument(
        "--real-decision",
        action="store_true",
        help="Use the configured live decision endpoint for decisions instead of the mock.",
    )
    parser.add_argument("--env-file")
    _configure_console()
    args = parser.parse_args(argv)
    _load_env(args)

    from . import selftest

    checks, _result = selftest.run(
        launch_browser=not args.no_launch,
        headless=args.headless,
        keep_open=args.keep_open,
        real_decision=args.real_decision,
    )
    if not any(checks.values()):
        print("\nNothing passed. Check the errors above, then: jev-doctor", file=sys.stderr)
    return 0 if all(checks.values()) else 1


def doctor_main(argv=None):
    parser = argparse.ArgumentParser(prog="jev-doctor", description="Show endpoints, versions, and browser status.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--live", action="store_true", help="Make one minimal real call per endpoint.")
    parser.add_argument("--env-file")
    _configure_console()
    args = parser.parse_args(argv)
    _load_env(args)
    report = task.doctor(live=args.live)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("config_ok"):
        return 1
    if args.live and not report.get("live_ok"):
        print("\nAn endpoint is configured but not answering:", file=sys.stderr)
        for name, entry in report["live"].items():
            if not entry["ok"]:
                print(f"  x {name}: {entry['detail']}", file=sys.stderr)
        return 1
    return 0 if report.get("ready") else 2


def serve_main(argv=None):
    """Local HTTP API: POST /run {"instruction": "..."} so any language can call the agent."""
    import secrets
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse

    parser = argparse.ArgumentParser(prog="jev-serve", description="Expose the agent over localhost HTTP.")
    parser.add_argument("--host", default=config.env("JEV_SERVE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(config.env("JEV_SERVE_PORT", "8787")))
    parser.add_argument("--token", default=config.env("JEV_SERVE_TOKEN"))
    parser.add_argument("--env-file")
    _configure_console()
    args = parser.parse_args(argv)

    _load_env(args)
    token = args.token or secrets.token_urlsafe(24)
    lock = threading.Lock()
    origin = f"http://{args.host}:{args.port}"

    class Handler(BaseHTTPRequestHandler):
        server_version = "jev-ultrafast"

        def _reply(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == "/health":
                return self._reply(200, {"ok": True, "service": "jev-ultrafast", "config": config.summary()})
            self._reply(404, {"error": "Use POST /run or GET /health"})

        def do_POST(self):
            if urlparse(self.path).path != "/run":
                return self._reply(404, {"error": "Unknown path"})
            if self.headers.get("Authorization") != f"Bearer {token}":
                return self._reply(401, {"error": "Send Authorization: Bearer <token>"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 65536:
                return self._reply(400, {"error": "Invalid request size"})
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                return self._reply(400, {"error": "Body must be JSON"})
            if not lock.acquire(blocking=False):
                return self._reply(409, {"error": "A run is already in progress"})
            try:
                result = task.run_task(
                    body.get("instruction", ""),
                    url=body.get("url"),
                    goal=body.get("goal"),
                    max_actions=body.get("steps"),
                    text_limit=int(body.get("text_limit", 8000)),
                    screenshots=bool(body.get("screenshots")),
                    launch_chrome=bool(body.get("launch_browser")),
                )
                self._reply(503 if result["status"] == "setup-required" else 200, result)
            except task.InstructionError as exc:
                self._reply(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - reported to the caller as JSON
                self._reply(500, {"error": f"{type(exc).__name__}: {exc}"})
            finally:
                lock.release()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"jev-serve on {origin}\n  token: {token}\n  POST /run  {{'instruction': '百度搜索 上海天气'}}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def ui_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="jev-ui",
        description="Open a live inspector for the one-sentence flow.",
    )
    parser.add_argument("--host", default=config.env("JEV_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(config.env("JEV_UI_PORT", "8788")))
    parser.add_argument(
        "--launch-browser", action="store_true", help="Start a browser automatically if none is reachable."
    )
    parser.add_argument("--headless", action="store_true", help="With --launch-browser, run it headless.")
    parser.add_argument("--open", action="store_true", help="Open the page in the default browser.")
    parser.add_argument("--instruction", help="Pre-fill the instruction box without running it.")
    parser.add_argument("--env-file")
    _configure_console()
    args = parser.parse_args(argv)
    _load_env(args)

    from . import ui

    return ui.serve(
        host=args.host,
        port=args.port,
        launch_browser=args.launch_browser,
        headless=args.headless,
        open_browser=args.open,
        instruction=args.instruction or "",
    )


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {
        "run": run_main,
        "doctor": doctor_main,
        "serve": serve_main,
        "browser": browser_main,
        "selftest": selftest_main,
        "ui": ui_main,
    }
    if argv and argv[0] in commands:
        return commands[argv.pop(0)](argv)
    return run_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
