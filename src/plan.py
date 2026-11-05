"""Read-only comparison between the repository and a Rivet installation."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import operations
import output
import project
import shell_rc
import state

CORE = "core"
PROJECT = "project"


@dataclass(frozen=True)
class Change:
    """One meaningful difference between desired and current state."""

    kind: str
    scope: str
    path: str
    detail: str = ""


def print_changes(changes: list[Change], show_scopes: bool = True) -> None:
    """
    Print a diff-style list of changes, grouped by scope.

    Args:
        changes: The changes to print.
        show_scopes: Print Core/Project headings. Disable when the caller
            already groups its output by scope.
    """
    if not changes:
        output.success("Rivet", "up to date")
        return

    # Collapse large groups (themes, skills, ...) into one line so a clean
    # install does not dump 80 near-identical paths.
    groups: dict[tuple[str, str, str], list[Change]] = {}
    order: list[tuple[str, str, str]] = []
    for change in changes:
        top = change.path.split("/", 1)[0]
        key = (change.kind, change.scope, top)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(change)

    for scope, title in ((CORE, "Core"), (PROJECT, "Project")):
        scoped = [key for key in order if key[1] == scope]
        if not scoped:
            continue
        if show_scopes:
            output.heading(title)
        for key in scoped:
            kind, _, top = key
            items = groups[key]
            if len(items) > 5:
                print(f"  {kind.upper():<7}{top}/  {len(items)} items")
                continue
            for change in items:
                detail = f"  {change.detail}" if change.detail else ""
                print(f"  {kind.upper():<7}{change.path}{detail}")


def _relative(path: Path, base: Path) -> str:
    """Return path relative to base, falling back to the absolute path."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _dedupe(changes: list[Change]) -> list[Change]:
    """Drop duplicate kind/path pairs while preserving order."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[Change] = []
    for change in changes:
        key = (change.kind, change.scope, change.path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(change)
    return unique


def _symlink_changes(
    artifact: dict,
    repo_root: Path,
    config_dir: Path,
) -> list[Change]:
    """Compare one symlink artifact's entries with the config directory."""
    changes: list[Change] = []
    entries = artifact.get("entries") or [
        {"src": artifact["src"], "target": artifact["target"]}
    ]
    for entry in entries:
        source = (repo_root / entry["src"]).resolve()
        target = config_dir / entry["target"]
        path = _relative(target, config_dir)

        if entry.get("replace"):
            # pylint: disable-next=protected-access
            desired = operations._substituted_content(repo_root, entry, config_dir)
            if target.is_symlink():
                changes.append(Change("update", CORE, path, "replace link with managed copy"))
            elif target.exists():
                if target.is_file() and target.read_text(encoding="utf-8") == desired:
                    continue
                if target.is_file() and state.is_recorded(
                    config_dir, entry["target"], target.read_text(encoding="utf-8")
                ):
                    changes.append(Change("update", CORE, path, "refresh managed copy"))
                else:
                    changes.append(Change("update", CORE, path, "overwrite modified file"))
            else:
                changes.append(Change("add", CORE, path))
            continue

        if target.is_symlink():
            if target.resolve() == source and source.exists():
                continue
            changes.append(Change("update", CORE, path, "replace symlink"))
        elif target.exists():
            changes.append(Change("update", CORE, path, "replace conflicting file"))
        else:
            changes.append(Change("add", CORE, path))

    return changes


def _text_insert_changes(
    artifact: dict, repo_root: Path, config_dir: Path
) -> list[Change]:
    """Compare one text-insert artifact with its target file."""
    target = config_dir / artifact["target"]
    path = _relative(target, config_dir)
    block_state = operations.text_block_state(repo_root, config_dir, artifact)
    if block_state == "ready":
        return []
    kind = "update" if target.exists() else "add"
    detail = "add Rivet instructions"
    if block_state == "outdated":
        detail = "refresh Rivet instructions"
    elif block_state == "incomplete":
        detail = "fix incomplete Rivet instructions"
    return [Change(kind, CORE, path, detail)]


def _config_merge_changes(artifact: dict, config_dir: Path, mcp_bin: str) -> list[Change]:
    """Compare one config-merge artifact with its target file."""
    target = config_dir / artifact["config_file"]
    path = _relative(target, config_dir)
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    try:
        merged = operations.config_merge_text(artifact, current, mcp_bin)
    except ValueError:
        return [Change("update", CORE, path, "fix invalid config")]
    if merged == current:
        return []
    config_path = artifact["config_path"]
    kind = "update" if target.exists() else "add"
    return [Change(kind, CORE, path, f"set {config_path}")]


def config_changes(
    manifest: dict,
    repo_root: Path,
    config_dir: Path,
) -> list[Change]:
    """
    Return the changes needed to bring the OpenCode config up to date.

    Args:
        manifest: The parsed manifest dictionary.
        repo_root: The Rivet checkout root.
        config_dir: The OpenCode config directory.

    Returns:
        The ordered list of core changes.
    """
    changes: list[Change] = []
    mcp_bin = shutil.which("codebase-memory-mcp") or "codebase-memory-mcp"

    for artifact in manifest["artifacts"]:
        operation = artifact["operation"]
        if operation == "symlink":
            changes.extend(_symlink_changes(artifact, repo_root, config_dir))
        elif operation == "text-insert":
            changes.extend(_text_insert_changes(artifact, repo_root, config_dir))
        elif operation == "config-merge":
            changes.extend(_config_merge_changes(artifact, config_dir, mcp_bin))

    expected = operations.expected_symlink_targets(manifest)
    for _, relative in operations.managed_symlinks(config_dir, repo_root):
        if relative not in expected:
            changes.append(Change("remove", CORE, relative, "stale managed link"))

    return _dedupe(changes)


def project_changes(repo_root: Path, cwd: Path) -> list[Change]:
    """
    Return the changes needed to initialize the current project.

    Args:
        repo_root: The Rivet checkout root.
        cwd: The working directory used to find the project.

    Returns:
        The ordered list of project changes (empty outside a Git repository).
    """
    root = project.git_root(cwd)
    if root is None:
        return []

    changes: list[Change] = []
    if not project.openspec_present(root):
        changes.append(Change("add", PROJECT, "openspec/", "OpenSpec project"))

    instruction_source = (
        repo_root / "content" / "instructions" / "codebase-memory-mcp-agents.md"
    )
    if not project.instruction_current(root, instruction_source):
        kind = "update" if (root / "AGENTS.md").exists() else "add"
        changes.append(
            Change(kind, PROJECT, "AGENTS.md", "refresh codebase-memory instructions")
        )

    source = repo_root / "content" / "plugins" / "CodebaseMemoryReminder.ts"
    plugin = project.plugin_path(root)
    path = _relative(plugin, root)
    if not plugin.exists():
        changes.append(Change("add", PROJECT, path, "reminder plugin"))
    elif plugin.read_text(encoding="utf-8") != source.read_text(encoding="utf-8"):
        changes.append(Change("update", PROJECT, path, "refresh reminder plugin"))

    if not project.mcp_entry_present(root):
        config_path = project.project_config_path(root)
        kind = "update" if config_path.exists() else "add"
        changes.append(
            Change(kind, PROJECT, _relative(config_path, root), "register codebase-memory-mcp")
        )

    mcp_bin = shutil.which("codebase-memory-mcp")
    if mcp_bin and not project.is_indexed(root, mcp_bin):
        changes.append(
            Change("add", PROJECT, "codebase-memory graph", "index repository")
        )

    return _dedupe(changes)


def all_changes(
    manifest: dict,
    repo_root: Path,
    config_dir: Path,
    cwd: Path,
) -> list[Change]:
    """
    Return every core and project change for the current installation.

    Args:
        manifest: The parsed manifest dictionary.
        repo_root: The Rivet checkout root.
        config_dir: The OpenCode config directory.
        cwd: The working directory used to find the project.

    Returns:
        Core changes followed by project changes.
    """
    return config_changes(manifest, repo_root, config_dir) + project_changes(
        repo_root, cwd
    )


def _managed_copy(
    path: Path, relative: str, desired: str, config_dir: Path
) -> bool:
    """Return True when a real file is a Rivet-written copy."""
    if not path.is_file() or path.is_symlink():
        return False
    content = path.read_text(encoding="utf-8")
    return content == desired or state.is_recorded(config_dir, relative, content)


def uninstall_changes(
    manifest: dict,
    repo_root: Path,
    config_dir: Path,
    cwd: Path,
) -> list[Change]:
    """
    Return what `rivet uninstall` would remove, without changing anything.

    Args:
        manifest: The parsed manifest dictionary.
        repo_root: The Rivet checkout root.
        config_dir: The OpenCode config directory.
        cwd: The working directory used to find the project.

    Returns:
        The ordered list of removals and preserved user files.
    """
    changes: list[Change] = []
    for _, relative in operations.managed_symlinks(config_dir, repo_root):
        changes.append(Change("remove", CORE, relative, "managed link"))

    for artifact in manifest["artifacts"]:
        if artifact["operation"] == "symlink":
            entries = artifact.get("entries") or [
                {"src": artifact["src"], "target": artifact["target"]}
            ]
            for entry in entries:
                target = config_dir / entry["target"]
                # Directory artifacts are symlinks, already removed above.
                if not (repo_root / entry["src"]).is_file():
                    continue
                # pylint: disable-next=protected-access
                desired = operations._substituted_content(repo_root, entry, config_dir)
                if _managed_copy(target, entry["target"], desired, config_dir):
                    changes.append(
                        Change("remove", CORE, _relative(target, config_dir), "managed file")
                    )
        elif artifact["operation"] == "text-insert":
            target = config_dir / artifact["target"]
            # Only a block with both markers can be removed; an incomplete
            # block is left in place, so the plan must not promise removal.
            if target.exists() and operations.text_block_state(
                repo_root, config_dir, artifact
            ) in ("ready", "outdated"):
                changes.append(
                    Change(
                        "update",
                        CORE,
                        _relative(target, config_dir),
                        "remove Rivet instructions",
                    )
                )

    for shell in shell_rc.RC_FILES:
        rc = shell_rc.rc_path(shell)
        if rc is None or not rc.exists():
            continue
        block = shell_rc.bootstrap_block(repo_root / "bin" / "rivet", shell)
        if shell_rc.block_state(rc, block) in ("ready", "outdated"):
            changes.append(Change("update", CORE, str(rc), "remove shell command"))

    root = project.git_root(cwd)
    if root is not None:
        if project.openspec_present(root):
            changes.append(Change("keep", PROJECT, "openspec/", "project content"))
        if project.instruction_removable(root):
            changes.append(
                Change("update", PROJECT, "AGENTS.md", "remove codebase-memory block")
            )
        source = repo_root / "content" / "plugins" / "CodebaseMemoryReminder.ts"
        plugin = project.plugin_path(root)
        if plugin.exists():
            kind = (
                "remove"
                if plugin.read_text(encoding="utf-8")
                == source.read_text(encoding="utf-8")
                else "keep"
            )
            changes.append(Change(kind, PROJECT, _relative(plugin, root), "reminder plugin"))
        if project.mcp_entry_present(root):
            kind = "remove" if project.mcp_entry_managed(root) else "keep"
            changes.append(
                Change(
                    kind,
                    PROJECT,
                    _relative(project.project_config_path(root), root),
                    "codebase-memory-mcp entry",
                )
            )

    return _dedupe(changes)
