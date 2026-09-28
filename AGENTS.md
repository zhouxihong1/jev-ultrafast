# Jev Ultrafast

Read README.md before editing. Keep the loop small: page -> indexed elements -> operation + target -> execution.

- The input is one natural-language goal. Do not add site-specific plans or hardcoded field values.
- TypeSafe chooses an operation and operation-specific target heads in one request. Consume only the selected operation's target.
- Targets must map to observed elements and supported operations. Never let the model emit selectors or executable code.
- TYPE_TEXT invokes the text LLM. Cache a stale retry's value only while its entire helper input is identical.
- Never retry a browser mutation. Log execution before observing its result.
- Screenshots are optional; the model does not consume them. Keep demonstration footage at its original speed.
- Keep credentials server-side and .env ignored. Tests must not call paid APIs.
- Verify actual final outcomes independently. A DONE choice is not proof of success.
- Keep examples, README claims, raw evidence, and model-call counts consistent.
- Do not commit or push unless the user requests it.

## Endpoints

Every host, path, model name, header, and timeout is resolved in `jev_ultrafast/config.py`. Do not
reintroduce a literal provider URL, and do not read `os.environ` for configuration outside that
module. New settings need a default, an entry in `.env.example`, a row in `docs/configuration.md`,
and a test in `tests/test_config.py`.

- The Jev decision endpoint: `TYPESAFE_URL`, or `TYPESAFE_BASE_URL` + `TYPESAFE_PATH`.
- The TYPE_TEXT helper: `TEXT_MODEL_URL`, or `TEXT_MODEL_BASE_URL` + `TEXT_MODEL_PATH`, plus
  `TEXT_MODEL_PROVIDER` presets for the common providers.

## Entry points

`jev_ultrafast/task.py` owns sentence → URL + goal parsing and the `run_task` result contract.
`jev_ultrafast/cli.py` is the only place that prints; keep the library silent. `jev_ultrafast/ui.py`
serves the live inspector and must not import a browser at module level. Parsing changes need a case
in `tests/test_task.py`; UI changes need a case in `tests/test_ui.py`.

Commands: `jev-run`, `jev-ui`, `jev-browser`, `jev-selftest`, `jev-doctor`, `jev-serve`.

## Screenshots are for people, never for the loop

The model decides from the structured element table. Anything that serves the inspector - the
screenshot in `browser_operation` above all - must degrade instead of failing the run. A capture that
times out costs the picture and nothing else. `live_state` must hand the page a `data:` URL, not the
executor's raw base64.

## Failures must be actionable

`config.preflight()` returns check/ok/detail/fix rows for the two endpoints and the browser.
`run_task` runs it before touching the browser and returns `status="setup-required"` with those rows
rather than raising. Never let a missing key or an undrivable browser surface as a timeout: a fresh
checkout must fail in about a second and say which command fixes it. `jev_ultrafast/chrome.py` owns
browser discovery and the dedicated-profile launch; its CDP probe must stay fast and must never
start anything.

Checks: `pytest -q`, `ruff check .`, `node --check jev_ultrafast/static/app.js`, `node --check jev_ultrafast/snapshot.js`.

