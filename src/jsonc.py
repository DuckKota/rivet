"""JSONC scanning and editing helpers shared by Rivet and the installer."""
from __future__ import annotations

import os
import shutil
import tempfile


class ConfigError(Exception):
    """A user-facing configuration error."""


def read_config(path: str) -> str:
    """Read a UTF-8 config file and drop a leading byte-order mark."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from None

    if text.startswith("\ufeff"):
        text = text[1:]

    return text


def write_atomic(path: str, content: str, prefix: str = ".opencode.") -> None:
    """Write through symlinks, atomically, preserving the target's mode."""
    target = os.path.realpath(path)
    directory = os.path.dirname(target) or "."

    def remove_temporary(temporary_path: str) -> None:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass

    try:
        descriptor, temporary_path = tempfile.mkstemp(prefix=prefix, dir=directory)
    except OSError as error:
        raise ConfigError(f"cannot write {target}: {error}") from None

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        if os.path.exists(target):
            shutil.copymode(target, temporary_path)
        else:
            # Match open()'s default for a new file instead of mkstemp's 0600.
            mask = os.umask(0)
            os.umask(mask)
            os.chmod(temporary_path, 0o666 & ~mask)
        os.replace(temporary_path, target)
    except OSError as error:
        remove_temporary(temporary_path)
        raise ConfigError(f"cannot write {target}: {error}") from None
    except BaseException:
        remove_temporary(temporary_path)
        raise


def strip_jsonc(source: str) -> str:
    """Drop comments and trailing commas outside strings."""
    without_comments = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        char = source[index]
        if in_string:
            without_comments.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            without_comments.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(source) and source[index + 1] == "/":
            while index < len(source) and source[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < len(source) and source[index + 1] == "*":
            index += 2
            while index + 1 < len(source) and not (
                source[index] == "*" and source[index + 1] == "/"
            ):
                index += 1
            index += 2
            continue
        without_comments.append(char)
        index += 1

    without_trailing_commas = []
    index = 0
    in_string = False
    escaped = False
    while index < len(without_comments):
        char = without_comments[index]
        if in_string:
            without_trailing_commas.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            without_trailing_commas.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while (
                lookahead < len(without_comments)
                and without_comments[lookahead].isspace()
            ):
                lookahead += 1
            if (
                lookahead < len(without_comments)
                and without_comments[lookahead] in "}]"
            ):
                index += 1
                continue
        without_trailing_commas.append(char)
        index += 1
    return "".join(without_trailing_commas)
