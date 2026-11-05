"""Resolve the OpenCode global configuration directory."""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

# Only OpenCode is supported. The manifest keeps an `agents` field so the
# schema can grow later; this is the only valid value today.
AGENTS = ("opencode",)

OPENCODE_FALLBACK = Path.home() / ".config" / "opencode"


def _probe(
    binary: str,
    args: list[str],
    parse: Callable[[str], str],
    fallback: Path,
) -> Path:
    """
    Run a binary's config-path command and return the resolved path.

    Returns fallback when the binary is missing, the command fails, or the
    parser yields nothing usable.

    Args:
        binary: The executable name to look up on PATH.
        args: The command arguments that print the config path.
        parse: Extracts the path string from the command's stdout.
        fallback: The default path when probing fails.

    Returns:
        The resolved config directory path.
    """
    if not shutil.which(binary):
        return fallback
    try:
        result = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Binary missing or failed — fall through to the default.
        return fallback
    path = parse(result.stdout) if result.returncode == 0 else ""
    return Path(path).expanduser() if path else fallback


def _parse_opencode_path(stdout: str) -> str:
    """
    Extract the config path from `opencode debug paths` output.

    The command prints lines like "config <path>"; return the path from the
    line whose label is `config`.

    Args:
        stdout: The command's stdout.

    Returns:
        The config path, or "" if not found.
    """
    for line in stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "config" and len(parts) > 1:
            return parts[1]
    return ""


def opencode_config_dir(manifest: dict) -> Path:
    """
    Resolve the OpenCode config directory.

    Precedence:
        OC_CONFIG_DIR env var, then manifest config.default_config_dir,
        then `opencode debug paths`, then ~/.config/opencode.

    Args:
        manifest: The parsed manifest dictionary.

    Returns:
        The resolved config directory path.
    """
    env_dir = os.environ.get("OC_CONFIG_DIR")
    if env_dir:
        return Path(env_dir).expanduser()

    default_dir = manifest.get("config", {}).get("default_config_dir")
    if default_dir:
        return Path(default_dir).expanduser()

    return _probe("opencode", ["debug", "paths"], _parse_opencode_path, OPENCODE_FALLBACK)
