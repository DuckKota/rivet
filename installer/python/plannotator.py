#!/usr/bin/env python3
"""Put the Plannotator OpenCode plugin into manual workflow mode."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from jsonc import ConfigError, read_config, strip_jsonc, write_atomic

PACKAGE = os.environ.get("PLANNOTATOR_PACKAGE", "@plannotator/opencode@latest")
# The version is optional in the config, so match on the package name alone.
BASE_PACKAGE = PACKAGE.rpartition("@")[0] or PACKAGE


def _is_plannotator(package: object) -> bool:
    """Match the Plannotator package at any pinned version."""
    return isinstance(package, str) and (
        package == BASE_PACKAGE or package.startswith(BASE_PACKAGE + "@")
    )


def _manual_plugin_entry() -> dict:
    """Return the Plannotator entry configured for manual workflow."""
    return {"package": PACKAGE, "options": {"workflow": "manual"}}


def _set_manual(plugins: list) -> bool:
    """Set the Plannotator entry to manual. Return False when already manual."""
    for index, entry in enumerate(plugins):
        if isinstance(entry, str):
            if not _is_plannotator(entry):
                continue
            plugins[index] = {"package": entry, "options": {"workflow": "manual"}}
            return True
        if not isinstance(entry, dict) or not _is_plannotator(entry.get("package")):
            continue
        options = entry.get("options")
        if not isinstance(options, dict):
            options = {}
        if options.get("workflow") == "manual":
            return False
        options["workflow"] = "manual"
        entry["options"] = options
        return True
    plugins.append(_manual_plugin_entry())
    return True


def update_config(path: str) -> int:
    """Return 0 when changed, 2 when already manual."""
    config_text = read_config(path)
    json_text = strip_jsonc(config_text)
    if not json_text.strip():
        raise ConfigError(f"{path} is empty")

    try:
        config = json.loads(json_text)
    except json.JSONDecodeError as error:
        raise ConfigError(f"invalid OpenCode config {path}: {error}") from None

    if not isinstance(config, dict):
        raise ConfigError(f"{path} root is not an object")
    if not config:
        raise ConfigError(f"{path} is empty")

    # OpenCode writes only one config file when both exist. Create the array
    # here so the other file can carry the same plugin entry.
    plugins = config.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise ConfigError(f"{path}: plugins is not an array")

    if not _set_manual(plugins):
        return 2

    write_atomic(path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    return 0


def main(argv: list[str]) -> int:
    """Run the command-line entry point."""
    if len(argv) != 2:
        raise ConfigError("usage: plannotator.py PATH")
    return update_config(argv[1])


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
