"""Tests for systemd cgroup isolation helpers in process_registry."""
import importlib
import os
import subprocess
import sys
from unittest import mock

import pytest

# Ensure tools/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools import process_registry as pr_mod


class TestRunningUnderSystemd:
    """Tests for _running_under_systemd()."""

    def test_false_on_windows(self, monkeypatch):
        monkeypatch.setattr(pr_mod, "_IS_WINDOWS", True)
        monkeypatch.setattr(pr_mod, "_IS_LINUX", False)
        assert pr_mod._running_under_systemd() is False

    def test_false_on_macos(self, monkeypatch):
        monkeypatch.setattr(pr_mod, "_IS_WINDOWS", False)
        monkeypatch.setattr(pr_mod, "_IS_LINUX", False)
        assert pr_mod._running_under_systemd() is False

    def test_true_via_invocation_id(self, monkeypatch):
        monkeypatch.setattr(pr_mod, "_IS_WINDOWS", False)
        monkeypatch.setattr(pr_mod, "_IS_LINUX", True)
        monkeypatch.setenv("INVOCATION_ID", "abc123")
        # Ensure cgroup path doesn't interfere
        monkeypatch.setattr(pr_mod, "Path", mock.MagicMock(side_effect=OSError))
        assert pr_mod._running_under_systemd() is True

    def test_true_via_cgroup_service(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pr_mod, "_IS_WINDOWS", False)
        monkeypatch.setattr(pr_mod, "_IS_LINUX", True)
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        # Create a fake /proc/self/cgroup
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("0::/user.slice/user-1000.slice/user@1000.service/app.slice/hermes-gateway.service\n")
        mock_path = mock.MagicMock()
        mock_path.read_text.return_value = cgroup_file.read_text()
        monkeypatch.setattr(pr_mod, "Path", mock.MagicMock(return_value=mock_path))
        assert pr_mod._running_under_systemd() is True

    def test_false_when_not_service(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pr_mod, "_IS_WINDOWS", False)
        monkeypatch.setattr(pr_mod, "_IS_LINUX", True)
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("0::/user.slice/user-1000.slice\n")
        mock_path = mock.MagicMock()
        mock_path.read_text.return_value = cgroup_file.read_text()
        monkeypatch.setattr(pr_mod, "Path", mock.MagicMock(return_value=mock_path))
        assert pr_mod._running_under_systemd() is False


class TestSystemdScopeFlags:
    """Tests for _systemd_scope_flags()."""

    def test_defaults_to_user_on_error(self, monkeypatch):
        monkeypatch.setattr(pr_mod, "_IS_WINDOWS", False)
        monkeypatch.setattr(pr_mod, "_IS_LINUX", True)
        monkeypatch.setattr(pr_mod, "Path", mock.MagicMock(side_effect=OSError))
        assert pr_mod._systemd_scope_flags() == ["--user"]

    def test_returns_user_when_systemctl_matches(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pr_mod, "_IS_WINDOWS", False)
        monkeypatch.setattr(pr_mod, "_IS_LINUX", True)
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("0::/user.slice/.../my-gateway.service\n")
        mock_path = mock.MagicMock()
        mock_path.read_text.return_value = cgroup_file.read_text()
        monkeypatch.setattr(pr_mod, "Path", mock.MagicMock(return_value=mock_path))

        # Mock shutil.which to return a fake systemctl
        def fake_which(name):
            return "/usr/bin/systemctl" if name == "systemctl" else None
        monkeypatch.setattr("shutil.which", fake_which)

        # Mock subprocess.run to return a valid PID
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "12345\n"
        monkeypatch.setattr("subprocess.run", mock.MagicMock(return_value=mock_result))

        assert pr_mod._systemd_scope_flags() == ["--user"]


class TestSpawnSystemdScope:
    """Tests for _spawn_systemd_scope()."""

    def test_returns_none_when_systemd_run_missing(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        result = pr_mod._spawn_systemd_scope(
            command="echo hello",
            env=os.environ.copy(),
            cwd="/tmp",
            scope_flags=["--user"],
        )
        assert result is None

    def test_returns_popen_when_systemd_run_available(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/systemd-run")

        # Mock Popen to avoid actually spawning
        mock_popen = mock.MagicMock()
        monkeypatch.setattr("subprocess.Popen", mock_popen)

        result = pr_mod._spawn_systemd_scope(
            command="echo hello",
            env=os.environ.copy(),
            cwd="/tmp",
            scope_flags=["--user"],
        )

        assert result is mock_popen.return_value
        # Verify the call used systemd-run with correct args
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "/usr/bin/systemd-run"
        assert "--user" in cmd
        assert "--scope" in cmd
        assert "--collect" in cmd
        assert "bash" in cmd
        assert "-lic" in cmd
