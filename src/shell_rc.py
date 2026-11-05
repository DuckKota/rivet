"""
Shell rc bootstrap: register a `rivet` shell function in the user's rc file so
the CLI is reachable from any directory.

The function embeds the absolute path to this repo's `bin/rivet`. A marker
block makes the bootstrap idempotent (no double-append) and lets `uninstall`
remove exactly what `install` added.
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

import jsonc

COMMAND_NAME = "rivet"

MARKER_START = f"# >>> {COMMAND_NAME} begin >>>"
MARKER_END = f"# <<< {COMMAND_NAME} end <<<"

# Login-shell basename -> rc file. Paths are relative to $HOME.
RC_FILES = {
    "zsh": "~/.zshrc",
    "bash": "~/.bashrc",
    "fish": "~/.config/fish/config.fish",
}


def login_shell() -> str | None:
    """Return the basename of the login shell, or None when unset/unsupported."""
    name = Path(os.environ.get("SHELL", "")).name
    return name if name in RC_FILES else None


def rc_path(shell: str | None) -> Path | None:
    """Resolve the rc file for a shell basename, or None for unknown."""
    if shell == "fish":
        config_home = os.environ.get("XDG_CONFIG_HOME")
        base = Path(config_home) if config_home else Path.home() / ".config"
        return base / "fish" / "config.fish"
    rel = RC_FILES.get(shell or "")
    return Path(rel).expanduser() if rel else None


def _fish_quote(value: str) -> str:
    """Quote a value for fish's single-quoted string syntax."""
    if (
        value
        and not value.startswith("-")
        and all(char.isalnum() or char in "_@%+=:,./-" for char in value)
    ):
        return value
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def bootstrap_block(script_path: Path, shell: str) -> str:
    """Return the marker-delimited block registering the command for `shell`."""
    path = str(script_path)
    if shell == "fish":
        body = f"function {COMMAND_NAME}\n    {_fish_quote(path)} $argv\nend"
    else:
        body = f'{COMMAND_NAME}() {{ {shlex.quote(path)} "$@"; }}'
    return f"{MARKER_START}\n{body}\n{MARKER_END}\n"


def block_present(rc_file: Path) -> bool:
    """Return True when either marker already exists in the rc file."""
    if not rc_file.exists():
        return False
    text = rc_file.read_text()
    return MARKER_START in text or MARKER_END in text


def block_state(rc_file: Path, block: str) -> str:
    """
    Return "missing", "incomplete", "ready", or "outdated" for the block.

    Args:
        rc_file: The shell rc file to inspect.
        block: The block Rivet wants to install.

    Returns:
        The state of the marker block.
    """
    if not rc_file.exists():
        return "missing"
    text = rc_file.read_text()
    start = text.find(MARKER_START)
    end = (
        text.find(MARKER_END, start + len(MARKER_START))
        if start != -1
        else text.find(MARKER_END)
    )
    if start == -1 and end == -1:
        return "missing"
    if start == -1 or end == -1:
        return "incomplete"
    current = text[start : end + len(MARKER_END)]
    return "ready" if current.strip() == block.strip() else "outdated"


def ensure_block(rc_file: Path, block: str) -> str:
    """
    Install, refresh, or repair the marker block.

    Args:
        rc_file: The shell rc file to update.
        block: The block Rivet wants to install.

    Returns:
        "installed", "updated", "repaired", or "ready".
    """
    status = block_state(rc_file, block)
    if status == "ready":
        return "ready"
    if not rc_file.exists():
        rc_file.parent.mkdir(parents=True, exist_ok=True)
        jsonc.write_atomic(str(rc_file), block)
        return "installed"
    text = rc_file.read_text()
    if status == "outdated":
        start = text.find(MARKER_START)
        end = text.find(MARKER_END, start + len(MARKER_START))
        if start != -1 and end != -1:
            end += len(MARKER_END)
            jsonc.write_atomic(
                str(rc_file), text[:start] + block.rstrip("\n") + text[end:]
            )
            return "updated"
        # block_state said outdated, so both markers should exist after the
        # start; treat a malformed file as incomplete rather than corrupt it.
        status = "incomplete"
    if status == "incomplete":
        # Keep every user line; drop the orphan marker and append a complete
        # block so the newest function definition wins.
        lines = [
            line
            for line in text.splitlines()
            if line.strip() not in (MARKER_START, MARKER_END)
        ]
        cleaned = "\n".join(lines).rstrip()
        jsonc.write_atomic(str(rc_file), (cleaned + "\n\n" if cleaned else "") + block)
        return "repaired"
    return "installed" if add_block(rc_file, block) else "ready"


def add_block(rc_file: Path, block: str) -> bool:
    """Append the block idempotently. Returns True if appended, False if already present."""
    if block_present(rc_file):
        return False
    if rc_file.exists():
        content = rc_file.read_text()
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n" + block
    else:
        content = block
    rc_file.parent.mkdir(parents=True, exist_ok=True)
    jsonc.write_atomic(str(rc_file), content)
    return True


def _remove_marker_block(rc_file: Path, start_marker: str, end_marker: str) -> bool:
    """Remove one marker-delimited block. Returns True if removed."""
    if not rc_file.exists():
        return False
    text = rc_file.read_text()
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker)) if start != -1 else -1
    if start == -1 or end == -1:
        return False
    end += len(end_marker)
    # swallow the trailing newline after the end marker, if present
    if end < len(text) and text[end] == "\n":
        end += 1
    new = text[:start] + text[end:]
    # collapse any double blank line left at the removal boundary
    while "\n\n\n" in new:
        new = new.replace("\n\n\n", "\n\n")
    jsonc.write_atomic(str(rc_file), new)
    return True


def remove_block(rc_file: Path) -> bool:
    """Remove the Rivet marker block. Returns True if removed, False if absent."""
    return _remove_marker_block(rc_file, MARKER_START, MARKER_END)
