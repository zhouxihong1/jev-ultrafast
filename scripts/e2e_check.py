"""End-to-end check of custom endpoints, with no paid API and no real website.

Thin wrapper so the repo script keeps working; the implementation is
``jev_ultrafast.selftest``, which is also what ``jev-selftest`` runs.

  BU_CDP_URL=http://127.0.0.1:9333 <venv>/python scripts/e2e_check.py

Without BU_CDP_URL it starts a dedicated automation browser itself.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import selftest  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-launch", action="store_true", help="Require an already running browser.")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    checks, _result = selftest.run(
        launch_browser=not args.no_launch, headless=args.headless, keep_open=args.keep_open
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
