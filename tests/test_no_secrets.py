"""Nothing in the repository may look like a credential.

Two tests, and the second one is the point: a scanner that reports nothing is worthless
unless it can be shown to report something. `test_the_scanner_actually_catches_a_planted_secret`
plants a credential and asserts it is caught, so a green suite cannot mean a broken regex.
"""

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_scanner():
    spec = importlib.util.spec_from_file_location("check_secrets", REPO / "scripts" / "check_secrets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scanner = load_scanner()


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout
    return [name for name in out.splitlines() if name.strip()]


def test_no_credential_pattern_matches_any_tracked_file():
    problems = scanner.scan_paths(scanner.tracked_pairs())
    assert not problems, "疑似凭据已进入版本库：\n  " + "\n  ".join(problems)


def test_no_credential_like_file_is_tracked():
    tracked = tracked_files()
    offenders = [name for name in tracked if scanner.is_forbidden_name(name)]
    assert not offenders, f"这些文件不该入库：{offenders}"
    assert ".env" not in tracked
    assert ".env.example" in tracked  # 模板是有意入库的，别被上面的规则误伤后又被删掉


def test_the_scanner_actually_catches_a_planted_secret():
    """Every needle is assembled at runtime.

    Written literally, these samples would be caught by the very scanner they are testing -
    which is what happened the first time, and is a decent demonstration that the guard works.
    """
    fake_openai = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    fake_env = "MY_SERVICE_API_KEY=" + "9f8e7d6c5b4a39281706f5e4d3c2b1a0"
    header = "-----BEGIN "  # split so this file holds no literal private-key header
    planted = [
        ("src/config.py", f'client = OpenAI(api_key="{fake_openai}")\n'.encode()),
        ("deploy/settings.py", f"{fake_env}\n".encode()),
        ("notes.md", f"{header}RSA PRIVATE KEY-----\nMIIEow\n".encode()),
        ("deploy/.env.production", b"ANY=thing\n"),
        ("tools/service_account.json", f'{{"private_key": "{header}PRIVATE KEY-----\n"}}\n'.encode()),
    ]
    found = scanner.scan_paths(planted)
    labels = "\n  ".join(found)
    assert any("OpenAI" in hit for hit in found), labels
    assert any("env 式长赋值" in hit for hit in found), labels
    assert any("私钥" in hit for hit in found), labels
    # A credential-shaped filename is refused whatever it holds.
    assert any(".env.production" in hit for hit in found), labels
    # The content rule still runs on ordinary filenames, which is how a key in source is caught.
    assert any("deploy/settings.py:1" in hit for hit in found), labels


def test_placeholders_and_documentation_do_not_trip_it():
    """The example config and the docs are full of empty or fake keys on purpose."""
    harmless = [
        (".env.example", b"TEXT_MODEL_API_KEY=\nTYPESAFE_API_KEY=\nJEV_SERVE_TOKEN=change-me\n"),
        ("docs/configuration.md", "TEXT_MODEL_API_KEY=sk-xxxx  # 占位符\n".encode()),
        ("requirements.lock.txt", b"httpx==0.28.1 --hash=sha256:9f8e7d6c5b4a39281706f5e4d3c2b1a0\n"),
    ]
    assert scanner.scan_paths(harmless) == []


def test_the_guard_is_wired_up_as_a_pre_commit_hook():
    hook = REPO / ".githooks" / "pre-commit"
    assert hook.is_file(), "缺少 .githooks/pre-commit"
    body = hook.read_text(encoding="utf-8")
    assert "check_secrets.py" in body
