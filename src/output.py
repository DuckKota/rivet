"""Terminal presentation helpers for Rivet.

Normal output reports user-meaningful progress. Per-file details go through
debug() and only appear with --verbose. Color is opt-out (NO_COLOR) and is
disabled when stdout is not a terminal, so piped and test output stays plain.
"""
from __future__ import annotations

import os
import sys
from typing import TextIO

LABEL_WIDTH = 24

_VERBOSE = False


def set_verbose(enabled: bool) -> None:
    """Enable or disable per-file debug output."""
    global _VERBOSE  # pylint: disable=global-statement
    _VERBOSE = enabled


def _color_enabled(stream: TextIO | None = None) -> bool:
    """Return True when color is safe: TTY, NO_COLOR unset, TERM not dumb."""
    stream = stream or sys.stdout
    return (
        "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
        and stream.isatty()
    )


def _paint(text: str, code: str) -> str:
    """Wrap text in an ANSI color when color is enabled."""
    if not _color_enabled():
        return text
    return f"\033[{code}m{text}\033[0m"


def component(symbol: str, label: str, detail: str = "", color: str = "") -> None:
    """Print one aligned status line: symbol, label, optional detail."""
    pad = max(1, LABEL_WIDTH - len(label))
    padding = " " * pad
    painted = _paint(symbol, color) if color else symbol
    if detail:
        print(f"  {painted} {label}{padding}{detail}")
    else:
        print(f"  {painted} {label}")


def success(label: str, detail: str = "") -> None:
    """Report a completed component."""
    component("✓", label, detail, "32")


def skip(label: str, detail: str = "") -> None:
    """Report an expected skip or optional component."""
    component("○", label, detail, "2")


def attention(label: str, detail: str = "") -> None:
    """Report something that needs the user's attention."""
    component("!", label, detail, "33")


def failure(label: str, detail: str = "") -> None:
    """Report a failed check."""
    component("✗", label, detail, "31")


def warning(text: str) -> None:
    """Print a free-form warning line."""
    marker = _paint("!", "33")
    print(f"  {marker} {text}")


def info(text: str) -> None:
    """Print a plain informational line."""
    print(f"  {text}")


def plural(count: int, noun: str) -> str:
    """Return a count with the noun in singular or plural form."""
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def banner(title: str, detail: str = "") -> None:
    """Print the product banner at the top of a command."""
    line = _paint(title, "1")
    if detail:
        detail_text = _paint(detail, "2")
        line += f"  {detail_text}"
    print(line)


def heading(text: str) -> None:
    """Start a named section of output."""
    print()
    painted = _paint(text, "1")
    print(f"  {painted}")


def debug(text: str) -> None:
    """Print a per-file detail line only in verbose mode."""
    if _VERBOSE:
        print(f"    {text}")
