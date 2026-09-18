"""
Smoke tests for the parakeet-stt-mlx-vlm optional skill.

This skill is a thin setup-and-config wrapper around ``mlx-vlm``'s
OpenAI-compatible transcription endpoint. It does not call any model itself
(network + 700 MB download is too heavy for CI), so these tests verify:
  - SKILL.md frontmatter conforms to the hardline format
  - shipped shell scripts parse as valid bash (no syntax errors)
  - the scripts reference the right CLI / port conventions
  - the description stays under the 60-char hardline
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parents[2] / "optional-skills" / "mlops" / "parakeet-stt-mlx-vlm"


@pytest.fixture(scope="module")
def frontmatter() -> dict:
    src = (SKILL_DIR / "SKILL.md").read_text()
    m = re.search(r"^---\n(.*?)\n---", src, re.DOTALL)
    assert m, "SKILL.md missing YAML frontmatter"
    return yaml.safe_load(m.group(1))


def test_skill_dir_exists() -> None:
    assert SKILL_DIR.is_dir(), f"missing skill dir: {SKILL_DIR}"


def test_skill_md_present() -> None:
    assert (SKILL_DIR / "SKILL.md").is_file()


def test_description_under_60_chars(frontmatter) -> None:
    desc = frontmatter["description"]
    assert len(desc) <= 60, f"description is {len(desc)} chars (hardline ≤60): {desc!r}"


def test_name_matches_dir(frontmatter) -> None:
    assert frontmatter["name"] == "parakeet-stt-mlx-vlm"


def test_platforms_excludes_windows(frontmatter) -> None:
    # mlx-vlm is MLX-bound; macOS + Linux only.
    assert "windows" not in frontmatter["platforms"]
    assert set(frontmatter["platforms"]) >= {"macos", "linux"}


def test_license_mit(frontmatter) -> None:
    assert frontmatter["license"] == "MIT"


def test_mlx_vlm_pin_in_dependencies(frontmatter) -> None:
    # 0.7.1 added the OpenAI-conformant segments PR (Blaizzy/mlx-vlm#2189);
    # anything older breaks the timestamps / SRT export promise.
    deps = frontmatter.get("dependencies", [])
    pin = next((d for d in deps if d.startswith("mlx-vlm")), None)
    assert pin is not None, "dependencies must pin mlx-vlm"
    assert ">=0.7.1" in pin, f"mlx-vlm must be pinned >=0.7.1; got {pin!r}"


@pytest.mark.parametrize(
    "path",
    [
        "scripts/install_deps.sh",
        "scripts/start_parakeet_server.sh",
        "scripts/transcribe_cli.sh",
    ],
)
def test_shipped_scripts_parse(path: str) -> None:
    """`bash -n` exits 0 if the script is syntactically valid.

    We use ``bash`` rather than ``sh`` so the `[[ ... ]]` tests / `set -euo
    pipefail` lines parse cleanly on macOS (the default ``sh`` is bash 3.2 and
    accepts them, but using bash explicitly matches the shebang).
    """
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not on PATH")
    script = SKILL_DIR / path
    assert script.is_file(), f"missing script: {path}"
    result = subprocess.run(
        [bash, "-n", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"bash syntax error in {path}: {result.stderr}"
    )


def test_start_script_targets_mlx_vlm_serve() -> None:
    src = (SKILL_DIR / "scripts" / "start_parakeet_server.sh").read_text()
    assert "mlx_vlm serve" in src, "start script must run `mlx_vlm serve`"
    # Default port must match what the SKILL.md quick-start advertises.
    assert "8080" in src, "start script must default to port 8080"


def test_start_script_default_model_is_parakeet_tdt() -> None:
    src = (SKILL_DIR / "scripts" / "start_parakeet_server.sh").read_text()
    assert "parakeet-tdt-0.6b-v3" in src, (
        "default model must be parakeet-tdt-0.6b-v3 (best accuracy/speed)"
    )


def test_transcribe_cli_targets_openai_endpoint() -> None:
    src = (SKILL_DIR / "scripts" / "transcribe_cli.sh").read_text()
    assert "/v1/audio/transcriptions" in src, (
        "transcribe_cli must POST to /v1/audio/transcriptions"
    )
    assert "response_format=json" in src, (
        "transcribe_cli must request response_format=json for parseable output"
    )


def test_install_script_refuses_outside_venv() -> None:
    """install_deps.sh must abort when no virtualenv is active.

    Defends against the very common "ran in system Python, broke brew-managed
    python on macOS" footgun.
    """
    src = (SKILL_DIR / "scripts" / "install_deps.sh").read_text()
    assert "VIRTUAL_ENV" in src, (
        "install_deps.sh must check VIRTUAL_ENV before running pip"
    )


def test_skill_documents_hermes_config_block() -> None:
    """The whole point of this skill is the 4-line config block — verify it's there."""
    body = (SKILL_DIR / "SKILL.md").read_text()
    assert "stt:" in body, "SKILL.md must show the stt: config block"
    assert "base_url: http://localhost:8080/v1" in body, (
        "SKILL.md must show the exact base_url pointing at the local server"
    )
    assert "provider: openai" in body, (
        "SKILL.md must instruct users to switch provider to openai (the existing one)"
    )


def test_troubleshooting_covers_hf_mirror() -> None:
    """Cross-link the HF mirror section to PR #125 so users find both at once."""
    body = (SKILL_DIR / "references" / "troubleshooting.md").read_text()
    assert "HF_ENDPOINT" in body, (
        "troubleshooting must mention HF_ENDPOINT as the HF mirror env var"
    )
