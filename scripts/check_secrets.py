"""Refuse to commit a credential.

Run as a pre-commit hook (`.githooks/pre-commit`) it reads what is **staged**, not the
working tree, so it judges exactly what the commit would contain. `--all` scans every
tracked file instead, which is what the test suite uses.

    python scripts/check_secrets.py           # staged content, exits 1 on a hit
    python scripts/check_secrets.py --all     # every tracked file

Patterns are deliberately generic. No real credential belongs in this file: a scanner that
contains the secret it is looking for has already leaked it.
"""

import argparse
import re
import subprocess
import sys

PATTERNS = {
    "OpenAI/Anthropic 风格密钥": r"sk-[A-Za-z0-9\-_]{16,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}",
    "AWS access key": r"AKIA[0-9A-Z]{16}",
    "Google API key": r"AIza[0-9A-Za-z_\-]{35}",
    "Slack token": r"xox[baprs]-[A-Za-z0-9\-]{10,}",
    "私钥文件内容": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "JWT": r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    "env 式长赋值": (
        r"(?im)^\s*(?:export\s+)?[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|APIKEY|API_KEY)"
        r"[A-Z0-9_]*\s*=\s*[\"']?([A-Za-z0-9/+_\-]{20,})"
    ),
    "本机绝对路径": r"[Cc]:\\+Users\\+[A-Za-z]",
}

# A file by these names is a credential whatever it contains.
FORBIDDEN_NAMES = re.compile(
    r"(^|/)(\.env(\..+)?|id_rsa|id_ed25519|\.netrc|credentials|.*\.(pem|key|p12|pfx))$",
    re.IGNORECASE,
)
ALLOWED_EXCEPTION = re.compile(r"\.env\.example$|\.env\.sample$|\.env\.template$", re.IGNORECASE)


def is_forbidden_name(path):
    """A credential-shaped filename refuser. `.env.example` is the one deliberate exemption."""
    return bool(FORBIDDEN_NAMES.search(path)) and not ALLOWED_EXCEPTION.search(path)

TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".md", ".txt", ".yml", ".yaml", ".toml",
    ".cfg", ".ini", ".sh", ".ps1", ".bat", ".html", ".css", ".env", ".example", ".lock", "",
}


def looks_textual(path, data):
    if path.endswith((".png", ".jpg", ".jpeg", ".gif", ".mp4", ".webm", ".ico", ".woff", ".woff2")):
        return False
    return b"\x00" not in data[:4096]


def scan_text(text):
    hits = []
    for label, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text):
            found = match.group(0)
            if match.groups():
                found = match.group(1)
            hits.append((label, found[:12] + "…" if len(found) > 12 else found, match.start()))
    return hits


def scan_paths(pairs):
    """pairs: iterable of (path, bytes). Returns a list of human-readable problems."""
    problems = []
    for path, data in pairs:
        if is_forbidden_name(path):
            problems.append(f"{path}: 文件名本身就是凭据文件，不应入库")
            continue
        if not looks_textual(path, data):
            continue
        text = data.decode("utf-8", "replace")
        for label, found, offset in scan_text(text):
            line = text.count("\n", 0, offset) + 1
            problems.append(f"{path}:{line}: 疑似{label} -> {found}")
    return problems


def staged_pairs():
    names = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout.split("\n")
    for name in names:
        name = name.strip()
        if not name:
            continue
        blob = subprocess.run(["git", "show", f":{name}"], capture_output=True)
        if blob.returncode == 0:
            yield name, blob.stdout


def tracked_pairs():
    names = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout.split("\n")
    for name in names:
        name = name.strip()
        if not name:
            continue
        blob = subprocess.run(["git", "show", f":{name}"], capture_output=True)
        if blob.returncode == 0:
            yield name, blob.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check_secrets", description="Refuse to commit a credential.")
    parser.add_argument("--all", action="store_true", help="Scan every tracked file instead of the staged set.")
    args = parser.parse_args(argv)

    pairs = list(tracked_pairs() if args.all else staged_pairs())
    problems = scan_paths(pairs)
    if not problems:
        print(f"check_secrets: {len(pairs)} 个文件，未发现凭据。")
        return 0

    print("check_secrets: 检测到疑似凭据，已拒绝提交。\n", file=sys.stderr)
    for problem in problems:
        print(f"  x {problem}", file=sys.stderr)
    print(
        "\n请把值移到 .env（已被 .gitignore 忽略），或改用占位符。\n"
        "确属误报时用 `git commit --no-verify` 显式跳过，并在提交说明里写清原因。",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
