"""Behavior tests for the Rivet CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import rivet  # noqa: E402
import manifest  # noqa: E402
import output  # noqa: E402
import plan  # noqa: E402
import project  # noqa: E402
import status  # noqa: E402

MANIFEST = REPO / "manifest.toml"


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    calls = []
    monkeypatch.setenv("OC_CONFIG_DIR", str(cfg))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rivet, "_bootstrap_shell_command", lambda: None)
    monkeypatch.setattr(rivet, "_unbootstrap_shell_command", lambda: None)
    monkeypatch.setattr(
        rivet.project, "init_project", lambda *a, **k: calls.append((a, k))
    )
    monkeypatch.setattr(status, "_environment_checks", lambda *a, **k: [])
    output.set_verbose(False)
    return SimpleNamespace(tmp=tmp_path, cfg=cfg, project_calls=calls)


def _init(*args: str) -> int:
    return rivet.main(["init", *args])


def test_init_installs_core_and_project(cli, monkeypatch, capsys):
    git("init", cwd=cli.tmp)
    monkeypatch.setattr(rivet.plan, "project_changes", lambda *a, **k: [])

    assert _init() == 0

    assert (cli.cfg / "commands" / "commit-message.md").exists()
    assert (cli.cfg / "AGENTS.md").exists()
    assert cli.project_calls
    assert cli.project_calls[0][0][0] == cli.tmp
    assert "Ready." in capsys.readouterr().out


def test_init_is_idempotent(cli, capsys):
    assert _init() == 0
    capsys.readouterr()

    assert _init() == 0

    out = capsys.readouterr().out
    assert "ready" in out
    assert (cli.cfg / "AGENTS.md").read_text().count("caveman-begin") == 1


def test_init_links_and_uninstall_removes_tab_explorer_plugin(cli, capsys):
    assert _init("--no-project") == 0

    target = cli.cfg / "plugins" / "tab-explorer"
    assert target.is_symlink()
    assert target.resolve() == (REPO / "content" / "plugins" / "tab-explorer").resolve()
    assert "Plugins" in capsys.readouterr().out

    assert rivet.main(["uninstall"]) == 0

    assert not target.is_symlink()


def test_init_repairs_a_partial_install(cli):
    assert _init("--no-project") == 0
    target = cli.cfg / "commands" / "fix.md"
    target.unlink()

    assert _init("--no-project") == 0

    assert target.exists()


def test_init_refreshes_outdated_instruction_block(cli):
    assert _init("--no-project") == 0
    agents = cli.cfg / "AGENTS.md"
    agents.write_text(
        agents.read_text().replace(
            "Respond terse like smart caveman.", "OLD CAVEMAN TEXT"
        )
    )

    assert _init("--no-project") == 0

    text = agents.read_text()
    assert "OLD CAVEMAN TEXT" not in text
    assert "Respond terse like smart caveman." in text


def test_init_warns_when_project_tools_are_missing(cli, capsys):
    git("init", cwd=cli.tmp)

    assert _init() == 0

    out = capsys.readouterr().out
    assert "Project" in out
    assert "need attention" in out
    assert "Ready." not in out


def test_init_outside_git_installs_core_only(cli, capsys):
    assert _init() == 0

    assert (cli.cfg / "commands" / "fix.md").exists()
    assert not cli.project_calls
    assert "not a Git repository" in capsys.readouterr().out


def test_init_dry_run_makes_no_changes(cli, capsys):
    assert _init("--dry-run") == 0

    assert not cli.cfg.exists()
    out = capsys.readouterr().out
    assert "ADD" in out
    assert "Dry run: no files were changed." in out


def test_init_reports_conflict_without_force(cli, capsys):
    cli.cfg.mkdir(parents=True)
    target = cli.cfg / "commands" / "fix.md"
    target.parent.mkdir(parents=True)
    target.write_text("user-owned\n")

    assert _init() == 1

    assert target.read_text() == "user-owned\n"
    out = capsys.readouterr().out
    assert "1 item needs attention" in out
    assert "Re-run with --force" in out


def test_init_force_replaces_conflict(cli):
    cli.cfg.mkdir(parents=True)
    target = cli.cfg / "commands" / "fix.md"
    target.parent.mkdir(parents=True)
    target.write_text("user-owned\n")

    assert _init("--force") == 0

    assert target.read_text() == (REPO / "content" / "commands" / "fix.md").read_text()


def test_init_force_prunes_a_stale_managed_link(cli):
    assert _init("--no-project") == 0
    stale = cli.cfg / "commands" / "old.md"
    stale.symlink_to(REPO / "content" / "commands" / "fix.md")

    assert _init("--force", "--no-project") == 0

    assert not stale.exists()


def test_init_preserves_existing_agents_md(cli):
    cli.cfg.mkdir(parents=True)
    agents = cli.cfg / "AGENTS.md"
    agents.write_text("my project notes\n")

    assert _init() == 0

    text = agents.read_text()
    assert "my project notes" in text
    assert "caveman-begin" in text


def test_init_failure_is_reported(cli, monkeypatch, capsys):
    git("init", cwd=cli.tmp)
    monkeypatch.setattr(
        rivet.project,
        "init_project",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert _init() == 1

    assert "boom" in capsys.readouterr().err


def test_status_reports_project_core_and_environment(cli, capsys):
    assert _init() == 0
    capsys.readouterr()

    assert rivet.main(["status"]) == 0

    out = capsys.readouterr().out
    assert "Project" in out
    assert "Environment" in out
    assert "Commands" in out
    assert "Integrations" in out
    assert "Rivet 0.1.0" in out


def test_status_before_init_is_informational(cli, capsys):
    assert rivet.main(["status"]) == 0

    out = capsys.readouterr().out
    assert "not installed" in out
    assert "Changes" in out


def test_status_reports_outdated_instruction_block(cli, capsys):
    assert _init("--no-project") == 0
    agents = cli.cfg / "AGENTS.md"
    agents.write_text(
        agents.read_text().replace(
            "Respond terse like smart caveman.", "OLD CAVEMAN TEXT"
        )
    )
    capsys.readouterr()

    assert rivet.main(["status"]) == 0

    out = capsys.readouterr().out
    assert "Instructions" in out
    assert "needs attention" in out


def test_status_has_no_changes_section_when_clean(cli, capsys):
    assert _init("--no-project") == 0
    capsys.readouterr()

    assert rivet.main(["status"]) == 0

    assert "Changes" not in capsys.readouterr().out


def test_status_reports_pending_changes(cli, capsys):
    assert rivet.main(["status"]) == 0

    out = capsys.readouterr().out
    assert "Changes" in out
    assert "ADD" in out


def test_status_reports_drift(cli, capsys):
    assert _init("--no-project") == 0
    capsys.readouterr()

    target = cli.cfg / "commands" / "fix.md"
    target.unlink()
    target.write_text("user-owned\n")
    stale = cli.cfg / "commands" / "old.md"
    stale.symlink_to(REPO / "content" / "commands" / "fix.md")

    assert rivet.main(["status"]) == 0

    out = capsys.readouterr().out
    assert "Changes" in out
    assert "UPDATE" in out
    assert "REMOVE" in out


def test_status_magic_context_is_optional(cli, capsys):
    assert rivet.main(["status"]) == 0

    out = capsys.readouterr().out
    assert "Magic Context" in out
    assert "not installed (optional)" in out


def test_status_reads_tui_plugins_from_cli_json(cli, capsys):
    cli.cfg.mkdir(parents=True, exist_ok=True)
    (cli.cfg / "cli.json").write_text(
        '{\n  "plugins": ["@banburist/opencode-headsup"]\n}\n'
    )

    assert rivet.main(["status"]) == 0

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "HeadsUp" in line)
    assert "installed" in line
    assert "not installed" not in line


def test_status_warnings_do_not_fail(cli, monkeypatch, capsys):
    warning = status.Check("Shell", status.WARN, "unsupported", "register it manually")
    monkeypatch.setattr(status, "_environment_checks", lambda *a, **k: [warning])
    monkeypatch.setattr(status, "_project_checks", lambda cwd: ([], None))
    monkeypatch.setattr(status, "_integration_checks", lambda config_dir: [])

    assert rivet.main(["status"]) == 0

    out = capsys.readouterr().out
    assert "1 issue found" in out
    assert "failure" not in out


def test_status_reports_failure(cli, monkeypatch, capsys):
    failure = status.Check("OpenCode", status.FAIL, "not found", "install it")
    monkeypatch.setattr(status, "_environment_checks", lambda *a, **k: [failure])

    assert rivet.main(["status"]) == 1

    out = capsys.readouterr().out
    assert "1 failure" in out
    assert "fix: install it" in out


@pytest.mark.parametrize("command", ["doctor", "diff"])
def test_removed_commands_are_rejected(cli, command):
    with pytest.raises(SystemExit) as exc:
        rivet.main([command])

    assert exc.value.code == 2


def test_init_yes_is_rejected(cli):
    with pytest.raises(SystemExit) as exc:
        rivet.main(["init", "--yes"])

    assert exc.value.code == 2


def test_init_dry_run_collapses_large_component_groups(cli, capsys):
    assert rivet.main(["init", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "commands/commit-message.md" in out
    assert "scripts/verify-commit" in out
    assert "skills/" in out
    assert "11 items" in out
    assert "themes/" in out
    assert "63 items" in out


def test_init_dry_run_reports_add_update_remove(cli, capsys):
    assert rivet.main(["init", "--dry-run"]) == 0
    assert "ADD" in capsys.readouterr().out

    assert _init() == 0
    capsys.readouterr()

    target = cli.cfg / "commands" / "fix.md"
    target.unlink()
    target.write_text("user-owned\n")
    stale = cli.cfg / "commands" / "old.md"
    stale.symlink_to(REPO / "content" / "commands" / "fix.md")

    assert rivet.main(["init", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "UPDATE" in out
    assert "REMOVE" in out


def test_uninstall_preserves_user_file(cli, capsys):
    cli.cfg.mkdir(parents=True)
    target = cli.cfg / "commands" / "fix.md"
    target.parent.mkdir(parents=True)
    target.write_text("user-owned\n")

    assert rivet.main(["uninstall"]) == 0

    assert target.read_text() == "user-owned\n"
    assert "left in place" in capsys.readouterr().out


def test_uninstall_removes_managed_and_project_files(cli, capsys):
    git("init", cwd=cli.tmp)
    assert _init("--no-project") == 0
    agents = cli.cfg / "AGENTS.md"
    agents.write_text("user notes\n\n" + agents.read_text())

    project_agents = cli.tmp / "AGENTS.md"
    project_agents.write_text(
        (REPO / "content" / "instructions" / "codebase-memory-mcp-agents.md").read_text()
        + "\n\nuser project notes\n"
    )
    plugin = cli.tmp / ".opencode" / "plugins" / "CodebaseMemoryReminder.ts"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(
        (REPO / "content" / "plugins" / "CodebaseMemoryReminder.ts").read_text()
    )
    config = cli.tmp / ".opencode" / "opencode.json"
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "servers": {
                        "codebase-memory-mcp": {
                            "type": "local",
                            "command": ["/usr/bin/codebase-memory-mcp"],
                        }
                    }
                }
            }
        )
    )

    assert rivet.main(["uninstall"]) == 0

    assert "user notes" in agents.read_text()
    assert "user project notes" in project_agents.read_text()
    assert "codebase-memory-mcp:start" not in project_agents.read_text()
    assert not plugin.exists()
    data = json.loads(config.read_text())
    assert "codebase-memory-mcp" not in data["mcp"]["servers"]


def test_uninstall_dry_run_makes_no_changes(cli, capsys):
    assert _init() == 0
    capsys.readouterr()

    assert rivet.main(["uninstall", "--dry-run"]) == 0

    assert (cli.cfg / "commands" / "fix.md").exists()
    assert "REMOVE" in capsys.readouterr().out


def test_uninstall_dry_run_omits_incomplete_text_block(cli, monkeypatch, capsys):
    monkeypatch.setattr(rivet.shell_rc, "rc_path", lambda shell: None)
    assert _init() == 0
    agents = cli.cfg / "AGENTS.md"
    damaged = agents.read_text()
    for marker in ("<!-- caveman-end -->", "<!-- file-edit-size-limits:stop -->"):
        damaged = damaged.replace(marker, "")
    agents.write_text(damaged)
    capsys.readouterr()

    assert rivet.main(["uninstall", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "remove Rivet instructions" not in out
    assert "AGENTS.md" not in out


def test_update_dry_run_reports_state(cli, monkeypatch, capsys):
    monkeypatch.setattr(rivet, "_checkout_state", lambda: "current")

    assert rivet.main(["update", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "up to date" in out
    assert not cli.cfg.exists()


def test_update_checkout_refuses_dirty_checkout(monkeypatch, capsys):
    monkeypatch.setattr(rivet, "_checkout_state", lambda: "behind")
    monkeypatch.setattr(
        rivet,
        "_git",
        lambda *args, **kw: SimpleNamespace(returncode=0, stdout=" M file\n", stderr=""),
    )

    assert rivet._update_checkout() is False
    assert "uncommitted" in capsys.readouterr().out


def test_update_checkout_pulls_when_clean(monkeypatch, capsys):
    monkeypatch.setattr(rivet, "_checkout_state", lambda: "behind")

    def fake_git(*args, **kw):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rivet, "_git", fake_git)

    assert rivet._update_checkout() is True
    assert "updated" in capsys.readouterr().out


def test_update_runs_init_in_fresh_process(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(rivet, "_update_checkout", lambda: True)
    monkeypatch.setattr(
        rivet.subprocess,
        "run",
        lambda args, **kw: calls.append((args, kw)) or SimpleNamespace(returncode=0),
    )

    assert rivet.main(["update", "--force"]) == 0

    assert calls
    assert "init" in calls[0][0]
    assert "--force" in calls[0][0]
    assert calls[0][1]["env"]["SKIP_RIVET_BANNER"] == "1"


def test_agent_flag_is_removed():
    for argv in (
        ["init", "--agent", "opencode"],
        ["init", "--agent", "omp"],
        ["status", "--agent", "opencode"],
        ["uninstall", "--agent", "omp"],
    ):
        with pytest.raises(SystemExit):
            rivet.build_parser().parse_args(argv)


def test_manifest_targets_only_opencode():
    data = manifest.load(MANIFEST)

    assert {agent for artifact in data["artifacts"] for agent in artifact["agents"]} == {
        "opencode"
    }


def test_install_is_not_a_canonical_command():
    with pytest.raises(SystemExit):
        rivet.build_parser().parse_args(["install"])


def test_version_is_reported():
    result = subprocess.run(
        [sys.executable, str(REPO / "src" / "rivet.py"), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Rivet 0.1.0"


def test_project_changes_reports_partial_install(cli):
    git("init", cwd=cli.tmp)
    (cli.tmp / "AGENTS.md").write_text(
        (REPO / "content" / "instructions" / "codebase-memory-mcp-agents.md").read_text()
    )

    changes = plan.project_changes(REPO, cli.tmp)

    paths = {change.path for change in changes}
    assert "openspec/" in paths
    assert ".opencode/plugins/CodebaseMemoryReminder.ts" in paths
    assert ".opencode/opencode.json" in paths


def test_project_changes_reports_jsonc_config(cli):
    git("init", cwd=cli.tmp)
    directory = cli.tmp / ".opencode"
    directory.mkdir()
    (directory / "opencode.jsonc").write_text(
        '{\n  // project config\n  "theme": "x"\n}\n'
    )

    changes = plan.project_changes(REPO, cli.tmp)

    paths = {change.path for change in changes}
    assert ".opencode/opencode.jsonc" in paths
    assert ".opencode/opencode.json" not in paths


def test_uninstall_changes_omits_incomplete_project_block(cli, monkeypatch):
    git("init", cwd=cli.tmp)
    (cli.tmp / "AGENTS.md").write_text(
        "<!-- codebase-memory-mcp:start -->\nbody\n"
    )
    monkeypatch.setattr(rivet.shell_rc, "rc_path", lambda shell: None)

    changes = plan.uninstall_changes(
        manifest.load(MANIFEST), REPO, cli.cfg, cli.tmp
    )

    assert not any(
        change.detail == "remove codebase-memory block" for change in changes
    )


def test_uninstall_changes_omits_start_only_shell_block(cli, monkeypatch):
    rc = cli.tmp / ".zshrc"
    rc.write_text(
        "# >>> rivet begin >>>\n"
        'rivet() { /old/bin/rivet "$@"; }\n'
    )
    monkeypatch.setattr(
        rivet.shell_rc, "rc_path", lambda shell: rc if shell == "zsh" else None
    )

    changes = plan.uninstall_changes(
        manifest.load(MANIFEST), REPO, cli.cfg, cli.tmp
    )

    assert not any(change.detail == "remove shell command" for change in changes)


def test_uninstall_changes_reports_complete_shell_block(cli, monkeypatch):
    rc = cli.tmp / ".zshrc"
    rc.write_text(
        rivet.shell_rc.bootstrap_block(REPO / "bin" / "rivet", "zsh")
    )
    monkeypatch.setattr(
        rivet.shell_rc, "rc_path", lambda shell: rc if shell == "zsh" else None
    )

    changes = plan.uninstall_changes(
        manifest.load(MANIFEST), REPO, cli.cfg, cli.tmp
    )

    assert any(change.detail == "remove shell command" for change in changes)


def test_uninstall_changes_marks_modified_project_files_as_keep(cli, monkeypatch):
    git("init", cwd=cli.tmp)
    plugin = cli.tmp / ".opencode" / "plugins" / "CodebaseMemoryReminder.ts"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("user modified\n")

    monkeypatch.setattr(rivet.shell_rc, "rc_path", lambda shell: None)
    changes = plan.uninstall_changes(
        manifest.load(MANIFEST), REPO, cli.cfg, cli.tmp
    )

    assert any(change.kind == "keep" for change in changes)
