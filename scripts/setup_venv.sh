#!/usr/bin/env bash
# Create .venv and install Jev Ultrafast reproducibly.
#
#   bash scripts/setup_venv.sh                # dev environment (runtime + pytest + ruff)
#   bash scripts/setup_venv.sh --no-dev       # runtime only
#   bash scripts/setup_venv.sh --exact        # pin every transitive dep from requirements.lock.txt
#   bash scripts/setup_venv.sh --recreate     # delete and rebuild .venv
#   bash scripts/setup_venv.sh --mirror https://pypi.tuna.tsinghua.edu.cn/simple
#
# --exact is what makes a machine reproduce another machine: the lockfile pins the
# full dependency graph, not just the two direct dependencies.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/.venv"
PYTHON="${PYTHON:-}"
MIRROR="${JEV_PIP_MIRROR:-}"
DEV=1
EXACT=0
RECREATE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --python) PYTHON="$2"; shift 2 ;;
    --mirror) MIRROR="$2"; shift 2 ;;
    --no-dev) DEV=0; shift ;;
    --exact) EXACT=1; shift ;;
    --recreate) RECREATE=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

find_python() {
  local candidate
  for candidate in "$PYTHON" python3 python py; do
    [ -n "$candidate" ] || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      echo "$candidate"; return 0
    fi
  done
  return 1
}

PY="$(find_python)" || {
  echo "No Python >= 3.12 found. Install one, or pass --python /path/to/python." >&2
  exit 1
}

if [ "$RECREATE" = 1 ] && [ -d "$VENV" ]; then
  echo "==> removing $VENV"
  rm -rf "$VENV"
fi

if [ ! -d "$VENV" ]; then
  echo "==> creating venv at $VENV with $("$PY" -V 2>&1)"
  "$PY" -m venv "$VENV"
fi

PYBIN="$VENV/Scripts/python.exe"
[ -x "$PYBIN" ] || PYBIN="$VENV/bin/python"

PIP_ARGS=()
[ -n "$MIRROR" ] && PIP_ARGS+=(--index-url "$MIRROR")

echo "==> upgrading pip"
"$PYBIN" -m pip install --upgrade pip "${PIP_ARGS[@]}" --quiet

if [ "$EXACT" = 1 ] && [ -f "$REPO/requirements.lock.txt" ]; then
  echo "==> installing exact pins from requirements.lock.txt"
  "$PYBIN" -m pip install "${PIP_ARGS[@]}" -r "$REPO/requirements.lock.txt"
elif [ "$DEV" = 1 ]; then
  echo "==> installing requirements-dev.txt"
  "$PYBIN" -m pip install "${PIP_ARGS[@]}" -r "$REPO/requirements-dev.txt"
else
  echo "==> installing requirements.txt"
  "$PYBIN" -m pip install "${PIP_ARGS[@]}" -r "$REPO/requirements.txt"
fi

echo "==> installing jev-ultrafast in editable mode"
"$PYBIN" -m pip install "${PIP_ARGS[@]}" --no-deps -e "$REPO" || {
  echo "    editable install failed; run the CLI as: python -m jev_ultrafast.cli run \"...\""
}

if [ ! -f "$REPO/.env" ]; then
  cp "$REPO/.env.example" "$REPO/.env"
  echo "==> created .env from .env.example — add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY"
fi

echo
echo "==> environment check"
"$PYBIN" -m jev_ultrafast.cli doctor || true
echo
echo "Done. Activate with:  source .venv/Scripts/activate   (Git Bash)"
echo
echo "Next:"
echo "  1. jev-browser start        # a browser the harness can drive"
echo "  2. jev-selftest             # prove the stack, no API key needed"
echo "  3. <edit .env>              # then add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY"
echo "  4. jev-run \"百度搜索 上海天气\""
