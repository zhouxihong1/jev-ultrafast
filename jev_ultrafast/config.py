"""One place for every endpoint, credential, and timeout.

Nothing in this package hardcodes a provider host. Both the Jev decision endpoint
(TypeSafe) and the TYPE_TEXT helper endpoint are resolved here, so they can be
pointed at a proxy, a self-hosted gateway, or an offline vLLM box without touching
the agent loop.

Resolution order for every value: explicit environment variable > provider preset
(TEXT_MODEL_PROVIDER) > built-in default.
"""

import json
import os
from pathlib import Path

# --- Jev decision endpoint (TypeSafe) -------------------------------------------------

DEFAULT_TYPESAFE_BASE_URL = "https://api.typesafe.ai"
DEFAULT_TYPESAFE_PATH = "/v1/systemone"
DEFAULT_TYPESAFE_MODEL = "jev-latest"
DEFAULT_TYPESAFE_TIMEOUT = 25.0

# --- Jev decision endpoint, classifier wire format -------------------------------------
# Same model (jev-1.13.0, provider typesafe), simpler protocol: {input, labels} -> {label}.
# Anonymous traffic is allowed but ONLY over a direct connection; through a proxy the API
# answers "Anonymous proxy traffic requires a funded API key".

DEFAULT_CLASSIFIER_URL = "https://classifier.dev/"
DEFAULT_CLASSIFIER_TIMEOUT = 25.0
DEFAULT_CLASSIFIER_MAX_INPUT = 24000

# --- TEXT_TEXT helper endpoint (OpenAI-compatible chat completions) --------------------

DEFAULT_TEXT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TEXT_PATH = "/chat/completions"
DEFAULT_TEXT_MODEL = "inception/mercury-2.5"
DEFAULT_TEXT_TIMEOUT = 30.0

# name -> (base_url, model, reasoning default or None, key required)
PROVIDER_PRESETS = {
    "openrouter": ("https://openrouter.ai/api/v1", "inception/mercury-2.5", None, True),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", None, True),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat", {"thinking": {"type": "disabled"}}, True),
    "siliconflow": ("https://api.siliconflow.cn/v1", "Qwen/Qwen3-8B", None, True),
    "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", None, True),
    "moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-8k", None, True),
    "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash", None, True),
    "ollama": ("http://127.0.0.1:11434/v1", "qwen2.5:7b", {"reasoning": {"enabled": False}}, False),
    "vllm": ("http://127.0.0.1:8000/v1", "Qwen/Qwen3-8B", {"reasoning": {"enabled": False}}, False),
    "lmstudio": ("http://127.0.0.1:1234/v1", "local-model", {"reasoning": {"enabled": False}}, False),
}

_LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")


class ConfigError(ValueError):
    """A required setting is missing or malformed."""


def env(name, default=None):
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def env_bool(name, default=False):
    value = env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_float(name, default):
    value = env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {value!r}") from None


def env_json(name, default=None):
    """Parse a JSON object from the environment, e.g. extra headers."""
    value = env(name)
    if value is None:
        return dict(default or {})
    try:
        parsed = json.loads(value)
    except ValueError:
        raise ConfigError(f"{name} must be valid JSON, got {value!r}") from None
    if not isinstance(parsed, dict):
        raise ConfigError(f"{name} must be a JSON object, got {type(parsed).__name__}")
    return {str(k): str(v) for k, v in parsed.items()}


def provider():
    """The active TEXT_MODEL_PROVIDER preset, or None when unset."""
    name = (env("TEXT_MODEL_PROVIDER", "") or "").lower()
    if not name:
        return None
    if name not in PROVIDER_PRESETS:
        known = ", ".join(sorted(PROVIDER_PRESETS))
        raise ConfigError(f"Unknown TEXT_MODEL_PROVIDER {name!r}. Known presets: {known}")
    return name


def join(base, path):
    """Append a path to a base URL. An absolute path wins over the base."""
    if path.startswith(("http://", "https://")):
        return path
    if not base:
        raise ConfigError("A base URL is required when the path is relative")
    return base.rstrip("/") + "/" + path.lstrip("/")


def is_local(url):
    return any(host in url for host in _LOCAL_HOSTS)


# --- Jev / TypeSafe --------------------------------------------------------------------


def backend():
    """Which wire format the Jev decision step speaks: 'typesafe' or 'classifier'."""
    name = (env("JEV_BACKEND", "typesafe") or "typesafe").lower()
    if name not in {"typesafe", "classifier"}:
        raise ConfigError(f"Unknown JEV_BACKEND {name!r}. Use 'typesafe' or 'classifier'.")
    return name


def classifier_url():
    return env("CLASSIFIER_URL", DEFAULT_CLASSIFIER_URL)


def classifier_key():
    return env("CLASSIFIER_API_KEY", "") or ""


def classifier_tier():
    return env("CLASSIFIER_TIER", "") or None


def classifier_timeout():
    return env_float("CLASSIFIER_TIMEOUT", DEFAULT_CLASSIFIER_TIMEOUT)


def classifier_max_input():
    return int(env_float("CLASSIFIER_MAX_INPUT", DEFAULT_CLASSIFIER_MAX_INPUT))


def classifier_trust_env_proxy():
    """Off by default: a proxy turns the free-anonymous allowance into a 403.

    Set CLASSIFIER_USE_ENV_PROXY=1 only when you have a funded key and really need a proxy.
    """
    return env_bool("CLASSIFIER_USE_ENV_PROXY")


def classifier_summary():
    return {
        "backend": backend(),
        "url": classifier_url(),
        "tier": classifier_tier() or "default",
        "timeout_s": classifier_timeout(),
        "key_set": bool(classifier_key()),
        "trust_env_proxy": classifier_trust_env_proxy(),
        "max_input_chars": classifier_max_input(),
    }


def decision_summary():
    """Whichever decision backend is active, described the same way."""
    if backend() == "classifier":
        return classifier_summary()
    reported = typesafe_summary()
    return {"backend": "typesafe", **reported}


def typesafe_url():
    """Absolute endpoint for the Jev decision request. TYPESAFE_URL wins outright."""
    override = env("TYPESAFE_URL")
    if override:
        return override
    return join(
        env("TYPESAFE_BASE_URL", DEFAULT_TYPESAFE_BASE_URL),
        env("TYPESAFE_PATH", DEFAULT_TYPESAFE_PATH),
    )


def typesafe_key():
    key = env("TYPESAFE_API_KEY")
    if not key and not env_bool("TYPESAFE_ALLOW_NO_KEY"):
        raise ConfigError(
            "TYPESAFE_API_KEY is not set. Export it, add it to .env, or set "
            "TYPESAFE_ALLOW_NO_KEY=1 when pointing TYPESAFE_BASE_URL at a local gateway."
        )
    return key or ""


def typesafe_model():
    return env("TYPESAFE_MODEL", DEFAULT_TYPESAFE_MODEL)


def typesafe_timeout():
    return env_float("TYPESAFE_TIMEOUT", DEFAULT_TYPESAFE_TIMEOUT)


def typesafe_headers():
    return {"Authorization": f"Bearer {typesafe_key()}", **env_json("TYPESAFE_EXTRA_HEADERS")}


def typesafe_summary():
    return {
        "url": typesafe_url(),
        "model": typesafe_model(),
        "timeout_s": typesafe_timeout(),
        "key_set": bool(env("TYPESAFE_API_KEY")),
        "extra_headers": sorted(env_json("TYPESAFE_EXTRA_HEADERS")),
    }


# --- TEXT_MODEL ------------------------------------------------------------------------


def text_url():
    """Absolute chat-completions endpoint. TEXT_MODEL_URL wins outright."""
    override = env("TEXT_MODEL_URL")
    if override:
        return override
    return join(
        env("TEXT_MODEL_BASE_URL", _preset_base()),
        env("TEXT_MODEL_PATH", DEFAULT_TEXT_PATH),
    )


def _preset_base():
    name = provider()
    return PROVIDER_PRESETS[name][0] if name else DEFAULT_TEXT_BASE_URL


def _preset_model():
    name = provider()
    return PROVIDER_PRESETS[name][1] if name else DEFAULT_TEXT_MODEL


def text_model():
    return env("TEXT_MODEL", _preset_model())


def text_key_optional():
    name = provider()
    preset_optional = name is not None and not PROVIDER_PRESETS[name][3]
    return env_bool("TEXT_MODEL_ALLOW_NO_KEY") or preset_optional or is_local(text_url())


def text_key():
    key = env("TEXT_MODEL_API_KEY")
    if not key:
        if text_key_optional():
            return "not-needed"
        raise ConfigError(
            "TYPE_TEXT needs TEXT_MODEL_API_KEY; no text is hardcoded or guessed by the executor. "
            "Set TEXT_MODEL_PROVIDER to a local preset (ollama/vllm/lmstudio) for keyless servers."
        )
    return key


def text_timeout():
    return env_float("TEXT_MODEL_TIMEOUT", DEFAULT_TEXT_TIMEOUT)


def text_max_tokens():
    return int(env_float("TEXT_MODEL_MAX_TOKENS", 1024))


def text_temperature():
    """Unset by default: the provider's own sampling settings stay in charge."""
    return env_float("TEXT_MODEL_TEMPERATURE", None)


def text_headers():
    style = (env("TEXT_MODEL_AUTH_STYLE", "bearer") or "bearer").lower()
    key = text_key()
    auth = {
        "bearer": {"Authorization": f"Bearer {key}"},
        "api-key": {"api-key": key},
        "x-api-key": {"x-api-key": key},
        "none": {},
    }
    if style not in auth:
        raise ConfigError(
            f"Unknown TEXT_MODEL_AUTH_STYLE {style!r}. Use one of: {', '.join(sorted(auth))}"
        )
    return {**auth[style], **env_json("TEXT_MODEL_EXTRA_HEADERS")}


def text_reasoning():
    """Provider-specific reasoning switch. Unset keeps the provider's own default."""
    raw = env("TEXT_MODEL_REASONING")
    if raw is None:
        name = provider()
        if name:
            return dict(PROVIDER_PRESETS[name][2] or {})
        return {"thinking": {"type": "disabled"}} if "api.deepseek.com/" in text_url() else {
            "reasoning": {"effort": "low"}
        }
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise ConfigError("TEXT_MODEL_REASONING is neither a preset name nor valid JSON") from None
        if not isinstance(parsed, dict):
            raise ConfigError("TEXT_MODEL_REASONING JSON must be an object")
        return parsed
    lowered = raw.lower()
    if lowered == "none":
        return {"reasoning": {"enabled": False}}
    if lowered == "off":
        return {}
    if lowered in {"low", "medium", "high", "minimal"}:
        return {"reasoning": {"effort": lowered}}
    raise ConfigError(
        "TEXT_MODEL_REASONING must be none, off, low, medium, high, minimal, or a JSON object"
    )


def text_json_mode():
    """Whether to send response_format=json_object. Some providers reject the field."""
    mode = (env("TEXT_MODEL_JSON_MODE", "auto") or "auto").lower()
    if mode in {"on", "true", "1", "yes"}:
        return True
    if mode in {"off", "false", "0", "no"}:
        return False
    if mode != "auto":
        raise ConfigError("TEXT_MODEL_JSON_MODE must be auto, on, or off")
    # Default keeps upstream behaviour; opt out only when a provider rejects the field.
    return True


def text_summary():
    return {
        "url": text_url(),
        "model": text_model(),
        "timeout_s": text_timeout(),
        "provider": provider(),
        "key_set": bool(env("TEXT_MODEL_API_KEY")),
        "key_required": not text_key_optional(),
        "auth_style": (env("TEXT_MODEL_AUTH_STYLE", "bearer") or "bearer").lower(),
        "reasoning": text_reasoning(),
        "json_mode": text_json_mode(),
        "extra_headers": sorted(env_json("TEXT_MODEL_EXTRA_HEADERS")),
    }


# --- .env loading ----------------------------------------------------------------------


def candidate_env_files():
    """Where a .env may live, most specific first."""
    explicit = env("JEV_ENV_FILE")
    paths = []
    if explicit:
        paths.append(Path(explicit))
    paths.append(Path.cwd() / ".env")
    paths.append(Path(__file__).resolve().parent.parent / ".env")
    paths.append(Path.home() / ".jev" / ".env")
    seen, unique = set(), []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def load_env(explicit=None):
    """Populate os.environ from the first existing .env without overriding real env vars."""
    paths = [Path(explicit)] if explicit else candidate_env_files()
    loaded = None
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            name, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(name.strip(), value)
        loaded = path
        break
    try:
        from . import chrome

        chrome.apply_env()
    except Exception:  # noqa: BLE001 - a missing state file must never block a run
        pass
    return loaded


# --- preflight -------------------------------------------------------------------------


def preflight(need_text_model=True, probe_browser=True):
    """Everything that would stop a run, reported before any request or browser call.

    Returns a list of dicts with check/ok/detail/fix. Empty means ready.
    """
    checks = []
    try:
        if backend() == "classifier":
            reported = classifier_summary()
            ok = True
            detail = f"{reported['url']} (tier {reported['tier']})"
            if reported["trust_env_proxy"]:
                detail += " - sent through a proxy; anonymous use needs a direct connection"
                ok = bool(reported["key_set"])
            checks.append(
                {
                    "check": "jev endpoint",
                    "ok": ok,
                    "detail": detail,
                    "fix": (
                        "Drop CLASSIFIER_USE_ENV_PROXY, or set CLASSIFIER_API_KEY to a funded key. "
                        "Anonymous classifier.dev traffic is rejected when it arrives via a proxy."
                    ),
                }
            )
        else:
            reported = typesafe_summary()
            ok = bool(reported["key_set"]) or env_bool("TYPESAFE_ALLOW_NO_KEY")
            detail = f"{reported['url']} (model {reported['model']})"
            if not ok:
                detail += " - TYPESAFE_API_KEY is not set"
            checks.append(
                {
                    "check": "jev endpoint",
                    "ok": ok,
                    "detail": detail,
                    "fix": (
                        "Use the keyless classifier backend instead (JEV_BACKEND=classifier), "
                        "or put TYPESAFE_API_KEY in .env, or set TYPESAFE_ALLOW_NO_KEY=1 when "
                        "TYPESAFE_BASE_URL points at a keyless local gateway."
                    ),
                }
            )
    except ConfigError as exc:
        checks.append(
            {
                "check": "jev endpoint",
                "ok": False,
                "detail": str(exc),
                "fix": "Fix the JEV_*/TYPESAFE_* values in .env.",
            }
        )

    try:
        reported = text_summary()
        ok = bool(reported["key_set"]) or not reported["key_required"]
        detail = f"{reported['url']} (model {reported['model']})"
        if not ok:
            detail += " - TEXT_MODEL_API_KEY is not set"
        if not need_text_model:
            detail += " [only needed for TYPE_TEXT steps]"
        checks.append(
            {
                "check": "text model endpoint",
                "ok": ok,
                "detail": detail,
                "fix": (
                    "Put TEXT_MODEL_API_KEY in .env, or point TEXT_MODEL_BASE_URL/TEXT_MODEL_PROVIDER "
                    "at a local server (ollama, vllm, lmstudio) which needs no key."
                ),
            }
        )
    except ConfigError as exc:
        checks.append(
            {
                "check": "text model endpoint",
                "ok": False,
                "detail": str(exc),
                "fix": "Fix the TEXT_MODEL_* values in .env.",
            }
        )

    if probe_browser:
        try:
            from . import chrome

            reachable, detail = chrome.probe()
            checks.append(
                {
                    "check": "browser (CDP)",
                    "ok": reachable,
                    "detail": detail,
                    "fix": (
                        "Run: jev-browser start    (it launches a dedicated Chrome on port 9333 "
                        "and remembers it, then re-run your command)"
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            checks.append(
                {
                    "check": "browser (CDP)",
                    "ok": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                    "fix": "Run: jev-browser start",
                }
            )
    return checks


def summary():
    return {"jev": decision_summary(), "text_model": text_summary()}


# --- loop budget -----------------------------------------------------------------------


def max_steps():
    """Action budget for one run. JEV_MAX_STEPS overrides the packaged default."""
    from .questions import MAX_STEPS

    value = env("JEV_MAX_STEPS")
    if value is None:
        return MAX_STEPS
    try:
        return max(1, int(value))
    except ValueError:
        raise ConfigError(f"JEV_MAX_STEPS must be an integer, got {value!r}") from None
