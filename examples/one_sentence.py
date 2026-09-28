"""Call the agent from Python with one sentence.

  python examples/one_sentence.py "百度搜索 上海天气"
  python examples/one_sentence.py --json "打开 example.com 把标题列出来"
  python examples/one_sentence.py --plan-only "google latest llm benchmarks"

Environment comes from .env or the shell, exactly as for the CLI.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import config, run_task  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instruction", nargs="+")
    parser.add_argument("--url")
    parser.add_argument("--goal")
    parser.add_argument("--steps", type=int)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config.load_env()
    sentence = " ".join(args.instruction)

    if args.plan_only:
        from jev_ultrafast import parse_instruction

        plan = parse_instruction(sentence, url=args.url, goal=args.goal).as_dict()
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    result = run_task(
        sentence,
        url=args.url,
        goal=args.goal,
        max_actions=args.steps,
        on_step=lambda state: print(f"  step {len(state['history'])} {state['status']}", file=sys.stderr),
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status : {result['status']}")
        print(f"steps  : {result['steps']}   elapsed: {result['elapsed_ms']} ms")
        print(f"final  : {result['page']['url']}")
        print(f"title  : {result['page']['title']}")
        print(f"text   : {(result['page']['text'] or '')[:600]}")
        if result["error"]:
            print(f"error  : {result['error']}")
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
