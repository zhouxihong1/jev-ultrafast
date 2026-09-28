"""Local stand-in for the two remote endpoints, plus the fixture page.

The implementation lives in ``jev_ultrafast.selftest`` so that ``jev-selftest`` works
from an installed venv too. This wrapper keeps the standalone script working:

  python scripts/mock_provider.py --port 8790
"""

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast.selftest import start_mock  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    port = start_mock(args.port)
    print(f"mock provider on http://127.0.0.1:{port}", flush=True)
    print(f"  Jev  : http://127.0.0.1:{port}/v1/systemone")
    print(f"  Text : http://127.0.0.1:{port}/mock/chat/completions")
    print(f"  Page : http://127.0.0.1:{port}/fixture.html?scenario=travel", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
