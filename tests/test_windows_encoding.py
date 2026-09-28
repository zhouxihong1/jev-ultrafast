"""Windows runs Python on the ANSI code page, not UTF-8.

cmd.exe with a Chinese system locale reports cp936, and `Path.read_text()` without an
explicit encoding uses that. `snapshot.js` contains "→" (U+2192), whose UTF-8 bytes cannot
be decoded as GBK, so importing the package used to fail outright outside Git Bash.

These tests spawn a real interpreter with `-X utf8=0` (disabling Python's UTF-8 mode) to
reproduce the cmd environment rather than assuming it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UTF8_OFF = ["-X", "utf8=0"]


def run(args, **kwargs):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("PYTHONUTF8", None)
    env.update(kwargs.pop("env", {}))
    return subprocess.run(  # noqa: S603 - fixed argv, this project's own entry points
        [sys.executable, *args],
        capture_output=True,
        cwd=REPO,
        env=env,
        **kwargs,
    )


def test_snapshot_js_is_utf8_and_contains_the_glyph_that_broke():
    raw = (REPO / "jev_ultrafast" / "snapshot.js").read_bytes()
    assert b"\xe2\x86\x92" in raw, "the arrow that made GBK decoding fail is gone; revisit this test"
    raw.decode("utf-8")  # must not raise


def test_package_imports_with_utf8_mode_disabled():
    result = run([*UTF8_OFF, "-c", "import jev_ultrafast; print('ok')"])
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"ok" in result.stdout


def test_imported_snapshot_matches_the_file():
    result = run(
        [
            *UTF8_OFF,
            "-c",
            "from jev_ultrafast.browser import READ_STATE; print(len(READ_STATE)); print('\\u2192' in READ_STATE)",
        ]
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    length, has_arrow = result.stdout.decode("utf-8").split()
    assert int(length) == len((REPO / "jev_ultrafast" / "snapshot.js").read_text(encoding="utf-8"))
    assert has_arrow == "True"


def test_cli_plan_only_runs_with_utf8_mode_disabled():
    """The exact command from the bug report, minus the browser."""
    result = run([*UTF8_OFF, "-m", "jev_ultrafast.cli", "run", "百度搜索 上海天气", "--plan-only"])
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["engine"] == "baidu" and payload["query"] == "上海天气"


def test_request_encoding_respects_a_non_utf8_console_spec():
    """Some Windows terminals still declare GBK here; the arrow must not reach the encoder."""
    result = run(["-c", "import jev_ultrafast.cli as c; c._configure_console(); print('arrow \u2192 ok')"])
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"arrow" in result.stdout


def test_console_guard_tolerates_an_unencodable_glyph():
    code = "import jev_ultrafast.cli as c; c._configure_console(); print('start \u2192 \U0001f680 end')"
    result = run(["-c", code], env={"PYTHONIOENCODING": "gbk"})
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"start" in result.stdout and b"end" in result.stdout
