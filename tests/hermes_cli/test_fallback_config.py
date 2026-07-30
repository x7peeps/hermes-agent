"""Tests for hermes_cli/fallback_config.py — fallback entry API-key resolution."""

from unittest.mock import patch

from hermes_cli.fallback_config import resolve_entry_api_key


class TestResolveEntryApiKey:
    def test_inline_api_key_wins(self, monkeypatch):
        monkeypatch.setenv("FB_KEY", "env-key")
        entry = {"provider": "custom", "api_key": "inline-key", "key_env": "FB_KEY"}
        assert resolve_entry_api_key(entry) == "inline-key"

    def test_key_env_resolves_from_environment(self, monkeypatch):
        monkeypatch.setenv("FB_KEY", "env-key")
        assert resolve_entry_api_key({"key_env": "FB_KEY"}) == "env-key"

    def test_api_key_env_alias(self, monkeypatch):
        monkeypatch.setenv("FB_ALIAS_KEY", "alias-key")
        assert resolve_entry_api_key({"api_key_env": "FB_ALIAS_KEY"}) == "alias-key"

    def test_unset_env_var_returns_none(self, monkeypatch):
        monkeypatch.delenv("FB_MISSING", raising=False)
        # None (not "") lets resolve_runtime_provider fall through to the
        # provider's standard credential resolution.
        assert resolve_entry_api_key({"key_env": "FB_MISSING"}) is None

    def test_empty_env_var_returns_none(self, monkeypatch):
        monkeypatch.setenv("FB_EMPTY", "   ")
        assert resolve_entry_api_key({"key_env": "FB_EMPTY"}) is None

    def test_no_key_fields_returns_none(self):
        assert resolve_entry_api_key({"provider": "openrouter", "model": "glm"}) is None

    def test_non_dict_returns_none(self):
        assert resolve_entry_api_key(None) is None
        assert resolve_entry_api_key("nope") is None  # type: ignore[arg-type]

    def test_whitespace_inline_key_falls_through_to_env(self, monkeypatch):
        monkeypatch.setenv("FB_KEY", "env-key")
        entry = {"api_key": "   ", "key_env": "FB_KEY"}
        assert resolve_entry_api_key(entry) == "env-key"

    # ── regression tests: secret_scope-aware resolution (PR #74722) ────────

    def test_scoped_get_secret_called_with_correct_env_name(self):
        """Verify _get_secret is called with the correct key_env name.

        Regression test for PR #74722: resolve_entry_api_key must delegate
        to the secret_scope-aware get_secret (not raw os.getenv), so that
        per-profile scoped secrets are respected in the multiplexing gateway.
        """
        with patch("hermes_cli.fallback_config._get_secret") as mock_get:
            mock_get.return_value = "scope-key"
            assert resolve_entry_api_key({"key_env": "MY_SCOPE_KEY"}) == "scope-key"
            mock_get.assert_called_once_with("MY_SCOPE_KEY")

    def test_scoped_get_secret_with_api_key_env_alias(self):
        """Same regression check for the api_key_env alias field."""
        with patch("hermes_cli.fallback_config._get_secret") as mock_get:
            mock_get.return_value = "alias-scope-key"
            assert resolve_entry_api_key({"api_key_env": "MY_ALIAS_KEY"}) == "alias-scope-key"
            mock_get.assert_called_once_with("MY_ALIAS_KEY")

    def test_scoped_path_returns_none_when_get_secret_returns_none(self):
        """When _get_secret returns None, resolve_entry_api_key returns None
        (letting resolve_runtime_provider fall through to standard resolution)."""
        with patch("hermes_cli.fallback_config._get_secret", return_value=None):
            assert resolve_entry_api_key({"key_env": "MISSING_KEY"}) is None
