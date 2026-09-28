"""Endpoint configuration is the contract that makes this package portable."""

import json

import pytest

from jev_ultrafast import config

# Captured at import time, before the suite-wide autouse stub replaces it.
REAL_PREFLIGHT = config.preflight


def test_typesafe_defaults_point_at_the_hosted_decision_endpoint():
    assert config.typesafe_url() == "https://api.typesafe.ai/v1/systemone"
    assert config.typesafe_model() == "jev-latest"


def test_typesafe_endpoint_is_fully_overridable(monkeypatch):
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:9000/gateway/")
    monkeypatch.setenv("TYPESAFE_PATH", "/v2/decide")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert config.typesafe_url() == "http://127.0.0.1:9000/gateway/v2/decide"


def test_typesafe_absolute_url_wins_over_base_and_path(monkeypatch):
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://example.test/ignored")
    monkeypatch.setenv("TYPESAFE_PATH", "/v1/systemone")
    monkeypatch.setenv("TYPESAFE_URL", "https://proxy.test/custom/endpoint")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert config.typesafe_url() == "https://proxy.test/custom/endpoint"


def test_missing_typesafe_key_is_explicit(monkeypatch):
    with pytest.raises(config.ConfigError, match="TYPESAFE_API_KEY"):
        config.typesafe_key()
    monkeypatch.setenv("TYPESAFE_ALLOW_NO_KEY", "1")
    assert config.typesafe_key() == ""


def test_typesafe_extra_headers_merge_over_the_bearer_token(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret")
    monkeypatch.setenv("TYPESAFE_EXTRA_HEADERS", json.dumps({"Authorization": "Custom abc", "X-Org": "t1"}))
    headers = config.typesafe_headers()
    assert headers["Authorization"] == "Custom abc" and headers["X-Org"] == "t1"


def test_bad_extra_headers_json_is_rejected(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "k")
    monkeypatch.setenv("TEXT_MODEL_EXTRA_HEADERS", "{not json}")
    with pytest.raises(config.ConfigError, match="JSON"):
        config.text_headers()


def test_text_endpoint_defaults_and_overrides(monkeypatch):
    assert config.text_url() == "https://openrouter.ai/api/v1/chat/completions"
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("TEXT_MODEL_PATH", "/chat/completions")
    assert config.text_url() == "http://127.0.0.1:11434/v1/chat/completions"
    monkeypatch.setenv("TEXT_MODEL_URL", "https://x.openai.azure.com/openai/deployments/y/chat/completions?api-version=1")
    assert config.text_url().startswith("https://x.openai.azure.com/openai/deployments/y/chat/completions")


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("deepseek", "https://api.deepseek.com/v1/chat/completions"),
        ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
        ("zhipu", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
        ("ollama", "http://127.0.0.1:11434/v1/chat/completions"),
    ],
)
def test_provider_presets_fill_the_endpoint(monkeypatch, provider, expected):
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", provider)
    assert config.text_url() == expected


def test_explicit_base_url_beats_the_provider_preset(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "deepseek")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "http://gateway.internal/v1")
    assert config.text_url() == "http://gateway.internal/v1/chat/completions"


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "not-a-provider")
    with pytest.raises(config.ConfigError, match="Unknown TEXT_MODEL_PROVIDER"):
        config.text_url()


def test_local_and_preset_providers_do_not_need_a_key(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "ollama")
    assert config.text_key() == "not-needed"
    monkeypatch.delenv("TEXT_MODEL_PROVIDER")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    assert config.text_key_optional() is True


def test_remote_provider_still_requires_a_key(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.example.test/v1")
    assert config.text_key_optional() is False
    with pytest.raises(config.ConfigError, match="TEXT_MODEL_API_KEY"):
        config.text_key()


@pytest.mark.parametrize(
    "style,header",
    [("bearer", "Authorization"), ("api-key", "api-key"), ("x-api-key", "x-api-key")],
)
def test_auth_styles_change_the_header_name(monkeypatch, style, header):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "k")
    monkeypatch.setenv("TEXT_MODEL_AUTH_STYLE", style)
    assert config.text_headers()[header] == ("Bearer k" if style == "bearer" else "k")


def test_auth_style_none_sends_no_credential(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "k")
    monkeypatch.setenv("TEXT_MODEL_AUTH_STYLE", "none")
    assert config.text_headers() == {}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("none", {"reasoning": {"enabled": False}}),
        ("off", {}),
        ("low", {"reasoning": {"effort": "low"}}),
        ('{"enable_thinking": false}', {"enable_thinking": False}),
    ],
)
def test_reasoning_values_are_translated_to_request_fields(monkeypatch, value, expected):
    monkeypatch.setenv("TEXT_MODEL_REASONING", value)
    assert config.text_reasoning() == expected


def test_reasoning_default_follows_the_endpoint(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1")
    assert config.text_reasoning() == {"thinking": {"type": "disabled"}}
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.other.test/v1")
    assert config.text_reasoning() == {"reasoning": {"effort": "low"}}


def test_bad_reasoning_name_is_rejected(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_REASONING", "sometimes")
    with pytest.raises(config.ConfigError, match="TEXT_MODEL_REASONING"):
        config.text_reasoning()


def test_numeric_settings_validate(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_TIMEOUT", "12.5")
    monkeypatch.setenv("TYPESAFE_TIMEOUT", "9")
    monkeypatch.setenv("JEV_MAX_STEPS", "15")
    monkeypatch.setenv("TEXT_MODEL_MAX_TOKENS", "2048")
    assert config.text_timeout() == 12.5
    assert config.typesafe_timeout() == 9
    assert config.max_steps() == 15
    assert config.text_max_tokens() == 2048
    monkeypatch.setenv("JEV_MAX_STEPS", "many")
    with pytest.raises(config.ConfigError, match="JEV_MAX_STEPS"):
        config.max_steps()


def test_load_env_reads_the_file_without_overwriting_real_variables(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\nTYPESAFE_API_KEY=""\nTEXT_MODEL="quoted-model"\nexport TEXT_MODEL_BASE_URL=http://a.test/v1\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TEXT_MODEL", "already-set")
    assert config.load_env(env_file) == env_file
    assert config.env("TEXT_MODEL") == "already-set"
    assert config.text_url() == "http://a.test/v1/chat/completions"


def test_env_file_discovery_order_prefers_an_explicit_path(monkeypatch, tmp_path):
    explicit = tmp_path / "custom.env"
    monkeypatch.setenv("JEV_ENV_FILE", str(explicit))
    assert config.candidate_env_files()[0] == explicit


def test_summary_reports_every_effective_endpoint(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "t")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "x")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.example.test/v1")
    summary = config.summary()
    assert summary["jev"]["backend"] == "typesafe"
    assert summary["jev"]["url"].endswith("/v1/systemone")
    assert summary["jev"]["key_set"] is True
    assert summary["text_model"]["url"] == "https://api.example.test/v1/chat/completions"
    assert summary["text_model"]["model"]


def test_summary_follows_the_active_backend(monkeypatch):
    monkeypatch.setenv("JEV_BACKEND", "classifier")
    assert config.summary()["jev"]["backend"] == "classifier"
    assert config.summary()["jev"]["url"].startswith("https://classifier.dev")


@pytest.mark.parametrize("backend,expected", [("typesafe", "typesafe"), ("CLASSIFIER", "classifier"), ("", "typesafe")])
def test_backend_name_is_normalised(monkeypatch, backend, expected):
    monkeypatch.setenv("JEV_BACKEND", backend)
    assert config.backend() == expected


def test_unknown_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("JEV_BACKEND", "guessy")
    with pytest.raises(config.ConfigError, match="JEV_BACKEND"):
        config.backend()


def test_classifier_defaults_are_keyless_and_proxy_free(monkeypatch):
    monkeypatch.setenv("JEV_BACKEND", "classifier")
    assert config.classifier_key() == ""
    assert config.classifier_trust_env_proxy() is False
    assert config.classifier_url() == "https://classifier.dev/"
    assert config.classifier_max_input() == 24000


def test_classifier_proxy_use_is_reported_as_unready_without_a_key(monkeypatch):
    """classifier.dev rejects anonymous traffic that arrives through a proxy."""
    monkeypatch.setattr(config, "preflight", REAL_PREFLIGHT)
    monkeypatch.setenv("JEV_BACKEND", "classifier")
    monkeypatch.setenv("CLASSIFIER_USE_ENV_PROXY", "1")
    monkeypatch.setattr("jev_ultrafast.chrome.probe", lambda *a, **k: (True, "stub"))
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "ollama")
    checks = {check["check"]: check for check in config.preflight()}
    assert checks["jev endpoint"]["ok"] is False
    assert "proxy" in checks["jev endpoint"]["detail"]

    monkeypatch.setenv("CLASSIFIER_API_KEY", "funded")
    checks = {check["check"]: check for check in config.preflight()}
    assert checks["jev endpoint"]["ok"] is True
