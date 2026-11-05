"""Tests for the Rivet python tooling."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import config  # noqa: E402
import rivet  # noqa: E402
import project  # noqa: E402
import jsonc  # noqa: E402
import manifest  # noqa: E402
import merge  # noqa: E402
import operations  # noqa: E402
import output  # noqa: E402
import shell_rc  # noqa: E402
import state  # noqa: E402

MANIFEST_PATH = REPO / "manifest.toml"


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _ok_run(cmd, **kw):
    # Stand-in for subprocess.run in tests that only assert on the command.
    class R:
        returncode = 0
        stdout = ""
        stderr = ""
    return R()


def git_out(*args, cwd=None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


# ------------------------------------------------------------------ manifest
def test_manifest_loads_and_validates():
    m = manifest.load(MANIFEST_PATH)
    names = manifest.artifact_names(m)
    assert "grill-me" in names
    assert "caveman" in names
    assert "humanize-writing" in names


def test_set_sha_edits_correct_artifact(tmp_path):
    src = tmp_path / "m.toml"
    src.write_text(
        'version = 2\n'
        '[[artifacts]]\nname = "a"\noperation = "symlink"\n'
        'provenance = "original"\nagents = ["opencode"]\nsrc = "a"\ntarget = "a"\nsource_sha = ""\n'
        '[[artifacts]]\nname = "b"\noperation = "symlink"\n'
        'provenance = "original"\nagents = ["opencode"]\nsrc = "b"\ntarget = "b"\nsource_sha = ""\n'
    )
    manifest.set_sha(src, "b", "abc123")
    m = manifest.load(src)
    assert m["artifacts"][0]["source_sha"] == ""
    assert m["artifacts"][1]["source_sha"] == "abc123"


# ------------------------------------------------------------- config dir
def test_config_dir_env_override(monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", "/tmp/fake")
    assert config.opencode_config_dir({}) == Path("/tmp/fake")


def test_config_dir_manifest_default(monkeypatch):
    monkeypatch.delenv("OC_CONFIG_DIR", raising=False)
    m = {"config": {"default_config_dir": "~/x"}}
    assert config.opencode_config_dir(m) == Path.home() / "x"


# ---------------------------------------------------------------- install
def test_install_symlinks_text_and_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    operations.install(manifest.load(MANIFEST_PATH), REPO, cfg)

    cmd = cfg / "commands" / "commit-message.md"
    # commit-message.md carries placeholder substitution, so it is installed
    # as a substituted copy, not a symlink.
    assert not cmd.is_symlink()
    assert "<VALIDATE_COMMIT_SCRIPT>" not in cmd.read_text()
    assert str(cfg / "scripts" / "verify-commit") in cmd.read_text()
    # the validator script entry stays a plain symlink
    assert (cfg / "scripts" / "verify-commit").is_symlink()

    agents = cfg / "AGENTS.md"
    text = agents.read_text()
    assert "caveman-begin" in text
    assert "file-edit-size-limits:start" in text

    cli = json.loads((cfg / "cli.json").read_text())
    assert cli["theme"]["name"] == "github"
    # codebase-memory-mcp is per-project now (see project), not global config.
    assert not (cfg / "opencode.json").exists()
    assert (cfg / state.STATE_FILE).exists()


def test_install_preserves_existing_theme(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    cfg.mkdir(parents=True)
    (cfg / "cli.json").write_text('{"theme": {"name": "catppuccin"}}\n')

    operations.install(manifest.load(MANIFEST_PATH), REPO, cfg)

    cli = json.loads((cfg / "cli.json").read_text())
    assert cli["theme"]["name"] == "catppuccin"


def test_install_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    m = manifest.load(MANIFEST_PATH)
    operations.install(m, REPO, cfg)
    agents_before = (cfg / "AGENTS.md").read_text()
    operations.install(m, REPO, cfg)
    assert (cfg / "AGENTS.md").read_text() == agents_before
    assert (cfg / "AGENTS.md").read_text().count("caveman-begin") == 1


def test_text_insert_refreshes_changed_block(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "content" / "instructions" / "demo.md"
    src.parent.mkdir(parents=True)
    src.write_text("<!-- demo-start -->\nnew body\n<!-- demo-end -->\n")
    artifact = {
        "name": "demo",
        "operation": "text-insert",
        "src": "content/instructions/demo.md",
        "target": "AGENTS.md",
        "mode": "prepend",
        "anchor": "<!-- demo-start -->",
        "end_anchor": "<!-- demo-end -->",
    }

    target = cfg / "AGENTS.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "<!-- demo-start -->\nold body\n<!-- demo-end -->\n\nuser notes\n"
    )

    assert operations.text_insert(root, cfg, artifact) == "installed"
    text = target.read_text()
    assert "new body" in text
    assert "old body" not in text
    assert text.endswith("user notes\n")
    assert text.count("demo-start") == 1


def test_install_output_summarizes_components(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    output.set_verbose(False)
    cfg = config.opencode_config_dir({})

    operations.install(manifest.load(MANIFEST_PATH), REPO, cfg)

    out = capsys.readouterr().out
    assert "✓ Commands" in out
    assert "6 installed" in out
    assert "✓ Skills" in out
    assert "11 installed" in out
    assert "✓ Themes" in out
    assert "63 installed" in out
    assert "✓ Instructions" in out
    assert "2 installed" in out
    assert "✓ Configuration" in out
    assert "updated" in out
    assert "linked " not in out
    assert str(cfg) not in out


def test_install_output_reports_ready_on_rerun(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    output.set_verbose(False)
    cfg = config.opencode_config_dir({})
    m = manifest.load(MANIFEST_PATH)
    operations.install(m, REPO, cfg)
    capsys.readouterr()

    operations.install(m, REPO, cfg)

    out = capsys.readouterr().out
    assert "6 ready" in out
    assert "11 ready" in out
    assert "63 ready" in out
    assert "installed" not in out


def test_install_output_reports_conflicts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    output.set_verbose(False)
    cfg = config.opencode_config_dir({})
    (cfg / "commands").mkdir(parents=True)
    (cfg / "commands" / "fix.md").write_text("mine\n")

    operations.install(manifest.load(MANIFEST_PATH), REPO, cfg)

    out = capsys.readouterr().out
    assert "! Conflict" in out
    assert "use --force" in out
    assert "! Commands" in out
    assert "5 ready, 1 skipped" in out


def test_install_verbose_shows_file_details(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    output.set_verbose(True)
    try:
        operations.install(manifest.load(MANIFEST_PATH), REPO, cfg)
    finally:
        output.set_verbose(False)

    out = capsys.readouterr().out
    assert "linked " in out
    assert str(cfg) in out
    assert "6 installed" in out


def test_output_color_respects_no_color(monkeypatch):
    class TTY:
        def isatty(self):
            return True

    class Pipe:
        def isatty(self):
            return False

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    assert output._color_enabled(TTY())  # pylint: disable=protected-access
    assert not output._color_enabled(Pipe())  # pylint: disable=protected-access

    monkeypatch.setenv("NO_COLOR", "")
    assert not output._color_enabled(TTY())  # pylint: disable=protected-access


def test_uninstall_removes_text_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    m = manifest.load(MANIFEST_PATH)
    operations.install(m, REPO, cfg)

    # marker-delimited blocks are removed even when their interior drifted
    # (source edited after install, or hand-edited inside the tool's markers)
    agents = cfg / "AGENTS.md"
    agents.write_text(
        agents.read_text().replace(
            "Respond terse like smart caveman.", "RESPOND VERY VERBOSELY."
        )
    )

    operations.uninstall(m, REPO, cfg)
    final = agents.read_text()
    assert "caveman-begin" not in final
    assert "caveman-end" not in final
    assert "file-edit-size-limits:start" not in final
    assert "file-edit-size-limits:stop" not in final


def test_uninstall_does_not_report_removing_incomplete_block(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    artifact = {
        "name": "caveman",
        "operation": "text-insert",
        "src": "content/instructions/caveman.md",
        "target": "AGENTS.md",
        "mode": "prepend",
        "anchor": "<!-- caveman-begin -->",
        "end_anchor": "<!-- caveman-end -->",
    }
    target = cfg / "AGENTS.md"
    target.parent.mkdir(parents=True)
    original = "<!-- caveman-begin -->\nbody\n"
    target.write_text(original)

    output.set_verbose(True)
    try:
        removed = operations.uninstall({"artifacts": [artifact]}, REPO, cfg)
    finally:
        output.set_verbose(False)

    out = capsys.readouterr().out
    assert removed == 0
    assert "removing managed text block" not in out
    assert target.read_text() == original


# -------------------------------------------------------------------- sync
def test_sync_removes_stale_keeps_user_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    m = manifest.load(MANIFEST_PATH)
    operations.install(m, REPO, cfg)

    stale = cfg / "commands" / "stale-ghost.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.symlink_to(REPO / "content" / "commands" / "fix.md")

    user = cfg / "commands" / "my-own.md"
    user.write_text("user file")

    operations.sync(m, REPO, cfg)
    assert not stale.exists()
    assert user.exists()


def test_sync_prune_false_keeps_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    m = manifest.load(MANIFEST_PATH)
    operations.install(m, REPO, cfg)

    stale = cfg / "commands" / "stale-ghost.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.symlink_to(REPO / "content" / "commands" / "fix.md")

    operations.sync(m, REPO, cfg, prune=False)
    assert stale.exists()  # stale symlink left in place when pruning disabled


# ---------------------------------------------------------------- uninstall
def test_uninstall_removes_managed_only(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    m = manifest.load(MANIFEST_PATH)
    operations.install(m, REPO, cfg)
    user = cfg / "commands" / "my-own.md"
    user.write_text("keep me")
    operations.uninstall(m, REPO, cfg)
    assert user.exists()
    assert not (cfg / "commands" / "commit-message.md").exists()
    assert not (cfg / state.STATE_FILE).exists()


def test_uninstall_keeps_symlinks_to_siblings_of_content(tmp_path):
    root = tmp_path / "repo"
    content = root / "content" / "commands"
    content.mkdir(parents=True)
    (content / "fix.md").write_text("managed\n")
    sibling = root / "content-backup" / "commands"
    sibling.mkdir(parents=True)
    (sibling / "fix.md").write_text("user\n")
    numeric = root / "content2"
    numeric.mkdir()
    (numeric / "fix.md").write_text("user\n")

    cfg = tmp_path / "cfg"
    commands = cfg / "commands"
    commands.mkdir(parents=True)
    managed = commands / "managed.md"
    managed.symlink_to(content / "fix.md")
    backup = commands / "backup.md"
    backup.symlink_to(sibling / "fix.md")
    other = commands / "other.md"
    other.symlink_to(numeric / "fix.md")

    removed = operations.uninstall({"artifacts": []}, root, cfg)

    assert removed == 1
    assert not managed.exists()
    assert backup.is_symlink()
    assert other.is_symlink()


def test_uninstall_removes_legacy_copy_of_plain_symlink(tmp_path, monkeypatch):
    # A plain symlink artifact installed as a real file copy by an earlier
    # tool (not a symlink) is a managed leftover: uninstall removes it when it
    # matches the source exactly, but keeps a user-edited file at the same
    # kind of target.
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"

    src = root / "src" / "scripts" / "verify.sh"
    src.parent.mkdir(parents=True)
    src.write_text("#!/bin/sh\nmanaged\n")
    managed = {"name": "managed", "operation": "symlink", "agents": ["opencode"],
               "src": "src/scripts/verify.sh", "target": "scripts/verify.sh"}

    edited_src = root / "src" / "themes" / "theme.json"
    edited_src.parent.mkdir(parents=True)
    edited_src.write_text('{"name": "managed"}\n')
    edited = {"name": "edited", "operation": "symlink", "agents": ["opencode"],
              "src": "src/themes/theme.json", "target": "themes/theme.json"}

    manifest = {"version": 2, "artifacts": [managed, edited]}

    # Installed as real files (copies), not symlinks.
    target = cfg / "scripts" / "verify.sh"
    target.parent.mkdir(parents=True)
    target.write_text(src.read_text())
    edited_target = cfg / "themes" / "theme.json"
    edited_target.parent.mkdir(parents=True)
    edited_target.write_text('{"name": "USER EDITED"}\n')

    operations.uninstall(manifest, root, cfg)
    assert not target.exists()
    assert edited_target.exists()


# ------------------------------------------------------------------- merge
def _make_repo(path: Path, files: dict[str, str]) -> str:
    # Build a throwaway local git repo to stand in for a remote upstream.
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=path)
    for rel, content in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    git("add", "-A", cwd=path)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c", cwd=path)
    return git_out("rev-parse", "HEAD", cwd=path)


def test_merge_file_clean(tmp_path):
    base = tmp_path / "base"
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    base.write_text("header\nbase\nmiddle\nmiddle\nmiddle\nfooter\n")
    ours.write_text("header\nMY CHANGE\nmiddle\nmiddle\nmiddle\nfooter\n")
    theirs.write_text("header\nbase\nmiddle\nmiddle\nmiddle\nUPSTREAM\n")
    conflict = merge._merge_file(ours, base, theirs)
    assert conflict is False
    result = ours.read_text()
    assert "MY CHANGE" in result
    assert "UPSTREAM" in result
    assert "<<<<<<<" not in result


def test_merge_file_conflict(tmp_path):
    base = tmp_path / "base"
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    base.write_text("line\n")
    ours.write_text("MINE\n")
    theirs.write_text("THEIRS\n")
    conflict = merge._merge_file(ours, base, theirs)
    assert conflict is True
    assert "<<<<<<<" in ours.read_text()


def test_vendor_update_overwrites_and_bumps(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    sha1 = _make_repo(upstream, {"f.md": "v1\n"})
    (upstream / "f.md").write_text("v2\n")
    git("add", "-A", cwd=upstream)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c2", cwd=upstream)
    head = git_out("rev-parse", "HEAD", cwd=upstream)

    root = tmp_path / "root"
    root.mkdir()
    src = root / "src" / "commands" / "f.md"
    src.parent.mkdir(parents=True)
    src.write_text("old\n")

    mp = tmp_path / "m.toml"
    mp.write_text(
        f'version = 2\n[[artifacts]]\nname = "f"\noperation = "symlink"\nagents = ["opencode"]\n'
        f'provenance = "vendor"\nsource_repo = "{upstream}"\n'
        f'source_path = "f.md"\nsource_sha = "{sha1}"\n'
        f'src = "src/commands/f.md"\ntarget = "commands/f.md"\n'
    )
    art = manifest.find(manifest.load(mp), "f")

    monkeypatch.setattr(
        merge, "_fetch_raw",
        lambda repo, spath, ref, dest: _local_fetch(Path(repo), spath, ref, Path(dest)),
    )
    assert merge.update_artifact(mp, root, art) == 0
    assert src.read_text().strip() == "v2"
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == head


def _local_fetch(repo: Path, spath: str, ref: str, dest: Path) -> bool:
    # Offline stand-in for merge._fetch_raw: read the file straight from
    # the throwaway repo instead of hitting the network with curl.
    r = subprocess.run(
        ["git", "show", f"{ref}:{spath}"], cwd=repo, capture_output=True, text=True
    )
    if r.returncode != 0:
        return False
    dest.write_text(r.stdout)  # preserve exact bytes, incl. trailing newline
    return True


def test_fork_first_merge_pins_without_touching(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    head = _make_repo(upstream, {"f.md": "v1\n"})

    root = tmp_path / "root"
    root.mkdir()
    src = root / "src" / "commands" / "f.md"
    src.parent.mkdir(parents=True)
    src.write_text("MY CUSTOM\n")

    mp = tmp_path / "m.toml"
    mp.write_text(
        f'version = 2\n[[artifacts]]\nname = "f"\noperation = "symlink"\nagents = ["opencode"]\n'
        f'provenance = "fork"\nsource_repo = "{upstream}"\n'
        f'source_path = "f.md"\nsource_sha = ""\n'
        f'src = "src/commands/f.md"\ntarget = "commands/f.md"\n'
    )
    art = manifest.find(manifest.load(mp), "f")
    assert merge.update_artifact(mp, root, art) == 0
    assert src.read_text() == "MY CUSTOM\n"  # untouched
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == head


def test_fork_merge_keeps_customization_and_merges(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    base_content = "header\nbase\nmiddle\nmiddle\nmiddle\nfooter\n"
    sha1 = _make_repo(upstream, {"f.md": base_content})
    # upstream changes the footer
    (upstream / "f.md").write_text(
        "header\nbase\nmiddle\nmiddle\nmiddle\nUPSTREAM footer\n"
    )
    git("add", "-A", cwd=upstream)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c2", cwd=upstream)
    head = git_out("rev-parse", "HEAD", cwd=upstream)

    root = tmp_path / "root"
    root.mkdir()
    src = root / "src" / "commands" / "f.md"
    src.parent.mkdir(parents=True)
    # our fork customized the base line
    src.write_text("header\nMY CUSTOMIZATION\nmiddle\nmiddle\nmiddle\nfooter\n")

    mp = tmp_path / "m.toml"
    mp.write_text(
        f'version = 2\n[[artifacts]]\nname = "f"\noperation = "symlink"\nagents = ["opencode"]\n'
        f'provenance = "fork"\nsource_repo = "{upstream}"\n'
        f'source_path = "f.md"\nsource_sha = "{sha1}"\n'
        f'src = "src/commands/f.md"\ntarget = "commands/f.md"\n'
    )
    art = manifest.find(manifest.load(mp), "f")
    monkeypatch.setattr(
        merge, "_fetch_raw",
        lambda repo, spath, ref, dest: _local_fetch(Path(repo), spath, ref, Path(dest)),
    )
    assert merge.update_artifact(mp, root, art) == 0
    result = src.read_text()
    assert "MY CUSTOMIZATION" in result
    assert "UPSTREAM footer" in result
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == head


def test_fork_conflict_lifecycle_converges(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    sha1 = _make_repo(upstream, {"f.md": "a\nb\nc\n\n\n\n"})
    # upstream rewrites the tail region our fork also touches
    (upstream / "f.md").write_text("a\nb\nC\n")
    git("add", "-A", cwd=upstream)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c2", cwd=upstream)
    head = git_out("rev-parse", "HEAD", cwd=upstream)

    root = tmp_path / "root"
    src = root / "src" / "commands" / "f.md"
    src.parent.mkdir(parents=True)
    src.write_text("a\nb\nc\n\n\n\nOUR_EXTRA\n")

    mp = tmp_path / "m.toml"
    mp.write_text(
        f'version = 2\n[[artifacts]]\nname = "f"\noperation = "symlink"\nagents = ["opencode"]\n'
        f'provenance = "fork"\nsource_repo = "{upstream}"\n'
        f'source_path = "f.md"\nsource_sha = "{sha1}"\n'
        f'src = "src/commands/f.md"\ntarget = "commands/f.md"\n'
    )
    art = manifest.find(manifest.load(mp), "f")
    monkeypatch.setattr(
        merge, "_fetch_raw",
        lambda repo, spath, ref, dest: _local_fetch(Path(repo), spath, ref, Path(dest)),
    )

    # Pull conflicts: markers land and the base advances to upstream HEAD.
    assert merge.update_artifact(mp, root, art) == 0
    assert "<<<<<<<" in src.read_text()
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == head

    # Unresolved markers must block further updates instead of re-merging the
    # marked file (which nests markers and never converges).
    art = manifest.find(manifest.load(mp), "f")  # each run reloads the manifest
    assert merge.update_artifact(mp, root, art, check_only=True) == merge.ERROR
    assert src.read_text().count("<<<<<<<") == 1

    # Resolve, keeping both the upstream change and our addition.
    src.write_text("a\nb\nC\n\nOUR_EXTRA\n")

    # The resolved file is based on upstream HEAD, so the re-run finalizes
    # cleanly rather than replaying the same merge.
    art = manifest.find(manifest.load(mp), "f")
    assert merge.update_artifact(mp, root, art) == 0
    assert "<<<<<<<" not in src.read_text()
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == head


# ------------------------------------------------------------ check / shims
def test_check_valid_source_path_reports_behind(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    head = _make_repo(upstream, {"f.md": "v1\n"})
    root = tmp_path / "root"
    root.mkdir()
    mp = tmp_path / "m.toml"
    mp.write_text(
        f'version = 2\n[[artifacts]]\nname = "f"\noperation = "symlink"\nagents = ["opencode"]\n'
        f'provenance = "vendor"\nsource_repo = "{upstream}"\n'
        f'source_path = "f.md"\nsource_sha = ""\n'
        f'src = "src/f.md"\ntarget = "f.md"\n'
    )
    art = manifest.find(manifest.load(mp), "f")
    monkeypatch.setattr(
        merge, "_fetch_raw",
        lambda repo, spath, ref, dest: _local_fetch(Path(repo), spath, ref, Path(dest)),
    )
    assert merge.update_artifact(mp, root, art, check_only=True) == merge.DRIFT
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == ""  # no mutation


# ---------------------------------------------------------------- entrypoint
def test_oc_entrypoint_paths_resolve_to_repo():
    import rivet  # noqa: PLC0415

    # Guards the CLI entrypoint against ROOT_PATH/MANIFEST_PATH regressions: an off-by-one
    # ROOT_PATH or a wrong manifest filename makes every subcommand fail.
    assert rivet.ROOT_PATH == REPO
    assert rivet.MANIFEST_PATH == REPO / "manifest.toml"
    assert rivet.MANIFEST_PATH.exists()


def test_cli_init_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(rivet, "_bootstrap_shell_command", lambda: None)

    # --no-project: keep this test hermetic. Per-project init (OpenSpec,
    # codebase-memory-mcp) would mutate the real working tree and PATH tools.
    assert rivet.main(["init", "--no-project"]) == 0
    cfg = tmp_path / "cfg"
    assert (cfg / "AGENTS.md").exists()
    assert (cfg / "commands" / "commit-message.md").exists()


def test_cli_missing_manifest_returns_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    import rivet  # noqa: PLC0415

    # A manifest we cannot find must fail cleanly (exit 2), not traceback.
    original = rivet.MANIFEST_PATH
    rivet.MANIFEST_PATH = tmp_path / "nope.toml"
    try:
        assert rivet.main(["init", "--no-project"]) == 2
    finally:
        rivet.MANIFEST_PATH = original
    assert "manifest not found" in capsys.readouterr().err


# --------------------------------------------------------- dir artifacts
def test_vendor_dir_update_prunes_deleted(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    _make_repo(upstream, {"skills/x/a.md": "a1\n", "skills/x/b.md": "b1\n"})
    # upstream deletes b.md and adds c.md
    (upstream / "skills" / "x" / "b.md").unlink()
    (upstream / "skills" / "x" / "c.md").write_text("c1\n")
    git("add", "-A", cwd=upstream)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c2", cwd=upstream)
    head = git_out("rev-parse", "HEAD", cwd=upstream)

    root = tmp_path / "root"
    src = root / "src" / "skills" / "x"
    src.mkdir(parents=True)
    (src / "a.md").write_text("old a\n")
    (src / "b.md").write_text("old b\n")  # deleted upstream — must be pruned

    mp = tmp_path / "m.toml"
    mp.write_text(
        f'version = 2\n[[artifacts]]\nname = "x"\noperation = "symlink"\nagents = ["opencode"]\n'
        f'provenance = "vendor"\nsource_repo = "{upstream}"\n'
        f'source_path = "skills/x"\nsource_sha = ""\n'
        f'src = "src/skills/x"\ntarget = "skills/x"\n'
    )
    art = manifest.find(manifest.load(mp), "x")
    assert merge.update_artifact(mp, root, art) == 0
    assert (src / "a.md").read_text().strip() == "a1"
    assert (src / "c.md").read_text().strip() == "c1"
    assert not (src / "b.md").exists()  # pruned
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == head


def test_fork_dir_merge_applies_upstream_keeps_custom(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    sha1 = _make_repo(upstream, {"skills/x/f.md": "header\nbase\nmiddle\nfooter\n"})
    (upstream / "skills" / "x" / "f.md").write_text(
        "header\nbase\nmiddle\nUPSTREAM footer\n"
    )
    git("add", "-A", cwd=upstream)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c2", cwd=upstream)
    head = git_out("rev-parse", "HEAD", cwd=upstream)

    root = tmp_path / "root"
    src = root / "src" / "skills" / "x"
    src.mkdir(parents=True)
    (src / "f.md").write_text("header\nMY CUSTOM\nmiddle\nfooter\n")

    mp = tmp_path / "m.toml"
    mp.write_text(
        f'version = 2\n[[artifacts]]\nname = "x"\noperation = "symlink"\nagents = ["opencode"]\n'
        f'provenance = "fork"\nsource_repo = "{upstream}"\n'
        f'source_path = "skills/x"\nsource_sha = "{sha1}"\n'
        f'src = "src/skills/x"\ntarget = "skills/x"\n'
    )
    art = manifest.find(manifest.load(mp), "x")
    assert merge.update_artifact(mp, root, art) == 0
    result = (src / "f.md").read_text()
    assert "MY CUSTOM" in result
    assert "UPSTREAM footer" in result
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == head


def test_fork_base_fetch_failure_does_not_clobber(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    sha1 = _make_repo(upstream, {"f.md": "base\n"})
    (upstream / "f.md").write_text("upstream new\n")
    git("add", "-A", cwd=upstream)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c2", cwd=upstream)

    root = tmp_path / "root"
    root.mkdir()
    src = root / "src" / "commands" / "f.md"
    src.parent.mkdir(parents=True)
    src.write_text("MY CUSTOM\n")

    mp = tmp_path / "m.toml"
    mp.write_text(
        f'version = 2\n[[artifacts]]\nname = "f"\noperation = "symlink"\nagents = ["opencode"]\n'
        f'provenance = "fork"\nsource_repo = "{upstream}"\n'
        f'source_path = "f.md"\nsource_sha = "{sha1}"\n'
        f'src = "src/commands/f.md"\ntarget = "commands/f.md"\n'
    )
    art = manifest.find(manifest.load(mp), "f")
    # base fetch always fails — update must fail cleanly and leave local intact
    monkeypatch.setattr(merge, "_fetch_raw", lambda repo, spath, ref, dest: False)
    assert merge.update_artifact(mp, root, art) == merge.ERROR
    assert src.read_text() == "MY CUSTOM\n"  # untouched
    assert manifest.load(mp)["artifacts"][0]["source_sha"] == sha1  # not bumped


# ------------------------------------------------------------ replace-copy
def _replace_artifact() -> dict:
    return {
        "name": "cmd",
        "operation": "symlink",
        "provenance": "original",
        "entries": [
            {
                "src": "src/commands/cmd.md",
                "target": "commands/cmd.md",
                "replace": {"<SCRIPT>": "{config_dir}/scripts/run.sh"},
            }
        ],
    }


def test_replace_upgrade_from_symlink_does_not_clobber_source(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "src" / "commands" / "cmd.md"
    src.parent.mkdir(parents=True)
    src.write_text("run <SCRIPT>\n")

    # old install left a plain symlink at the target
    target = cfg / "commands" / "cmd.md"
    target.parent.mkdir(parents=True)
    target.symlink_to(src)

    operations.symlink(root, cfg, _replace_artifact())
    # repo source placeholder is intact (not clobbered through the symlink)
    assert "<SCRIPT>" in src.read_text()
    # target is now a substituted copy, not a symlink
    assert not target.is_symlink()
    assert f"{cfg}/scripts/run.sh" in target.read_text()


def test_replace_copy_honors_force(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "src" / "commands" / "cmd.md"
    src.parent.mkdir(parents=True)
    src.write_text("run <SCRIPT>\n")

    target = cfg / "commands" / "cmd.md"
    target.parent.mkdir(parents=True)
    target.write_text("USER FILE\n")

    operations.symlink(root, cfg, _replace_artifact())
    assert target.read_text() == "USER FILE\n"  # kept without --force
    operations.symlink(root, cfg, _replace_artifact(), force=True)
    assert f"{cfg}/scripts/run.sh" in target.read_text()  # overwritten


def test_replace_copy_force_backs_up_user_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "src" / "commands" / "cmd.md"
    src.parent.mkdir(parents=True)
    src.write_text("run <SCRIPT>\n")

    target = cfg / "commands" / "cmd.md"
    target.parent.mkdir(parents=True)
    target.write_text("USER FILE\n")

    operations.symlink(root, cfg, _replace_artifact(), force=True)

    backups = list((cfg / state.BACKUP_DIR).rglob("cmd.md"))
    assert backups
    assert backups[0].read_text() == "USER FILE\n"


def test_force_symlink_backs_up_user_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "content" / "skills" / "demo" / "SKILL.md"
    src.parent.mkdir(parents=True)
    src.write_text("managed\n")
    artifact = {
        "name": "demo",
        "operation": "symlink",
        "src": "content/skills/demo",
        "target": "skills/demo",
    }

    target = cfg / "skills" / "demo"
    target.mkdir(parents=True)
    (target / "NOTES.md").write_text("user notes\n")

    operations.symlink(root, cfg, artifact, force=True)

    assert target.is_symlink()
    backups = list((cfg / state.BACKUP_DIR).rglob("NOTES.md"))
    assert backups
    assert backups[0].read_text() == "user notes\n"


def test_replace_copy_refreshes_after_source_change(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "src" / "commands" / "cmd.md"
    src.parent.mkdir(parents=True)
    src.write_text("old run <SCRIPT>\n")

    operations.symlink(root, cfg, _replace_artifact())
    target = cfg / "commands" / "cmd.md"
    assert "old run" in target.read_text()

    src.write_text("new run <SCRIPT>\n")
    operations.symlink(root, cfg, _replace_artifact())

    assert "new run" in target.read_text()
    assert "old run" not in target.read_text()


def test_replace_copy_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "src" / "commands" / "cmd.md"
    src.parent.mkdir(parents=True)
    src.write_text("run <SCRIPT>\n")

    operations.symlink(root, cfg, _replace_artifact())
    content = (cfg / "commands" / "cmd.md").read_text()
    operations.symlink(root, cfg, _replace_artifact())
    assert (cfg / "commands" / "cmd.md").read_text() == content  # unchanged


def test_uninstall_keeps_user_file_at_replace_target(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "src" / "commands" / "cmd.md"
    src.parent.mkdir(parents=True)
    src.write_text("run <SCRIPT>\n")

    artifact = _replace_artifact()
    manifest = {"version": 2, "artifacts": [artifact]}

    # a user's real file (content differs from the managed copy) is kept
    target = cfg / "commands" / "cmd.md"
    target.parent.mkdir(parents=True)
    target.write_text("USER EDITED CONTENT\n")
    operations.uninstall(manifest, root, cfg)
    assert target.exists()

    # the managed copy is removed
    target.unlink()
    operations.symlink(root, cfg, artifact)
    assert target.exists()
    operations.uninstall(manifest, root, cfg)
    assert not target.exists()


def test_uninstall_keeps_user_file_that_mentions_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "src" / "commands" / "cmd.md"
    src.parent.mkdir(parents=True)
    src.write_text("run <SCRIPT>\n")

    artifact = _replace_artifact()
    manifest = {"version": 2, "artifacts": [artifact]}

    target = cfg / "commands" / "cmd.md"
    target.parent.mkdir(parents=True)
    target.write_text(f"my own file mentions {cfg}/scripts/run.sh\n")

    operations.uninstall(manifest, root, cfg)
    assert target.exists()


def test_uninstall_removes_stale_substituted_copy(tmp_path, monkeypatch):
    # A substituted copy installed from an older source must still be removed
    # when the repo source drifted since install. It embeds the tool's
    # resolved config-dir path, which marks it as managed.
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    root = tmp_path / "root"
    src = root / "src" / "commands" / "cmd.md"
    src.parent.mkdir(parents=True)
    src.write_text("old run <SCRIPT> text\n")

    artifact = _replace_artifact()
    manifest = {"version": 2, "artifacts": [artifact]}

    operations.install(manifest, root, cfg)
    target = cfg / "commands" / "cmd.md"
    assert target.exists()

    # source drifts after install (e.g. the user edited the repo command)
    src.write_text("new run <SCRIPT> wording\n")
    operations.uninstall(manifest, root, cfg)
    assert not target.exists()


# ---------------------------------------------------- config_merge guards
def test_config_merge_refuses_unparseable_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    target = cfg / "opencode.json"
    target.parent.mkdir(parents=True)
    target.write_text("{ not json !! }\n")
    artifact = {"config_file": "opencode.json", "config_path": "a.b",
                "value": '"x"'}
    before = target.read_text()
    with pytest.raises(ValueError):
        operations.config_merge(tmp_path, cfg, artifact)
    assert target.read_text() == before  # untouched


def test_config_merge_refuses_non_object_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OC_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = config.opencode_config_dir({})
    target = cfg / "opencode.json"
    target.parent.mkdir(parents=True)
    target.write_text("[1, 2, 3]\n")
    artifact = {"config_file": "opencode.json", "config_path": "a.b",
                "value": '"x"'}
    with pytest.raises(ValueError):
        operations.config_merge(tmp_path, cfg, artifact)


# ------------------------------------------------------------ validation
def test_validate_rejects_non_string_replace_value():
    data = {
        "version": 2,
        "artifacts": [{
            "name": "x", "operation": "symlink", "provenance": "original", "agents": ["opencode"],
            "entries": [{"src": "a", "target": "b",
                         "replace": {"<X>": 123}}],
        }],
    }
    with pytest.raises(manifest.ManifestError):
        manifest.validate(data)


def test_validate_rejects_single_form_replace():
    data = {
        "version": 2,
        "artifacts": [{
            "name": "x", "operation": "symlink", "provenance": "original", "agents": ["opencode"],
            "src": "a", "target": "b", "replace": {"<X>": "y"},
        }],
    }
    with pytest.raises(manifest.ManifestError):
        manifest.validate(data)


def test_validate_accepts_empty_string_config_value():
    data = {
        "version": 2,
        "artifacts": [{
            "name": "x", "operation": "config-merge", "provenance": "original", "agents": ["opencode"],
            "config_file": "cli.json", "config_path": "theme.name", "value": "",
        }],
    }
    manifest.validate(data)  # must not raise


def test_validate_rejects_non_string_config_value():
    data = {
        "version": 2,
        "artifacts": [{
            "name": "x", "operation": "config-merge", "provenance": "original", "agents": ["opencode"],
            "config_file": "cli.json", "config_path": "theme.name", "value": 123,
        }],
    }
    with pytest.raises(manifest.ManifestError):
        manifest.validate(data)


# ------------------------------------------------------------------ project
def test_git_root_resolves_toplevel_from_subdir(tmp_path):
    git("init", cwd=tmp_path)
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert project.git_root(sub) == tmp_path.resolve()


def test_git_root_none_outside_repo(tmp_path):
    assert project.git_root(tmp_path) is None


def test_prepend_instruction_is_idempotent(tmp_path):
    src = tmp_path / "instruction.md"
    src.write_text(
        "<!-- codebase-memory-mcp:start -->\n# block\n<!-- codebase-memory-mcp:end -->\n"
    )
    root = tmp_path / "proj"
    root.mkdir()
    (root / "AGENTS.md").write_text("existing\n")

    project._prepend_instruction(root, src)
    first = (root / "AGENTS.md").read_text()
    assert first.startswith("<!-- codebase-memory-mcp:start -->")
    assert first.endswith("existing\n")

    project._prepend_instruction(root, src)
    assert (root / "AGENTS.md").read_text() == first

    src.write_text(
        "<!-- codebase-memory-mcp:start -->\n# new block\n"
        "<!-- codebase-memory-mcp:end -->\n"
    )
    project._prepend_instruction(root, src)
    updated = (root / "AGENTS.md").read_text()
    assert "# new block" in updated
    assert "# block" not in updated
    assert updated.endswith("existing\n")
    assert updated.count("codebase-memory-mcp:start") == 1


def test_install_plugin(tmp_path):
    src = tmp_path / "CodebaseMemoryReminder.ts"
    src.write_text("// plugin")
    root = tmp_path / "proj"
    root.mkdir()
    project._install_plugin(root, src)
    assert (root / ".opencode" / "plugins" / "CodebaseMemoryReminder.ts").read_text() == (
        "// plugin"
    )


def test_merge_mcp_config_writes_v2_shape(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project._merge_mcp_config(root, "/bin/cbm")
    data = json.loads((root / ".opencode" / "opencode.json").read_text())
    assert data["mcp"]["servers"]["codebase-memory-mcp"] == {
        "type": "local",
        "command": ["/bin/cbm"],
    }


def test_merge_mcp_config_idempotent(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project._merge_mcp_config(root, "/bin/cbm")
    first = (root / ".opencode" / "opencode.json").read_text()

    project._merge_mcp_config(root, "/bin/cbm")
    assert (root / ".opencode" / "opencode.json").read_text() == first


def test_merge_mcp_config_upgrades_kit_legacy_entry(tmp_path):
    # The exact V1 payload this tool wrote is upgraded to the V2 shape,
    # keeping the resolved command.
    root = tmp_path / "proj"
    (root / ".opencode").mkdir(parents=True)
    (root / ".opencode" / "opencode.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "codebase-memory-mcp": {
                        "enabled": True,
                        "type": "local",
                        "command": ["/old/cbm"],
                    }
                }
            }
        )
    )
    project._merge_mcp_config(root, "/bin/cbm")
    data = json.loads((root / ".opencode" / "opencode.json").read_text())
    assert "codebase-memory-mcp" not in data["mcp"]
    assert data["mcp"]["servers"]["codebase-memory-mcp"]["command"] == ["/bin/cbm"]


def test_merge_mcp_config_preserves_user_entry(tmp_path):
    root = tmp_path / "proj"
    (root / ".opencode").mkdir(parents=True)
    (root / ".opencode" / "opencode.json").write_text(
        json.dumps({"mcp": {"codebase-memory-mcp": {"command": ["/custom"]}}})
    )
    project._merge_mcp_config(root, "/bin/cbm")
    data = json.loads((root / ".opencode" / "opencode.json").read_text())
    assert data["mcp"]["codebase-memory-mcp"]["command"] == ["/custom"]
    assert "servers" not in data["mcp"]


def test_merge_mcp_config_preserves_custom_v2_entry(tmp_path):
    root = tmp_path / "proj"
    (root / ".opencode").mkdir(parents=True)
    entry = {
        "type": "local",
        "command": ["npx", "-y", "codebase-memory-mcp"],
        "environment": {"TOKEN": "secret"},
    }
    (root / ".opencode" / "opencode.json").write_text(
        json.dumps({"mcp": {"servers": {"codebase-memory-mcp": entry}}})
    )

    project._merge_mcp_config(root, "/bin/codebase-memory-mcp")

    data = json.loads((root / ".opencode" / "opencode.json").read_text())
    assert data["mcp"]["servers"]["codebase-memory-mcp"] == entry


def test_merge_mcp_config_refreshes_moved_binary(tmp_path):
    root = tmp_path / "proj"
    (root / ".opencode").mkdir(parents=True)
    (root / ".opencode" / "opencode.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "servers": {
                        "codebase-memory-mcp": {
                            "type": "local",
                            "command": ["/old/codebase-memory-mcp"],
                        }
                    }
                }
            }
        )
    )

    project._merge_mcp_config(root, "/new/codebase-memory-mcp")

    data = json.loads((root / ".opencode" / "opencode.json").read_text())
    assert data["mcp"]["servers"]["codebase-memory-mcp"]["command"] == [
        "/new/codebase-memory-mcp"
    ]


def test_merge_mcp_config_reads_jsonc(tmp_path):
    root = tmp_path / "proj"
    directory = root / ".opencode"
    directory.mkdir(parents=True)
    config = directory / "opencode.jsonc"
    config.write_text(
        '{\n'
        '  // project config\n'
        '  "theme": "x",\n'
        '  "mcp": {"servers": {"other": {"type": "local", "command": ["x"]}}},\n'
        '}\n'
    )

    project._merge_mcp_config(root, "/bin/cbm")

    data = json.loads(jsonc.strip_jsonc(config.read_text()))
    assert data["theme"] == "x"
    assert data["mcp"]["servers"]["other"] == {"type": "local", "command": ["x"]}
    assert data["mcp"]["servers"]["codebase-memory-mcp"] == {
        "type": "local",
        "command": ["/bin/cbm"],
    }
    assert not (directory / "opencode.json").exists()


def test_merge_mcp_config_prefers_existing_jsonc(tmp_path):
    root = tmp_path / "proj"
    directory = root / ".opencode"
    directory.mkdir(parents=True)
    jsonc_config = directory / "opencode.jsonc"
    jsonc_config.write_text('{\n  // keep me\n  "theme": "jsonc"\n}\n')
    json_config = directory / "opencode.json"
    json_config.write_text('{"theme": "json"}\n')

    project._merge_mcp_config(root, "/bin/cbm")

    data = json.loads(jsonc.strip_jsonc(jsonc_config.read_text()))
    assert data["mcp"]["servers"]["codebase-memory-mcp"]["command"] == ["/bin/cbm"]
    assert json_config.read_text() == '{"theme": "json"}\n'


def test_mcp_entry_present_reads_jsonc(tmp_path):
    root = tmp_path / "proj"
    directory = root / ".opencode"
    directory.mkdir(parents=True)
    (directory / "opencode.jsonc").write_text(
        '{\n  // project config\n'
        '  "mcp": {"servers": {"codebase-memory-mcp": '
        '{"type": "local", "command": ["/bin/cbm"]}}}\n}\n'
    )

    assert project.mcp_entry_present(root)


def test_uninstall_project_removes_entry_from_jsonc(tmp_path):
    root = tmp_path / "proj"
    directory = root / ".opencode"
    directory.mkdir(parents=True)
    config = directory / "opencode.jsonc"
    config.write_text(
        '{\n  // project config\n'
        '  "theme": "x",\n'
        '  "mcp": {"servers": {"codebase-memory-mcp": '
        '{"type": "local", "command": ["/bin/codebase-memory-mcp"]}}}\n}\n'
    )

    project.uninstall_project(root, tmp_path / "missing.ts")

    data = json.loads(jsonc.strip_jsonc(config.read_text()))
    assert data["theme"] == "x"
    assert "codebase-memory-mcp" not in data["mcp"]["servers"]
    assert not (directory / "opencode.json").exists()


def test_uninstall_keeps_custom_mcp_entry(tmp_path):
    root = tmp_path / "proj"
    (root / ".opencode").mkdir(parents=True)
    entry = {
        "type": "local",
        "command": ["npx", "-y", "codebase-memory-mcp"],
        "environment": {"TOKEN": "secret"},
    }
    config = root / ".opencode" / "opencode.json"
    config.write_text(
        json.dumps({"mcp": {"servers": {"codebase-memory-mcp": entry}}})
    )

    project.uninstall_project(root, tmp_path / "missing.ts")

    data = json.loads(config.read_text())
    assert data["mcp"]["servers"]["codebase-memory-mcp"] == entry


def test_init_project_skips_outside_repo(tmp_path):
    # Not a git repo: init must no-op without invoking any tool.
    calls = []
    confirm = lambda prompt: calls.append(prompt) or True  # noqa: E731
    project.init_project(tmp_path, confirm, tmp_path / "no.md", tmp_path / "no.ts")
    assert calls == []
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".opencode").exists()


def test_init_openspec_uses_opencode_tools(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    calls = []
    monkeypatch.setattr(
        project.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or _ok_run(cmd, **kw),
    )
    project._init_openspec(root, "/bin/openspec")
    assert calls[0] == ["/bin/openspec", "init", "--tools", "opencode"]


def _write_instruction(tmp_path) -> Path:
    src = tmp_path / "instruction.md"
    src.write_text(
        "<!-- codebase-memory-mcp:start -->\n# block\n<!-- codebase-memory-mcp:end -->\n"
    )
    return src


def _R(code, stdout=""):
    return type("R", (), {"returncode": code, "stdout": stdout, "stderr": ""})()


def _index_subprocess(status_code, index_code):
    """Fake subprocess.run branching on index_status vs index_repository."""
    def run(cmd, **kw):
        code = index_code if "index_repository" in " ".join(cmd) else status_code
        return _R(code)
    return run


def test_initial_index_skips_when_indexed(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    calls = []
    monkeypatch.setattr(project.subprocess, "run", lambda cmd, **kw: calls.append(" ".join(cmd)) or _R(0))
    project._initial_index(root, "/bin/cbm")
    assert not any("index_repository" in c for c in calls)
    assert capsys.readouterr().out == ""


def test_initial_index_indexes_when_not_indexed(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    calls = []
    monkeypatch.setattr(
        project.subprocess, "run",
        lambda cmd, **kw: calls.append(" ".join(cmd)) or _index_subprocess(1, 0)(cmd, **kw),
    )
    project._initial_index(root, "/bin/cbm")
    index_calls = [c for c in calls if "index_repository" in c]
    assert index_calls
    assert "--mode full" in index_calls[0]
    status_calls = [c for c in calls if "index_status" in c]
    assert status_calls
    assert str(root.resolve()).lstrip("/").replace("/", "-") in status_calls[0]
    assert "Indexing" in capsys.readouterr().out


def test_initial_index_warns_on_failure(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setattr(project.subprocess, "run", _index_subprocess(1, 1))
    project._initial_index(root, "/bin/cbm")  # must not raise
    assert "graph may be empty" in capsys.readouterr().out


def _fake_init_run(root, indexed):
    """Fake subprocess.run for init_project: handle git_root + index_status."""
    def run(cmd, **kw):
        argv = " ".join(cmd)
        if "rev-parse" in argv:
            return _R(0, str(root))
        return _R(0 if indexed else 1)
    return run


def test_init_project_indexes_repository(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    git("init", cwd=root)
    calls = []
    monkeypatch.setattr(project, "_ensure_tool", lambda *a, **k: "/bin/cbm")
    monkeypatch.setattr(project, "_init_openspec", lambda *a, **k: True)
    monkeypatch.setattr(project, "_init_codebase", lambda *a, **k: None)
    monkeypatch.setattr(
        project.subprocess, "run",
        lambda cmd, **kw: calls.append(" ".join(cmd)) or _fake_init_run(root, False)(cmd, **kw),
    )
    project.init_project(root, lambda p: True, tmp_path / "i.md", tmp_path / "oc.ts")
    assert sum(1 for c in calls if "index_status" in c) == 1


def test_init_project_idempotent_skips_index(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    git("init", cwd=root)
    calls = []
    monkeypatch.setattr(project, "_ensure_tool", lambda *a, **k: "/bin/cbm")
    monkeypatch.setattr(project, "_init_openspec", lambda *a, **k: True)
    monkeypatch.setattr(project, "_init_codebase", lambda *a, **k: None)
    monkeypatch.setattr(
        project.subprocess, "run",
        lambda cmd, **kw: calls.append(" ".join(cmd)) or _fake_init_run(root, True)(cmd, **kw),
    )
    project.init_project(root, lambda p: True, tmp_path / "i.md", tmp_path / "oc.ts")
    assert not any("index_repository" in c for c in calls)


def test_ensure_tool_prompts_with_command_and_skips_on_decline(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # ensure the bin is "not installed"
    calls = []
    confirm = lambda prompt: calls.append(prompt) or False  # noqa: E731 decline
    result = project._ensure_tool("FakeTool", "fake-bin-xyz", "echo install it", confirm)
    assert result is None
    assert calls, "must ask before installing"
    # the exact install command is shown so the user knows what will run
    assert "echo install it" in calls[0]


def _timeout_run(cmd, **kwargs):
    raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))


def test_run_checked_times_out(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project.subprocess, "run", _timeout_run)

    with pytest.raises(subprocess.CalledProcessError):
        project._run_checked(["/bin/slow"], cwd=tmp_path)
    assert "timed out" in capsys.readouterr().out


def test_init_openspec_reports_timeout(tmp_path, monkeypatch, capsys):
    seen = {}

    def run(cmd, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

    monkeypatch.setattr(project.subprocess, "run", run)

    assert project._init_openspec(tmp_path, "/bin/openspec") is False
    assert seen["timeout"] == project.COMMAND_TIMEOUT
    assert "OpenSpec" in capsys.readouterr().out


def test_set_runtime_flags_warns_on_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project.subprocess, "run", _timeout_run)

    assert project._set_runtime_flags(tmp_path, "/bin/cbm") is False
    out = capsys.readouterr().out
    assert "auto_index" in out


def test_ensure_tool_times_out_with_visible_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    seen = {}

    def run(cmd, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

    monkeypatch.setattr(project.subprocess, "run", run)

    result = project._ensure_tool(
        "FakeTool", "fake-bin-xyz", "echo install it", lambda prompt: True
    )

    assert result is None
    assert seen["timeout"] == project.INSTALL_TIMEOUT
    assert not seen.get("capture_output")
    assert "timed out" in capsys.readouterr().out


def test_initial_index_times_out(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setattr(project, "is_indexed", lambda *args, **kwargs: False)
    monkeypatch.setattr(project.subprocess, "run", _timeout_run)

    assert project._initial_index(root, "/bin/cbm") is False
    assert "timed out" in capsys.readouterr().out


def test_validate_requires_agents():
    data = {
        "version": 2,
        "artifacts": [{
            "name": "x", "operation": "symlink", "provenance": "original",
            "src": "a", "target": "b",
        }],
    }
    with pytest.raises(manifest.ManifestError):
        manifest.validate(data)


def test_validate_rejects_unknown_agent():
    data = {
        "version": 2,
        "artifacts": [{
            "name": "x", "operation": "symlink", "provenance": "original",
            "agents": ["claude"], "src": "a", "target": "b",
        }],
    }
    with pytest.raises(manifest.ManifestError):
        manifest.validate(data)


def test_validate_rejects_version_1():
    data = {
        "version": 1,
        "artifacts": [{
            "name": "x", "operation": "symlink", "provenance": "original",
            "agents": ["opencode"], "src": "a", "target": "b",
        }],
    }
    with pytest.raises(manifest.ManifestError):
        manifest.validate(data)


# ----------------------------------------------------------- shell rc bootstrap
def test_rc_path_mapping():
    assert shell_rc.rc_path("zsh") == Path.home() / ".zshrc"
    assert shell_rc.rc_path("bash") == Path.home() / ".bashrc"
    assert shell_rc.rc_path("fish") == Path.home() / ".config" / "fish" / "config.fish"
    assert shell_rc.rc_path("tcsh") is None
    assert shell_rc.rc_path(None) is None
    assert shell_rc.rc_path("") is None


def test_rc_path_fish_honors_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert shell_rc.rc_path("fish") == tmp_path / "fish" / "config.fish"


def test_login_shell_unknown(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    assert shell_rc.login_shell() is None
    monkeypatch.setenv("SHELL", "/bin/tcsh")
    assert shell_rc.login_shell() is None
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert shell_rc.login_shell() == "zsh"


def test_bootstrap_block_fish():
    b = shell_rc.bootstrap_block(Path("/kit/bin/rivet"), "fish")
    assert "function rivet" in b
    assert "/kit/bin/rivet $argv" in b


def test_bootstrap_block_posix():
    b = shell_rc.bootstrap_block(Path("/kit/bin/rivet"), "zsh")
    assert 'rivet() { /kit/bin/rivet "$@"; }' in b


def test_bootstrap_block_quotes_paths_with_spaces():
    path = Path("/kit dir/bin/rivet")
    posix = shell_rc.bootstrap_block(path, "zsh")
    assert "'/kit dir/bin/rivet' \"$@\"" in posix
    fish = shell_rc.bootstrap_block(path, "fish")
    assert "'/kit dir/bin/rivet' $argv" in fish


def test_add_block_idempotent(tmp_path):
    rc = tmp_path / ".zshrc"
    block = shell_rc.bootstrap_block(Path("/kit/bin/rivet"), "zsh")
    assert shell_rc.add_block(rc, block) is True
    assert shell_rc.add_block(rc, block) is False
    assert rc.read_text().count("rivet begin") == 1


def test_remove_block(tmp_path):
    rc = tmp_path / ".zshrc"
    rc.write_text("export FOO=1\n")
    block = shell_rc.bootstrap_block(Path("/kit/bin/rivet"), "zsh")
    shell_rc.add_block(rc, block)
    assert shell_rc.remove_block(rc) is True
    assert shell_rc.remove_block(rc) is False
    text = rc.read_text()
    assert "rivet" not in text
    assert "export FOO=1" in text


def test_ensure_block_replaces_after_stray_end_marker(tmp_path):
    rc = tmp_path / ".zshrc"
    rc.write_text(
        "prefix\n"
        "# <<< rivet end <<<\n"
        "middle\n"
        "# >>> rivet begin >>>\n"
        'rivet() { /old/bin/rivet "$@"; }\n'
        "# <<< rivet end <<<\n"
        "suffix\n"
    )
    block = shell_rc.bootstrap_block(Path("/new/bin/rivet"), "zsh")

    assert shell_rc.ensure_block(rc, block) == "updated"

    text = rc.read_text()
    assert text.count("middle") == 1
    assert "/old/bin/rivet" not in text
    assert "/new/bin/rivet" in text


def test_remove_block_after_stray_end_marker(tmp_path):
    rc = tmp_path / ".zshrc"
    rc.write_text(
        "prefix\n"
        "# <<< rivet end <<<\n"
        "middle\n"
        "# >>> rivet begin >>>\n"
        'rivet() { /old/bin/rivet "$@"; }\n'
        "# <<< rivet end <<<\n"
        "suffix\n"
    )

    assert shell_rc.remove_block(rc) is True

    text = rc.read_text()
    assert "rivet begin" not in text
    assert "/old/bin/rivet" not in text
    assert text.count("middle") == 1
    assert "prefix" in text
    assert "suffix" in text


def test_bootstrap_registers_without_tty(tmp_path, monkeypatch, capsys):
    rc = tmp_path / ".zshrc"
    monkeypatch.setattr(shell_rc, "login_shell", lambda: "zsh")
    monkeypatch.setattr(shell_rc, "rc_path", lambda shell: rc)
    rivet._bootstrap_shell_command()
    assert "rivet()" in rc.read_text()
    assert "Shell command" in capsys.readouterr().out


def test_bootstrap_is_idempotent(tmp_path, monkeypatch):
    rc = tmp_path / ".zshrc"
    monkeypatch.setattr(shell_rc, "login_shell", lambda: "zsh")
    monkeypatch.setattr(shell_rc, "rc_path", lambda shell: rc)
    rivet._bootstrap_shell_command()
    rivet._bootstrap_shell_command()
    assert rc.read_text().count("rivet begin") == 1


def test_bootstrap_updates_stale_block(tmp_path, monkeypatch, capsys):
    rc = tmp_path / ".zshrc"
    rc.write_text(shell_rc.bootstrap_block(Path("/old/bin/rivet"), "zsh"))
    monkeypatch.setattr(shell_rc, "login_shell", lambda: "zsh")
    monkeypatch.setattr(shell_rc, "rc_path", lambda shell: rc)

    rivet._bootstrap_shell_command()

    text = rc.read_text()
    assert str(rivet.ROOT_PATH / "bin" / "rivet") in text
    assert "/old/bin/rivet" not in text
    assert text.count("rivet begin") == 1
    assert "exec zsh" in capsys.readouterr().out


def test_bootstrap_repairs_incomplete_block(tmp_path, monkeypatch, capsys):
    rc = tmp_path / ".zshrc"
    rc.write_text(
        "export FOO=1\n"
        "# >>> rivet begin >>>\n"
        'rivet() { /old/bin/rivet "$@"; }\n'
    )
    monkeypatch.setattr(shell_rc, "login_shell", lambda: "zsh")
    monkeypatch.setattr(shell_rc, "rc_path", lambda shell: rc)

    rivet._bootstrap_shell_command()

    text = rc.read_text()
    assert "export FOO=1" in text
    assert str(rivet.ROOT_PATH / "bin" / "rivet") in text
    assert text.count("rivet begin") == 1
    assert "rivet end" in text
    assert "repaired" in capsys.readouterr().out


def test_unbootstrap_removes_block_from_any_shell(tmp_path, monkeypatch, capsys):
    zsh_rc = tmp_path / ".zshrc"
    zsh_rc.write_text(shell_rc.bootstrap_block(Path("/kit/bin/rivet"), "zsh"))
    monkeypatch.setattr(shell_rc, "login_shell", lambda: "bash")
    monkeypatch.setattr(
        shell_rc, "rc_path", lambda shell: zsh_rc if shell == "zsh" else None
    )
    rivet._unbootstrap_shell_command()
    assert "rivet" not in zsh_rc.read_text()
    assert "Removed shell command" in capsys.readouterr().out


def test_bootstrap_runs_even_with_force(tmp_path, monkeypatch):
    # Install always registers the short command, regardless of --force.
    calls = []
    monkeypatch.setattr(rivet.operations, "sync", lambda *a, **k: {})
    monkeypatch.setattr(rivet.project, "init_project", lambda *a, **k: None)
    monkeypatch.setattr(rivet, "_bootstrap_shell_command", lambda: calls.append(1))
    rivet._run_init(
        manifest.load(MANIFEST_PATH), tmp_path, tmp_path, force=True,
        skip_project=False, dry_run=False,
    )
    assert calls == [1]


# --------------------------------------------------------- atomic writes
def _forbid_write_text(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Path.write_text is not crash-safe")

    monkeypatch.setattr(Path, "write_text", forbidden)


def test_project_writes_are_atomic(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    first = tmp_path / "first.md"
    first.write_text("one\n")
    second = tmp_path / "second.md"
    second.write_text("two\n")
    plugin = tmp_path / "plugin.ts"
    plugin.write_text("plugin\n")

    _forbid_write_text(monkeypatch)

    project._prepend_instruction(root, first)
    project._prepend_instruction(root, second)
    project._install_plugin(root, plugin)
    project.uninstall_project(root, plugin)


def test_operations_writes_are_atomic(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "content").mkdir(parents=True)
    (root / "content" / "block.md").write_text(
        "<!-- begin -->\nblock\n<!-- end -->\n"
    )
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    artifact = {
        "name": "block",
        "operation": "text-insert",
        "src": "content/block.md",
        "target": "AGENTS.md",
        "mode": "append",
        "anchor": "<!-- begin -->",
        "end_anchor": "<!-- end -->",
    }

    _forbid_write_text(monkeypatch)

    assert operations.text_insert(root, cfg, artifact) == "installed"
    assert operations._text_remove(root, cfg, artifact) is True
    assert operations.config_merge(
        root,
        cfg,
        {"config_file": "opencode.json", "config_path": "a.b", "value": '"x"'},
    ) == "installed"


def test_shell_rc_writes_are_atomic(tmp_path, monkeypatch):
    rc = tmp_path / ".zshrc"
    rc.write_text("# user\n")
    block = shell_rc.bootstrap_block(Path("/bin/rivet"), "zsh")

    _forbid_write_text(monkeypatch)

    assert shell_rc.ensure_block(rc, block) == "installed"
    newer = shell_rc.bootstrap_block(Path("/opt/rivet"), "zsh")
    assert shell_rc.ensure_block(rc, newer) == "updated"
    rc.write_bytes(
        rc.read_text().replace(shell_rc.MARKER_END + "\n", "").encode()
    )
    assert shell_rc.ensure_block(rc, newer) == "repaired"
    assert shell_rc.remove_block(rc) is True
    assert shell_rc.ensure_block(rc, newer) == "installed"


def test_manifest_writes_are_atomic(tmp_path, monkeypatch):
    path = tmp_path / "manifest.toml"
    path.write_text('[[artifacts]]\nname = "x"\nsource_sha = ""\n')

    _forbid_write_text(monkeypatch)

    manifest.set_sha(path, "x", "abc")
    assert 'source_sha = "abc"' in path.read_text()


# ------------------------------------------------------------- tree merges
def test_copy_tree_rejects_upstream_symlink(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n")
    (upstream / "link.md").symlink_to(outside)
    local = tmp_path / "local"

    with pytest.raises(RuntimeError, match="symlink"):
        merge._copy_tree(upstream, local)
    assert not (local / "link.md").exists()


def test_merge_tree_rejects_upstream_symlink(tmp_path):
    base = tmp_path / "base"
    theirs = tmp_path / "theirs"
    local = tmp_path / "local"
    for directory in (base, theirs, local):
        directory.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n")
    (theirs / "link.md").symlink_to(outside)

    with pytest.raises(RuntimeError, match="symlink"):
        merge._merge_tree(local, base, theirs)


def test_merge_tree_removes_files_deleted_upstream(tmp_path):
    base = tmp_path / "base"
    theirs = tmp_path / "theirs"
    local = tmp_path / "local"
    for directory in (base, theirs, local):
        directory.mkdir()
    for directory in (base, local):
        (directory / "gone.md").write_text("same\n")
    for directory in (base, theirs, local):
        (directory / "keep.md").write_text("same\n")
    (base / "custom.md").write_text("base\n")
    (local / "custom.md").write_text("mine\n")

    conflict = merge._merge_tree(local, base, theirs)

    assert conflict is False
    assert not (local / "gone.md").exists()
    assert (local / "keep.md").read_text() == "same\n"
    assert (local / "custom.md").read_text() == "mine\n"


def test_merge_tree_preserves_mode_of_new_files(tmp_path):
    base = tmp_path / "base"
    theirs = tmp_path / "theirs"
    local = tmp_path / "local"
    for directory in (base, theirs, local):
        directory.mkdir()
    script = theirs / "script.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)

    assert merge._merge_tree(local, base, theirs) is False
    assert (local / "script.sh").read_text() == "#!/bin/sh\n"
    assert (local / "script.sh").stat().st_mode == script.stat().st_mode


