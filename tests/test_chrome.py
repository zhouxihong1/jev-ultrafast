"""The browser launcher is what makes a fresh venv usable; its pieces are tested offline."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jev_ultrafast import chrome

# Captured at import time, before the hermetic fixture replaces them.
REAL_WRITE_STATE = chrome.write_state
REAL_READ_STATE = chrome.read_state


class VersionHandler(BaseHTTPRequestHandler):
    payload = {"Browser": "Chrome/144.0.0.0", "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/browser/x"}

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/json/version":
            body = json.dumps(self.payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def fake_cdp():
    server = ThreadingHTTPServer(("127.0.0.1", 0), VersionHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_version_reads_a_cdp_origin(fake_cdp):
    assert chrome.version(fake_cdp)["Browser"].startswith("Chrome/")


def test_version_returns_none_when_nothing_listens():
    assert chrome.version("http://127.0.0.1:9", timeout=0.5) is None


def test_probe_explains_what_is_missing(monkeypatch):
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    reachable, detail = chrome.probe()
    assert reachable is False
    assert "jev-browser" in detail


def test_probe_reports_the_running_browser(fake_cdp, monkeypatch):
    monkeypatch.setenv("BU_CDP_URL", fake_cdp)
    reachable, detail = chrome.probe()
    assert reachable is True and "Chrome/144" in detail


def test_probe_accepts_a_websocket_url_without_http_probing(monkeypatch):
    monkeypatch.setenv("BU_CDP_WS", "ws://127.0.0.1:9/devtools/browser/x")
    reachable, detail = chrome.probe()
    assert reachable is True and "BU_CDP_WS" in detail


def test_configured_url_prefers_the_environment_over_saved_state(monkeypatch):
    monkeypatch.setattr(chrome, "read_state", lambda: {"cdp_url": "http://127.0.0.1:1111"})
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    assert chrome.configured_url() == "http://127.0.0.1:1111"
    monkeypatch.setenv("BU_CDP_URL", "http://127.0.0.1:2222")
    assert chrome.configured_url() == "http://127.0.0.1:2222"


def test_apply_env_exports_the_saved_origin(monkeypatch):
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    monkeypatch.setattr(chrome, "read_state", lambda: {"cdp_url": "http://127.0.0.1:3333"})
    assert chrome.apply_env() == "http://127.0.0.1:3333"
    import os

    assert os.environ["BU_CDP_URL"] == "http://127.0.0.1:3333"


def test_apply_env_leaves_an_explicit_value_alone(monkeypatch):
    monkeypatch.setenv("BU_CDP_URL", "http://127.0.0.1:4444")
    monkeypatch.setattr(chrome, "read_state", lambda: {"cdp_url": "http://127.0.0.1:3333"})
    assert chrome.apply_env() == "http://127.0.0.1:4444"


def test_find_chrome_honours_the_override(monkeypatch, tmp_path):
    binary = tmp_path / "chrome.exe"
    binary.write_bytes(b"")
    monkeypatch.setenv("JEV_CHROME", str(binary))
    assert chrome.find_chrome() == str(binary)


def test_find_chrome_rejects_a_bad_override(monkeypatch, tmp_path):
    monkeypatch.setenv("JEV_CHROME", str(tmp_path / "missing.exe"))
    with pytest.raises(chrome.ChromeError, match="JEV_CHROME"):
        chrome.find_chrome()


def test_state_round_trip(monkeypatch, tmp_path):
    state_file = tmp_path / "browser.json"
    monkeypatch.setattr(chrome, "STATE", state_file)
    monkeypatch.setattr(chrome, "write_state", REAL_WRITE_STATE)
    monkeypatch.setattr(chrome, "read_state", lambda: json.loads(state_file.read_text()) if state_file.exists() else {})
    chrome.remember("http://127.0.0.1:9333", port=9333, profile=Path("/tmp/p"), pid=42)
    saved = json.loads(state_file.read_text())
    assert saved["cdp_url"] == "http://127.0.0.1:9333" and saved["pid"] == 42
    chrome.forget()
    assert "cdp_url" not in json.loads(state_file.read_text())


def test_launch_reuses_an_origin_that_is_already_up(fake_cdp, monkeypatch, tmp_path):
    monkeypatch.setenv("JEV_CHROME", "/definitely/not/needed")
    monkeypatch.setattr(chrome, "STATE", tmp_path / "browser.json")
    monkeypatch.setattr(chrome, "write_state", REAL_WRITE_STATE)
    origin, message = chrome.launch(port=int(fake_cdp.rsplit(":", 1)[1]), profile=tmp_path / "profile")
    assert origin == fake_cdp
    assert message.startswith("already running")


def test_launch_without_a_browser_binary_explains_the_fix(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome, "STATE", tmp_path / "browser.json")
    monkeypatch.setattr(chrome, "write_state", REAL_WRITE_STATE)
    monkeypatch.setattr(chrome, "version", lambda *_a, **_k: None)
    monkeypatch.setattr(chrome, "find_chrome", lambda: None)
    with pytest.raises(chrome.ChromeError, match="JEV_CHROME"):
        chrome.launch(port=1, profile=tmp_path / "p", wait=0.1)


def test_export_hint_is_shell_specific():
    hint = chrome.export_hint("http://127.0.0.1:9333")
    assert "BU_CDP_URL" in hint and "http://127.0.0.1:9333" in hint
