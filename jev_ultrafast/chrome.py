"""Find, launch, and stop a Chrome that Browser Harness can actually drive.

A Chrome started the normal way exposes no CDP endpoint, and recent Chrome versions
refuse remote debugging on the default profile. The supported path is a dedicated
profile on its own port:

    chrome --remote-debugging-port=9333 --user-data-dir=<dedicated dir>

``jev-browser start`` does exactly that, remembers the CDP origin in
``~/.jev/browser.json``, and the rest of the package picks it up automatically - so
no environment variable has to be exported by hand.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE = Path.home() / ".jev" / "browser.json"
DEFAULT_PORT = 9333
DEFAULT_PROFILE = Path.home() / ".jev" / "chrome-profile"

WINDOWS_CANDIDATES = (
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
    r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
    r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
    r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
)

POSIX_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)

PATH_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge")


class ChromeError(RuntimeError):
    """Chrome could not be located or started."""


def find_chrome():
    """Absolute path to a Chromium-based browser, or None."""
    override = os.environ.get("JEV_CHROME")
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path)
        raise ChromeError(f"JEV_CHROME points at {override!r}, which is not a file")

    if platform.system() == "Windows":
        for template in WINDOWS_CANDIDATES:
            expanded = os.path.expandvars(template)
            if "%" not in expanded and Path(expanded).is_file():
                return expanded
    else:
        for candidate in POSIX_CANDIDATES:
            if Path(candidate).is_file():
                return candidate

    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def version(base_url, timeout=3.0):
    """Browser version payload from a CDP HTTP origin, or None when unreachable."""
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/json/version", timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def read_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def remember(cdp_url, port=None, profile=None, pid=None, headless=None):
    state = read_state()
    state["cdp_url"] = cdp_url.rstrip("/")
    for key, value in (("port", port), ("profile", profile), ("pid", pid), ("headless", headless)):
        if value is not None:
            state[key] = str(profile) if key == "profile" else value
    write_state(state)
    return state


def forget():
    state = read_state()
    state.pop("cdp_url", None)
    state.pop("pid", None)
    write_state(state)


def configured_url():
    """The CDP origin in use: BU_CDP_URL, then the remembered state, then None."""
    for name in ("BU_CDP_URL", "BU_CDP_WS"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return (read_state().get("cdp_url") or "").strip() or None


def probe(timeout=3.0):
    """(reachable, detail) for the configured CDP origin. Never starts anything."""
    url = configured_url()
    if not url:
        return False, "BU_CDP_URL is not set and no browser was started by jev-browser"
    if url.startswith("ws://") or url.startswith("wss://"):
        return True, f"BU_CDP_WS is set to {url.split('?')[0]} (not probed)"
    origin = url.split("/devtools/")[0].rstrip("/")
    payload = version(origin, timeout)
    if payload:
        return True, f"{payload.get('Browser', 'unknown browser')} at {origin}"
    return False, f"nothing is listening on {origin}"


def apply_env():
    """Export BU_CDP_URL from the remembered state so subprocesses and the harness see it."""
    if os.environ.get("BU_CDP_URL") or os.environ.get("BU_CDP_WS"):
        return os.environ.get("BU_CDP_URL") or os.environ.get("BU_CDP_WS")
    url = (read_state().get("cdp_url") or "").strip()
    if url:
        os.environ["BU_CDP_URL"] = url
        return url
    return None


def launch(port=None, profile=None, headless=False, wait=20.0):
    """Start a dedicated automation Chrome and record its CDP origin."""
    port = int(port or os.environ.get("JEV_CHROME_PORT") or read_state().get("port") or DEFAULT_PORT)
    profile = Path(profile or os.environ.get("JEV_CHROME_PROFILE") or read_state().get("profile") or DEFAULT_PROFILE)
    origin = f"http://127.0.0.1:{port}"

    existing = version(origin)
    if existing:
        remember(origin, port, profile, read_state().get("pid"), headless)
        apply_env()
        return origin, f"already running: {existing.get('Browser', 'Chrome')}"

    binary = find_chrome()
    if not binary:
        raise ChromeError(
            "No Chrome/Chromium/Edge found. Install one, or point JEV_CHROME at the executable, "
            "e.g. JEV_CHROME='C:/Program Files/Google/Chrome/Application/chrome.exe'"
        )

    profile.mkdir(parents=True, exist_ok=True)
    args = [
        binary,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    if headless:
        args.append("--headless=new")
    args.append("about:blank")

    flags = 0
    if platform.system() == "Windows":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(  # noqa: S603 - the binary is resolved locally, args are fixed
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=platform.system() != "Windows",
    )

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if version(origin):
            remember(origin, port, profile, process.pid, headless)
            apply_env()
            return origin, f"started pid {process.pid} ({binary})"
        if process.poll() is not None:
            raise ChromeError(f"Chrome exited immediately with code {process.returncode}; run it by hand to see why")
        time.sleep(0.25)
    raise ChromeError(
        f"Chrome started (pid {process.pid}) but no CDP endpoint appeared on {origin} within {wait:.0f}s. "
        "A firewall or an endpoint-protection agent may be blocking the loopback port."
    )


def stop():
    """Stop the Chrome this tool started. Returns a human-readable result."""
    state = read_state()
    pid = state.get("pid")
    if not pid:
        forget()
        return "nothing recorded to stop"
    killed = False
    if platform.system() == "Windows":
        # No text=True: a non-English Windows console emits non-UTF-8 bytes from taskkill,
        # and decoding them would raise. Only the exit status is used.
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        killed = result.returncode == 0
    else:
        import signal

        try:
            os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
            killed = True
        except (ProcessLookupError, PermissionError):
            killed = False
    forget()
    return f"stopped pid {pid}" if killed else f"pid {pid} was already gone"


def status():
    reachable, detail = probe()
    state = read_state()
    return {
        "reachable": reachable,
        "detail": detail,
        "cdp_url": configured_url(),
        "binary": find_chrome() or "not found",
        "profile": state.get("profile") or str(DEFAULT_PROFILE),
        "port": state.get("port") or DEFAULT_PORT,
        "pid": state.get("pid"),
    }


def export_hint(origin):
    if platform.system() == "Windows":
        shell = "$env:BU_CDP_URL='" + origin + "'"
    else:
        shell = f"export BU_CDP_URL={origin}"
    return shell


if __name__ == "__main__":  # pragma: no cover - convenience only
    print(json.dumps(status(), indent=2))
    sys.exit(0)
