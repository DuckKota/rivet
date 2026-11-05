"""Direct tests for the installer's Python config editors."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON_DIR = REPO / "installer" / "python"
JSONC = REPO / "src" / "jsonc.py"


def _load_jsonc():
    spec = importlib.util.spec_from_file_location("installer_jsonc", JSONC)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PYTHON_DIR / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def _load_config(path: Path):
    jsonc = _load_jsonc()
    return json.loads(jsonc.strip_jsonc(path.read_text()))


def test_strip_jsonc_keeps_string_markers_and_removes_comments():
    jsonc = _load_jsonc()
    source = (
        '{\n'
        '  // comment\n'
        '  "url": "https://example.com/a//b",\n'
        '  "pattern": "a,b}c", /* block */\n'
        '}\n'
    )
    data = json.loads(jsonc.strip_jsonc(source))
    assert data == {
        "url": "https://example.com/a//b",
        "pattern": "a,b}c",
    }


def test_write_atomic_preserves_symlink_and_mode(tmp_path):
    jsonc = _load_jsonc()
    target = tmp_path / "dotfiles" / "opencode.jsonc"
    target.parent.mkdir()
    target.write_text("old\n")
    target.chmod(0o640)
    link = tmp_path / "opencode.jsonc"
    link.symlink_to(target)

    jsonc.write_atomic(str(link), "new\n")

    assert link.is_symlink()
    assert target.read_text() == "new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_write_atomic_creates_new_file_with_default_mode(tmp_path):
    jsonc = _load_jsonc()
    target = tmp_path / "new.md"
    previous = os.umask(0o022)
    try:
        jsonc.write_atomic(str(target), "new\n")
    finally:
        os.umask(previous)

    assert target.read_text() == "new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_plannotator_converts_string_entry(tmp_path):
    config = _write(
        tmp_path / "opencode.jsonc",
        '{\n  "plugins": [\n    "@dietrichgebert/ponytail",\n'
        '    "@plannotator/opencode@latest"\n  ]\n}\n',
    )

    result = _run(
        "plannotator.py",
        str(config),
    )

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["plugins"][0] == "@dietrichgebert/ponytail"
    assert data["plugins"][1] == {
        "package": "@plannotator/opencode@latest",
        "options": {"workflow": "manual"},
    }


def test_plannotator_matches_pinned_version_string(tmp_path):
    config = _write(
        tmp_path / "opencode.jsonc",
        '{\n  "plugins": ["@plannotator/opencode@0.28.38"]\n}\n',
    )

    result = _run("plannotator.py", str(config))

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["plugins"] == [
        {
            "package": "@plannotator/opencode@0.28.38",
            "options": {"workflow": "manual"},
        }
    ]


def test_plannotator_matches_pinned_version_entry(tmp_path):
    config = _write(
        tmp_path / "opencode.jsonc",
        '{\n  "plugins": [\n    {\n'
        '      "package": "@plannotator/opencode@0.28.38",\n'
        '      "options": { "runtime": "cli" }\n'
        '    }\n  ]\n}\n',
    )

    result = _run("plannotator.py", str(config))

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["plugins"] == [
        {
            "package": "@plannotator/opencode@0.28.38",
            "options": {"runtime": "cli", "workflow": "manual"},
        }
    ]


def test_plannotator_ignores_similar_package(tmp_path):
    config = _write(
        tmp_path / "opencode.jsonc",
        '{\n  "plugins": ["@plannotator/opencode-extra"]\n}\n',
    )

    result = _run("plannotator.py", str(config))

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["plugins"][0] == "@plannotator/opencode-extra"
    assert data["plugins"][1] == {
        "package": "@plannotator/opencode@latest",
        "options": {"workflow": "manual"},
    }


def test_plannotator_preserves_other_options(tmp_path):
    config = _write(
        tmp_path / "opencode.jsonc",
        '{\n  "plugins": [\n    {\n'
        '      "package": "@plannotator/opencode@latest",\n'
        '      "options": { "workflow": "plan-agent", "runtime": "cli" }\n'
        '    }\n  ]\n}\n',
    )

    result = _run(
        "plannotator.py",
        str(config),
    )

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["plugins"][0]["options"] == {
        "workflow": "manual",
        "runtime": "cli",
    }


def test_plannotator_is_idempotent(tmp_path):
    config = _write(
        tmp_path / "opencode.jsonc",
        '{\n  "plugins": [\n    {\n'
        '      "package": "@plannotator/opencode@latest",\n'
        '      "options": { "workflow": "manual" }\n'
        '    }\n  ]\n}\n',
    )

    result = _run(
        "plannotator.py",
        str(config),
    )

    assert result.returncode == 2, result.stderr


def test_plannotator_adds_missing_entry(tmp_path):
    config = _write(
        tmp_path / "opencode.jsonc",
        '{\n  "plugins": ["@dietrichgebert/ponytail"]\n}\n',
    )

    result = _run(
        "plannotator.py",
        str(config),
    )

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["plugins"][0] == "@dietrichgebert/ponytail"
    assert data["plugins"][1] == {
        "package": "@plannotator/opencode@latest",
        "options": {"workflow": "manual"},
    }


def test_plannotator_drops_comments_and_trailing_commas(tmp_path):
    config = _write(
        tmp_path / "opencode.jsonc",
        '{\n  // keep\n  "plugins": [\n'
        '    "@plannotator/opencode@latest",\n  ]\n}\n',
    )

    result = _run(
        "plannotator.py",
        str(config),
    )

    assert result.returncode == 0, result.stderr
    updated = config.read_text()
    assert "// keep" not in updated
    data = _load_config(config)
    assert data["plugins"][0]["options"]["workflow"] == "manual"


def test_plannotator_adds_plugins_array_when_missing(tmp_path):
    config = _write(tmp_path / "opencode.jsonc", '{\n  "theme": "x"\n}\n')

    result = _run(
        "plannotator.py",
        str(config),
    )

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["theme"] == "x"
    assert data["plugins"][0]["options"]["workflow"] == "manual"


def test_plannotator_fills_empty_plugins_array(tmp_path):
    config = _write(tmp_path / "opencode.jsonc", '{\n  "plugins": []\n}\n')

    result = _run(
        "plannotator.py",
        str(config),
    )

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["plugins"][0]["options"]["workflow"] == "manual"


def test_plannotator_rejects_empty_object(tmp_path):
    original = "{}\n"
    config = _write(tmp_path / "opencode.jsonc", original)

    result = _run("plannotator.py", str(config))

    assert result.returncode == 1
    assert "is empty" in result.stderr
    assert config.read_text() == original


def test_disabled_plugins_adds_entries_and_preserves_others(tmp_path):
    config = _write(
        tmp_path / "cli.json",
        '{\n  "plugins": ["@banburist/opencode-headsup"]\n}\n',
    )

    result = _run("disabled_plugins.py", str(config))

    assert result.returncode == 0, result.stderr
    assert _load_config(config)["plugins"] == [
        "@banburist/opencode-headsup",
        "-opencode.sidebar.context",
        "-opencode.sidebar.footer",
    ]


def test_disabled_plugins_is_idempotent(tmp_path):
    config = _write(
        tmp_path / "cli.json",
        '{\n  "plugins": [\n'
        '    "-opencode.sidebar.context",\n'
        '    "-opencode.sidebar.footer"\n'
        "  ]\n}\n",
    )

    result = _run("disabled_plugins.py", str(config))

    assert result.returncode == 2, result.stderr


def test_disabled_plugins_creates_missing_file(tmp_path):
    config = tmp_path / "cli.json"

    result = _run("disabled_plugins.py", str(config))

    assert result.returncode == 0, result.stderr
    data = _load_config(config)
    assert data["$schema"] == "https://opencode.ai/v2/cli.json"
    assert data["plugins"] == [
        "-opencode.sidebar.context",
        "-opencode.sidebar.footer",
    ]


def test_disabled_plugins_rejects_empty_file(tmp_path):
    config = _write(tmp_path / "cli.json", "")

    result = _run("disabled_plugins.py", str(config))

    assert result.returncode == 1
    assert "is empty" in result.stderr
    assert config.read_text() == ""


def test_plannotator_reads_package_from_environment(tmp_path):
    config = _write(tmp_path / "opencode.jsonc", '{\n  "plugins": []\n}\n')
    package = "@plannotator/opencode@9.9.9"

    result = subprocess.run(
        [sys.executable, str(PYTHON_DIR / "plannotator.py"), str(config)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PLANNOTATOR_PACKAGE": package},
    )

    assert result.returncode == 0, result.stderr
    assert _load_config(config)["plugins"][0]["package"] == package



