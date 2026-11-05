#!/usr/bin/env python3
"""Disable OpenCode's default sidebar plugins in the TUI config."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from jsonc import ConfigError, read_config, strip_jsonc, write_atomic

DISABLED = ("-opencode.sidebar.context", "-opencode.sidebar.footer")


def update_config(path: str) -> int:
    """Return 0 when changed, 2 when already disabled."""
    if not Path(path).exists():
        config = {
            "$schema": "https://opencode.ai/v2/cli.json",
            "plugins": list(DISABLED),
        }
        write_atomic(path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        return 0

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

    plugins = config.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise ConfigError(f"{path}: plugins is not an array")

    changed = False
    for package in DISABLED:
        if package not in plugins:
            plugins.append(package)
            changed = True
    if not changed:
        return 2

    write_atomic(path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    return 0


def main(argv: list[str]) -> int:
    """Run the command-line entry point."""
    if len(argv) != 2:
        raise ConfigError("usage: disabled_plugins.py PATH")
    return update_config(argv[1])


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
