"""
Track Rivet-owned files and back up user files before destructive replaces.

The state file lives in the OpenCode config directory so it moves with the
config it describes. It records the hash of each substituted copy Rivet wrote;
uninstall removes a copy only when its hash still matches. Files that do not
match are user-owned and are left alone.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import jsonc

STATE_FILE = ".rivet-state.json"
BACKUP_DIR = ".rivet-backups"


def _path(config_dir: Path) -> Path:
    """Return the state file path for a config directory."""
    return config_dir / STATE_FILE


def load(config_dir: Path) -> dict:
    """Return the recorded state, or an empty state when it is absent/invalid."""
    path = _path(config_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "files": {}}
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {"version": 1, "files": {}}
    return {"version": 1, "files": data["files"]}


def save(config_dir: Path, data: dict) -> None:
    """Write the state file atomically."""
    config_dir.mkdir(parents=True, exist_ok=True)
    jsonc.write_atomic(
        str(_path(config_dir)),
        json.dumps(data, indent=2) + "\n",
        prefix=".rivet-state.",
    )


def _hash(content: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def record_file(config_dir: Path, relative: str, content: str) -> None:
    """Record the hash of a file Rivet wrote."""
    data = load(config_dir)
    data["files"][relative] = _hash(content)
    save(config_dir, data)


def is_recorded(config_dir: Path, relative: str, content: str) -> bool:
    """Return True when content matches the hash Rivet recorded for a path."""
    return load(config_dir)["files"].get(relative) == _hash(content)


def forget_file(config_dir: Path, relative: str) -> None:
    """Drop one file record, removing the state file when it becomes empty."""
    data = load(config_dir)
    if data["files"].pop(relative, None) is None:
        return
    if data["files"]:
        save(config_dir, data)
    else:
        clear(config_dir)


def clear(config_dir: Path) -> None:
    """Remove the state file."""
    try:
        _path(config_dir).unlink()
    except FileNotFoundError:
        pass


def backup(target: Path, backup_root: Path, relative: Path) -> Path | None:
    """
    Copy a user file or directory aside before Rivet replaces it.

    Args:
        target: The existing path that is about to be replaced.
        backup_root: The directory that holds backup runs.
        relative: Path to use inside the backup run.

    Returns:
        The backup path, or None when the target is absent or a symlink.
    """
    if not target.exists() or target.is_symlink():
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="backup-", dir=backup_root))
    destination = run_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(target, destination, symlinks=True)
    else:
        shutil.copy2(target, destination)
    return destination
