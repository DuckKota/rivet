"""
Operations for Rivet: symlink, text-insert, and config-merge.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonc
import output
import state


def _substituted_content(root: Path, entry: dict, config_dir: Path) -> str:
    """
    Render the substituted copy content for a `replace` symlink entry.

    Args:
        root: The repository root containing the source file.
        entry: The symlink entry declaring `src` and `replace`.
        config_dir: The OpenCode config directory (resolves `{config_dir}`).

    Returns:
        The source file content with each placeholder replaced.
    """
    content = (root / entry["src"]).read_text(encoding="utf-8")
    for placeholder, value in entry.get("replace", {}).items():
        content = content.replace(
            placeholder, value.replace("{config_dir}", str(config_dir))
        )
    return content


def _backup_target(config_dir: Path, target: Path) -> None:
    """Back up a user path before --force replaces it."""
    destination = state.backup(
        target,
        config_dir / state.BACKUP_DIR,
        target.relative_to(config_dir),
    )
    if destination:
        output.warning(f"backed up {target} to {destination}")


def symlink(
    root: Path,
    config_dir: Path,
    artifact: dict,
    force: bool = False,
) -> list[str]:
    """
    Symlink managed file or directory artifacts into the config directory.

    Args:
        root: The repository root containing the managed files.
        config_dir: The OpenCode config directory to link into.
        artifact: The manifest artifact describing the symlink.
        force: Overwrite an existing conflicting file or symlink.

    Returns:
        One status per entry: "installed", "ready", or "skipped".
    """
    statuses: list[str] = []
    entries = artifact.get("entries") or [
        {"src": artifact["src"], "target": artifact["target"]}
    ]
    for entry in entries:
        source_path = (root / entry["src"]).resolve()
        target_path = config_dir / entry["target"]

        # Create the destination's parent directories (e.g. commands/) if absent.
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # An entry with a `replace` table is written as a substituted copy (a
        # symlink cannot be edited in place). A leftover symlink from an older
        # install is unlinked first, since a plain write would follow it and
        # clobber the repo source; a conflicting real file honours --force.
        replace = entry.get("replace")
        if replace:
            desired = _substituted_content(root, entry, config_dir)
            if target_path.is_symlink():
                if target_path.resolve() == source_path or force:
                    target_path.unlink()
                else:
                    output.attention(
                        "Conflict",
                        f"{target_path} differs from managed (use --force)",
                    )
                    statuses.append("skipped")
                    continue
            elif target_path.exists():
                if target_path.is_file():
                    current = target_path.read_text(encoding="utf-8")
                    if current == desired:
                        # Idempotent: our copy is already in place.
                        state.record_file(config_dir, entry["target"], desired)
                        output.debug(f"already current: {target_path}")
                        statuses.append("ready")
                        continue
                    if state.is_recorded(config_dir, entry["target"], current):
                        # Our copy drifted with the source, not with a user
                        # edit; refresh it without --force.
                        jsonc.write_atomic(str(target_path), desired)
                        state.record_file(config_dir, entry["target"], desired)
                        output.debug(f"refreshed {target_path}")
                        statuses.append("installed")
                        continue
                if not force:
                    output.attention(
                        "Conflict", f"{target_path} exists (use --force)"
                    )
                    statuses.append("skipped")
                    continue
                _backup_target(config_dir, target_path)
                if target_path.is_dir():
                    shutil.rmtree(target_path)
            jsonc.write_atomic(str(target_path), desired)
            state.record_file(config_dir, entry["target"], desired)
            output.debug(f"installed {target_path}")
            statuses.append("installed")
            continue

        if target_path.is_symlink():
            # Already a symlink: skip if it points where we want (idempotent);
            # otherwise only replace it when the user passed --force.
            if target_path.resolve() == source_path:
                output.debug(f"already linked: {target_path}")
                statuses.append("ready")
                continue
            if force:
                target_path.unlink()
            else:
                output.attention(
                    "Conflict", f"{target_path} differs from managed (use --force)"
                )
                statuses.append("skipped")
                continue
        elif target_path.exists():
            # A real file (not a symlink) is in the way — only displace it
            # with --force, after copying it aside, and remove directories
            # recursively.
            if force:
                _backup_target(config_dir, target_path)
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
            else:
                output.attention("Conflict", f"{target_path} exists (use --force)")
                statuses.append("skipped")
                continue

        target_path.symlink_to(source_path)
        output.debug(f"linked {target_path}")
        statuses.append("installed")

    return statuses


def _text_end_marker(artifact: dict, content: str) -> str:
    """Return the artifact's end marker, falling back to its last comment."""
    marker = artifact.get("end_anchor")
    if marker:
        return marker
    return next(
        (
            line.strip()
            for line in reversed(content.splitlines())
            if line.strip().startswith("<!--")
        ),
        artifact["anchor"],
    )


def text_block_state(root: Path, config_dir: Path, artifact: dict) -> str:
    """
    Return "missing", "incomplete", "ready", or "outdated" for a text block.

    Args:
        root: The repository root containing the source text.
        config_dir: The OpenCode config directory containing the target.
        artifact: The manifest artifact describing the insertion.

    Returns:
        The state of the installed block.
    """
    content = (root / artifact["src"]).read_text(encoding="utf-8").strip()
    target_path = config_dir / artifact["target"]
    if not target_path.exists():
        return "missing"
    existing = target_path.read_text(encoding="utf-8")
    start_marker = artifact["anchor"]
    end_marker = _text_end_marker(artifact, content)
    start = existing.find(start_marker)
    end = (
        existing.find(end_marker, start + len(start_marker))
        if start != -1
        else existing.find(end_marker)
    )
    if start == -1 and end == -1:
        return "missing"
    if start == -1 or end == -1:
        return "incomplete"
    block = existing[start : end + len(end_marker)]
    return "ready" if block.strip() == content else "outdated"


def text_insert(
    root: Path,
    config_dir: Path,
    artifact: dict,
) -> str:
    """
    Insert or refresh a text block in a target file.

    Args:
        root: The repository root containing the source text.
        config_dir: The OpenCode config directory containing the target.
        artifact: The manifest artifact describing the insertion.

    Returns:
        "installed" when the block was written, "ready" when already current,
        or "skipped" when the markers are incomplete.
    """
    content = (root / artifact["src"]).read_text(encoding="utf-8").strip()
    target_path = config_dir / artifact["target"]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    )
    start_marker = artifact["anchor"]
    end_marker = _text_end_marker(artifact, content)
    start = existing.find(start_marker)
    end = (
        existing.find(end_marker, start + len(start_marker))
        if start != -1
        else existing.find(end_marker)
    )

    if start != -1 and end != -1:
        end += len(end_marker)
        if existing[start:end].strip() == content:
            output.debug(f"already present: {target_path}")
            return "ready"
        destination = state.backup(
            target_path,
            config_dir / state.BACKUP_DIR,
            target_path.relative_to(config_dir),
        )
        if destination:
            output.warning(f"backed up {target_path} to {destination}")
        new_content = existing[:start] + content + existing[end:]
        jsonc.write_atomic(str(target_path), new_content)
        output.debug(f"refreshed text block in {target_path}")
        return "installed"

    if start != -1 or end != -1:
        output.attention(
            "Conflict",
            f"{target_path} has an incomplete Rivet block; fix the markers",
        )
        return "skipped"

    if artifact.get("mode", "append") == "prepend":
        new_content = content + "\n\n" + existing
    else:
        new_content = existing.rstrip() + "\n\n" + content + "\n"

    jsonc.write_atomic(str(target_path), new_content)
    output.debug(f"inserted text block into {target_path}")
    return "installed"


def _text_remove(
    root: Path,
    config_dir: Path,
    artifact: dict,
) -> bool:
    """
    Remove a previously inserted text block from its target file.

    Removes the whole marker-delimited region: from the block's start anchor
    to its closing comment. Locating by markers rather than by matching the
    current source byte-for-byte means a block whose interior drifted — e.g.
    because the source instructions were edited after install — is still torn
    down. A hand-edited interior is removed too: it sits inside the tool's own
    begin/end markers, which mark that region as tool-managed.

    Args:
        root: The repository root containing the source text.
        config_dir: The OpenCode config directory containing the target.
        artifact: The manifest artifact describing the insertion.

    Returns:
        True when the target file changed.
    """
    content = (root / artifact["src"]).read_text(encoding="utf-8").strip()
    target_path = config_dir / artifact["target"]
    if not target_path.exists():
        return False
    existing = target_path.read_text(encoding="utf-8")
    start_marker = artifact["anchor"]
    start = existing.find(start_marker)
    if start == -1:
        return False  # never inserted
    end_marker = _text_end_marker(artifact, content)
    end = existing.find(end_marker, start + len(start_marker))
    if end == -1:
        return False  # no closing marker; leave it rather than mangle the file
    end += len(end_marker)
    new_content = (existing[:start] + existing[end:]).strip("\n") + "\n"
    if new_content == existing:
        return False
    destination = state.backup(
        target_path,
        config_dir / state.BACKUP_DIR,
        target_path.relative_to(config_dir),
    )
    if destination:
        output.warning(f"backed up {target_path} to {destination}")
    jsonc.write_atomic(str(target_path), new_content)
    return True


def config_merge_text(
    artifact: dict,
    current_text: str,
    mcp_bin: str = "",
) -> str:
    """
    Return the config text with the artifact's entry merged in.

    Args:
        artifact: The manifest artifact describing the merge.
        current_text: The existing file content ("" when absent).
        mcp_bin: The codebase-memory-mcp binary path to substitute.

    Returns:
        The merged text. Equal to current_text when the entry is current.

    Raises:
        ValueError: If the existing config is unparseable or not an object.
    """
    # Substitute the resolved mcp binary path before parsing the value.
    raw_value = artifact["value"].replace("<MCP_BIN>", mcp_bin)
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        # Value isn't JSON — store it as a raw string instead.
        value = raw_value

    data: dict = {}
    if current_text.strip():
        try:
            data = json.loads(current_text)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"refusing to merge into unparseable config: {error}"
            ) from error
        if not isinstance(data, dict):
            raise ValueError("refusing to merge into non-object config")

    # Walk the dotted config_path (e.g. "mcp.servers.foo"), creating any
    # intermediate dicts, then set the final leaf key to the value.
    node = data
    for key in artifact["config_path"].split(".")[:-1]:
        existing = node.setdefault(key, {})
        if not isinstance(existing, dict):
            raise ValueError(f"config key {key!r} is not a table")
        node = existing
    leaf = artifact["config_path"].split(".")[-1]
    if leaf in node:
        # A default must not replace a value the user already chose.
        if artifact.get("only_if_absent"):
            return current_text
        # Idempotent only when the key is actually present with the target
        # value. `node.get(leaf) == value` would also return True for an
        # absent key when value is JSON null, skipping the write.
        if node[leaf] == value:
            return current_text
    node[leaf] = value
    return json.dumps(data, indent=2) + "\n"


def config_merge(
    _root: Path,
    config_dir: Path,
    artifact: dict,
    mcp_bin: str = "",
) -> str:
    """
    Merge a JSON config entry into a target config file.

    Args:
        config_dir: The OpenCode config directory containing the target.
        artifact: The manifest artifact describing the merge.
        mcp_bin: The codebase-memory-mcp binary path to substitute.

    Returns:
        "installed" when the file was written, "ready" when already merged.
    """
    target_path = config_dir / artifact["config_file"]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    current = target_path.read_text(encoding="utf-8") if target_path.exists() else ""

    try:
        merged = config_merge_text(artifact, current, mcp_bin)
    except ValueError as error:
        raise ValueError(f"{error} ({target_path}); fix or remove it first") from error

    if merged == current:
        output.debug(f"already merged: {target_path}")
        return "ready"
    jsonc.write_atomic(str(target_path), merged)
    output.debug(f"merged {target_path}")
    return "installed"


_GROUP_LABELS = {
    "command": "Commands",
    "skill": "Skills",
    "theme": "Themes",
    "plugin": "Plugins",
    "instruction": "Instructions",
}
_GROUP_ORDER = (
    "Commands",
    "Skills",
    "Themes",
    "Plugins",
    "Instructions",
    "Configuration",
)
_CONFIG_GROUP = "Configuration"


def _artifact_group(artifact: dict) -> str:
    """Return the user-facing summary group for an artifact."""
    if artifact["operation"] == "config-merge":
        return _CONFIG_GROUP
    kind = artifact.get("type", "other")
    return _GROUP_LABELS.get(kind, kind.replace("-", " ").title())


def _print_summary(order: list[str], groups: dict[str, dict[str, int]]) -> None:
    """Print one compact line per component group."""
    for label in order:
        counts = groups[label]
        total = counts["installed"] + counts["ready"] + counts["skipped"]
        if total == 0:
            continue
        if counts["skipped"]:
            ready = counts["installed"] + counts["ready"]
            skipped = counts["skipped"]
            output.attention(label, f"{ready} ready, {skipped} skipped")
        elif label == _CONFIG_GROUP and counts["installed"] == total:
            output.success(label, "updated")
        elif counts["installed"] == total:
            output.success(label, f"{total} installed")
        else:
            output.success(label, f"{total} ready")


def install(
    manifest: dict,
    root: Path,
    config_dir: Path,
    force: bool = False,
) -> dict[str, dict[str, int]]:
    """
    Bring the managed config farm up, idempotently.

    Args:
        manifest: The parsed manifest dictionary.
        root: The repository root.
        config_dir: The OpenCode config directory.
        force: Overwrite conflicting files.

    Returns:
        Per-group counts of installed, ready, and skipped artifacts.
    """
    mcp_bin = shutil.which("codebase-memory-mcp") or "codebase-memory-mcp"
    config_dir.mkdir(parents=True, exist_ok=True)
    order: list[str] = []
    groups: dict[str, dict[str, int]] = {}

    for artifact in manifest["artifacts"]:
        operation = artifact["operation"]
        if operation == "symlink":
            statuses = symlink(root, config_dir, artifact, force)
        elif operation == "text-insert":
            statuses = [text_insert(root, config_dir, artifact)]
        elif operation == "config-merge":
            statuses = [config_merge(root, config_dir, artifact, mcp_bin)]
        else:  # pragma: no cover
            raise ValueError(f"unknown operation {operation}")

        label = _artifact_group(artifact)
        if label not in groups:
            groups[label] = {"installed": 0, "ready": 0, "skipped": 0}
            order.append(label)
        for status in statuses:
            groups[label][status] += 1

    order.sort(
        key=lambda label: _GROUP_ORDER.index(label)
        if label in _GROUP_ORDER
        else len(_GROUP_ORDER)
    )
    _print_summary(order, groups)
    return groups


def expected_symlink_targets(manifest: dict) -> set[str]:
    """
    Return the set of managed symlink targets declared in the manifest.

    Args:
        manifest: The parsed manifest dictionary.

    Returns:
        The set of relative symlink target paths.
    """
    targets: set[str] = set()

    for artifact in manifest["artifacts"]:
        if artifact["operation"] != "symlink":
            continue
        entries = artifact.get("entries") or [{"target": artifact["target"]}]
        for entry in entries:
            targets.add(entry["target"])

    return targets


def managed_symlinks(
    config_dir: Path,
    root: Path,
):
    """
    Yield managed symlinks under config_dir that point into root/content.

    Args:
        config_dir: The OpenCode config directory to scan.
        root: The repository root.

    Yields:
        Tuples of (symlink_path, relative_target).
    """
    content_root = (root / "content").resolve()
    for path in config_dir.rglob("*"):
        if path.is_symlink():
            relative = path.relative_to(config_dir)
            # Backup copies are user data, not installed links.
            if relative.parts and relative.parts[0] == state.BACKUP_DIR:
                continue
            try:
                resolved = path.resolve()
            except OSError:
                continue
            # Only treat symlinks that point into this repo's content/ as
            # managed; user-created links elsewhere are left alone.
            if resolved.is_relative_to(content_root):
                yield path, str(relative)


def sync(
    manifest: dict,
    root: Path,
    config_dir: Path,
    force: bool = False,
    prune: bool = True,
) -> dict[str, dict[str, int]]:
    """
    Install and remove stale managed symlinks.

    Args:
        manifest: The parsed manifest dictionary.
        root: The repository root.
        config_dir: The OpenCode config directory.
        force: Overwrite conflicting files.
        prune: Remove stale managed symlinks (default True).

    Returns:
        Per-group counts of installed, ready, and skipped artifacts.
    """
    groups = install(manifest, root, config_dir, force)

    if not prune:
        return groups

    # Prune: remove managed symlinks no longer declared in the manifest
    # (e.g. after an artifact was renamed or dropped). Replace-substituted
    # copies are NOT pruned here: once an artifact is dropped, its copy is
    # indistinguishable from a user file, so deleting it would be unsafe.
    # (uninstall() handles in-manifest teardown by content comparison.)
    expected = expected_symlink_targets(manifest)
    removed = 0
    for path, relative_target in list(managed_symlinks(config_dir, root)):
        if relative_target not in expected:
            output.debug(f"removing stale managed symlink: {path}")
            path.unlink()
            removed += 1
    if removed:
        noun = "link" if removed == 1 else "links"
        output.success("Cleanup", f"{removed} stale {noun} removed")
    return groups


def uninstall(
    manifest: dict,
    root: Path,
    config_dir: Path,
) -> int:
    """
    Tear down managed symlinks, substituted copies, and inserted text blocks,
    keeping user files.

    Args:
        manifest: The parsed manifest dictionary.
        root: The repository root.
        config_dir: The OpenCode config directory.

    Returns:
        The number of managed items removed.
    """
    removed = 0
    for path, _ in list(managed_symlinks(config_dir, root)):
        output.debug(f"removing managed symlink: {path}")
        path.unlink()
        removed += 1
    # Replace-substituted entries are written as copies, so the symlink scan
    # above misses them; remove them here for a complete teardown. Plain
    # symlink entries that were installed as copies by an earlier tool (rather
    # than as symlinks) are also real files, so they need the same handling.
    # Only a file that still matches exactly the content the tool would write
    # is removed — a user's own file at the same path is kept.
    for artifact in manifest["artifacts"]:
        if artifact["operation"] != "symlink":
            continue
        entries = artifact.get("entries") or [
            {"src": artifact["src"], "target": artifact["target"]}
        ]
        for entry in entries:
            relative = entry["target"]
            target = config_dir / relative
            if target.is_symlink() or target.is_dir() or not target.exists():
                continue
            content = target.read_text(encoding="utf-8")
            # Remove a file that matches what the tool would write today, or
            # whose hash Rivet recorded at install time. A user's own file at
            # the same path has neither property and is kept.
            if content == _substituted_content(root, entry, config_dir) or (
                state.is_recorded(config_dir, relative, content)
            ):
                output.debug(f"removing managed file: {target}")
                target.unlink()
                state.forget_file(config_dir, relative)
                removed += 1
    # text-insert artifacts inject a block into a target file (e.g. AGENTS.md);
    # tear them down too, keeping any user-edited block in place.
    for artifact in manifest["artifacts"]:
        if artifact["operation"] == "text-insert":
            target = config_dir / artifact["target"]
            if target.exists() and text_block_state(
                root, config_dir, artifact
            ) != "missing":
                if _text_remove(root, config_dir, artifact):
                    output.debug(f"removing managed text block: {target}")
                    removed += 1
    state.clear(config_dir)

    if removed:
        items = output.plural(removed, "managed item")
        output.success("Core", f"{items} removed")
    else:
        output.skip("Core", "nothing to remove")
    return removed
