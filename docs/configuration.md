# Configuration

Everything that points at a network is resolved in `jev_ultrafast/config.py`. Nothing in the
agent loop hardcodes a host, a path, a model name, or a timeout.

Resolution order for every value:

```
explicit environment variable  >  TEXT_MODEL_PROVIDER preset  >  built-in default
```

`.env` files are read with `setdefault`, so a real environment variable always wins over the file.
Search order: `JEV_ENV_FILE` → `./.env` → `<repo>/.env` → `~/.jev/.env`. Only the first file that
exists is loaded. `jev-doctor` prints which one was used.

Run `jev-doctor` at any time to see the effective result:

```bash
jev-doctor
jev-doctor --json | jq '.config'
```

---

## 1. The Jev decision endpoint (TypeSafe)

Called once per decision cycle. Returns one operation plus one operation-specific target head.

### Which protocol: `JEV_BACKEND`

| Value | Endpoint | Key | Requests per decision |
| --- | --- | --- | --- |
| `classifier` (default) | `CLASSIFIER_URL`, default `https://classifier.dev/` | none required | one, plus one more when the chosen operation has several candidate elements |
| `typesafe` | `TYPESAFE_URL`, or `TYPESAFE_BASE_URL` + `TYPESAFE_PATH` | `TYPESAFE_API_KEY` required | one, returning every head at once |

Both serve the same model — classifier.dev reports `"model": "jev-1.13.0"`, `"provider": "typesafe"`.

#### classifier.dev, the keyless path

```bash
JEV_BACKEND=classifier
CLASSIFIER_URL=https://classifier.dev/
```

Restrictions found by probing the live API, each of which the adapter handles:

| Constraint | Consequence |
| --- | --- |
| Anonymous use is direct-connection only | Through a proxy the API answers `{"code":"proxy_requires_payment"}`. This endpoint therefore ignores `HTTP_PROXY`/`HTTPS_PROXY` unless `CLASSIFIER_USE_ENV_PROXY=1`, which then needs a funded key. |
| `input` must be a single string | The page, element table, goal, and question are composed into one prompt. |
| At least two labels | An operation with a single candidate element is answered locally, with no request: one candidate is not a question anyway. |
| One label per response | The operation and its target become two requests. |
| 8 KB of input is accepted | `CLASSIFIER_MAX_INPUT` (default 24000 chars) trims only the page text; the rules, element table, and question always survive whole. |

Labels carry their own description, e.g. `3 | [3] button "Find stays"`, and are mapped back by the key before the separator. This matters: with bare indices the model cannot connect a label to a line of the prompt, and target selection degrades into guessing (measured: it clicked the site logo nine times in a row at p≈0.4). With descriptions it picked the right button at p=0.9.

| Variable | Default | Meaning |
| --- | --- | --- |
| `JEV_BACKEND` | `classifier` | `classifier` or `typesafe`. |
| `CLASSIFIER_URL` | `https://classifier.dev/` | The classification endpoint. |
| `CLASSIFIER_API_KEY` | — | Optional. Send a funded key to use a proxy or lift the anonymous allowance. |
| `CLASSIFIER_TIER` | unset | Forwarded as `tier` when set; the API reports `fast` for the default. |
| `CLASSIFIER_TIMEOUT` | `25` | Per-request seconds. |
| `CLASSIFIER_MAX_INPUT` | `24000` | Character budget for the composed prompt. |
| `CLASSIFIER_USE_ENV_PROXY` | `0` | Allow proxy environment variables to apply. |

#### The native TypeSafe protocol

| Variable | Default | Meaning |
| --- | --- | --- |
| `TYPESAFE_API_KEY` | — | Required. Sent as `Authorization: Bearer <key>`. |
| `TYPESAFE_MODEL` | `jev-latest` | Model name in the request body. |
| `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | Scheme + host + optional prefix. |
| `TYPESAFE_PATH` | `/v1/systemone` | Appended to the base URL. |
| `TYPESAFE_URL` | — | Absolute override. Wins over `BASE_URL` + `PATH`. |
| `TYPESAFE_TIMEOUT` | `25` | Per-request seconds. |
| `TYPESAFE_EXTRA_HEADERS` | — | JSON object merged over the Authorization header. |
| `TYPESAFE_ALLOW_NO_KEY` | `0` | Set to `1` to run against a keyless local gateway. |

Pointing at a gateway:

```bash
JEV_BACKEND=typesafe
TYPESAFE_BASE_URL=https://gateway.internal/jev
TYPESAFE_PATH=/v1/systemone
```

Pointing at a mock or a proxy that uses a different auth header:

```bash
JEV_BACKEND=typesafe
TYPESAFE_URL=http://127.0.0.1:8080/mock/systemone
TYPESAFE_EXTRA_HEADERS={"Authorization":"ApiKey abc","X-Tenant":"t1"}
```

The request body is unchanged by any of this: `model`, `state` (page, elements, recent actions), and
`questions`. See `model.choose_typesafe` for the exact shape.

---

## 2. The `TYPE_TEXT` helper endpoint

Only used when the chosen operation is `TYPE_TEXT`. Any OpenAI-compatible
`POST /chat/completions` server works.

| Variable | Default | Meaning |
| --- | --- | --- |
| `TEXT_MODEL_API_KEY` | — | Required unless `key_optional` is true (below). |
| `TEXT_MODEL_BASE_URL` | `https://openrouter.ai/api/v1` | Scheme + host + optional prefix. |
| `TEXT_MODEL_PATH` | `/chat/completions` | Appended to the base URL. |
| `TEXT_MODEL_URL` | — | Absolute override, wins over `BASE_URL` + `PATH`. Use for Azure deployments with query strings. |
| `TEXT_MODEL` | `inception/mercury-2.5` | Model name. |
| `TEXT_MODEL_PROVIDER` | — | Preset that fills base URL, model, and reasoning defaults. |
| `TEXT_MODEL_AUTH_STYLE` | `bearer` | `bearer`, `api-key` (Azure), `x-api-key`, or `none`. |
| `TEXT_MODEL_EXTRA_HEADERS` | — | JSON object merged over the auth header. |
| `TEXT_MODEL_REASONING` | provider default | `none`, `off`, `low`, `medium`, `high`, `minimal`, or a raw JSON object. |
| `TEXT_MODEL_JSON_MODE` | `auto` | `auto`/`on` send `response_format={"type":"json_object"}`; `off` omits it. |
| `TEXT_MODEL_MAX_TOKENS` | `1024` | `max_tokens`. |
| `TEXT_MODEL_TEMPERATURE` | unset | Sent only when set, so the provider default stands otherwise. |
| `TEXT_MODEL_TIMEOUT` | `30` | Per-request seconds. |
| `TEXT_MODEL_ALLOW_NO_KEY` | `0` | Permit an empty key for a self-hosted server. |

### Provider presets

`TEXT_MODEL_PROVIDER` fills any value you have not set explicitly.

| Preset | Base URL | Default model | Key required |
| --- | --- | --- | --- |
| `openrouter` | `https://openrouter.ai/api/v1` | `inception/mercury-2.5` | yes |
| `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` | yes |
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` | yes |
| `siliconflow` | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3-8B` | yes |
| `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | yes |
| `moonshot` | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | yes |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | yes |
| `ollama` | `http://127.0.0.1:11434/v1` | `qwen2.5:7b` | no |
| `vllm` | `http://127.0.0.1:8000/v1` | `Qwen/Qwen3-8B` | no |
| `lmstudio` | `http://127.0.0.1:1234/v1` | `local-model` | no |

A key is also treated as optional whenever the resolved URL points at `127.0.0.1`, `localhost`,
`0.0.0.0`, or `[::1]`.

### Recipes

DeepSeek, reasoning disabled:

```bash
TEXT_MODEL_PROVIDER=deepseek
TEXT_MODEL_API_KEY=sk-...
TEXT_MODEL_REASONING=none
```

Azure OpenAI deployment:

```bash
TEXT_MODEL_URL=https://x.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-06-01
TEXT_MODEL_API_KEY=...
TEXT_MODEL_AUTH_STYLE=api-key
TEXT_MODEL_JSON_MODE=off
```

Local vLLM with the Qwen chat-template thinking switch:

```bash
TEXT_MODEL_PROVIDER=vllm
TEXT_MODEL_REASONING='{"enable_thinking": false}'
```

`TEXT_MODEL_REASONING` accepts either a preset name or a raw JSON object, so any provider-specific
field can be forwarded verbatim.

---

## 3. Runtime

| Variable | Default | Meaning |
| --- | --- | --- |
| `JEV_MAX_STEPS` | `60` | Action budget for one run. |
| `JEV_DEFAULT_SEARCH_ENGINE` | `baidu` | Engine used when a sentence names none. |
| `JEV_ENV_FILE` | — | Explicit `.env` path. |
| `JEV_CHROME` | auto-detected | Path to the browser executable. |
| `JEV_CHROME_PORT` | `9333` | CDP port used by `jev-browser start`. |
| `JEV_CHROME_PROFILE` | `~/.jev/chrome-profile` | Dedicated profile directory. |
| `TYPESAFE_DEMO_PORT` | `8766` | Inspector port. |
| `JEV_SERVE_HOST` / `JEV_SERVE_PORT` | `127.0.0.1` / `8787` | `jev-serve` bind address. |
| `JEV_SERVE_TOKEN` | random | Bearer token required by `POST /run`. |
| `BU_CDP_URL` | — | Browser Harness: CDP origin of a dedicated automation Chrome. |

### The browser

`BU_CDP_URL` matters more than it looks. A Chrome launched the normal way exposes no CDP
endpoint, and recent Chrome versions block remote debugging on the default profile, so
Browser Harness falls back to discovering `DevToolsActivePort` in your everyday profile —
which requires enabling debugging at `chrome://inspect` and approving a per-session prompt.

`jev-browser` skips all of that:

```bash
jev-browser start              # dedicated profile, port 9333, remembered in ~/.jev/browser.json
jev-browser start --headless
jev-browser status
jev-browser stop
```

The remembered origin is applied automatically, so `jev-run` and `jev-selftest` need no
exported variable. `BU_CDP_URL`/`BU_CDP_WS` still win when you set them explicitly, which is
what you want when driving a browser started elsewhere or a remote one.

---

## 4. Checking the wiring

Nothing here makes a paid call.

| Command | What it does |
| --- | --- |
| `jev-ui` | Serves the live inspector on loopback: one sentence in, decisions and actions out. |
| `jev-doctor` | Interpreter, package versions, both effective endpoints, key presence, `.env` used, CDP status, and a `ready` flag with a per-check fix. |
| `jev-doctor --live` | Adds one minimal real call per endpoint. Configured is not the same as working: a gateway can answer `GET /v1/models` while every completion returns HTTP 500. |
| `jev-browser status` | Whether a CDP origin is configured and answering, plus the detected browser and profile. |
| `jev-selftest` | Starts mock endpoints and a local page, then drives a real browser through type → submit → done. No key, no external site. Starts a browser itself when needed. |
| `jev-selftest --real-decision` | Same, but the decision endpoint is the live classifier.dev. Isolates which half of the stack is at fault. |

## The live inspector

```bash
jev-ui --open --launch-browser
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `JEV_UI_HOST` | `127.0.0.1` | Bind address. Loopback only; every `POST` also needs the page's token. |
| `JEV_UI_PORT` | `8788` | Port. |

`GET /` serves the page, `GET /api/state` is what the page polls, `GET /api/meta` describes the
active backend. `POST /api/plan` parses a sentence without starting anything, `POST /api/run` starts
one run, `POST /api/stop` ends the current run after its step. One run at a time; a second gets `409`.

Screenshots are captured with the run (`screenshots=True`) and are for the page only. They are the
reason `browser_operation` had to become fault-tolerant: on a busy renderer
`Page.captureScreenshot` can exceed the harness's 5 s response timeout, and before this the whole run
died with `_IPCResponseTimeout`. A missed capture is retried once, then dropped.

`run_task` runs the static checks before touching the browser and returns `status:
"setup-required"` with a `checks` list instead of launching anything, so a misconfigured
environment fails in about a second with the fix rather than timing out. Pass
`preflight=False` (Python) or `--no-preflight` (CLI) to bypass it, and `--launch-browser` to
start a browser automatically before running.

### Measured behaviour

Live classifier.dev, live text model, dedicated headless Chrome, local fixture page:

| Scenario | Result |
| --- | --- |
| Fill a field, then submit | `done` in 2 steps, 2 classifier calls, 8.7 s |
| Read a keyword field | `TYPE_TEXT` at p=0.99, ~150 ms, 759 input tokens |
| Choose among 3 result links | correct link at p=0.75, 2 calls, 2.2 s |
| `en.wikipedia.org` search | `done` |
| `cn.bing.com` search + submit | `done` in 2 steps, `TYPE_TEXT` then `ENTER`, both at p=1.0 |
| Baidu results page | `blocked` — Baidu serves `百度安全验证` to a fresh headless profile |

## The `ENTER` operation

`CLICK`, `TYPE_TEXT`, `ENTER`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`, `DONE`, `BLOCKED`.

`ENTER` is offered for every editable field, alongside `TYPE_TEXT` and `CLICK`, and is a targeted
operation rather than a global control: Enter has to be pressed in a specific observed field.

It exists because many forms have no visible submit control. Bing is the clearest case — probing its
DOM shows `INPUT#sb_form_go name="Search" size=0x0 vis=false`, so the snapshot correctly drops it as
invisible, while the visible affordance is `LABEL#search_icon`, a bare label. Without `ENTER` the
agent can type the query and then has nothing to submit it with, which it correctly reports as
`blocked` after three actions that changed nothing.

The executor focuses the observed node, verifies `document.activeElement` landed on it, then sends a
real key sequence — `rawKeyDown`, `char` with `text="\r"`, `keyUp`. `Input.insertText` does not
trigger a form submission; only a real key event does. Freshness for `ENTER` is node-scoped like
`CLICK`, so a stale Enter cannot submit a field whose contents changed since the decision.

