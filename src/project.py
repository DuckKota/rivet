"""
Per-project tool initialization: OpenSpec and codebase-memory-mcp.

Run inside a git working tree (any depth — the repo root is resolved via
`git rev-parse --show-toplevel`, so subdirectories behave the same as the
root). Every step is idempotent: safe to re-run as often as `rivet init`
is. Both tools are per-project; nothing here touches the global config.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import jsonc
import output
import state

# Markers around the codebase-memory AGENTS.md instruction block; used to keep
# the prepend idempotent and to remove exactly the tool-owned region.
INSTRUCTION_MARKER = "<!-- codebase-memory-mcp:start -->"
INSTRUCTION_END = "<!-- codebase-memory-mcp:end -->"

PLUGIN_NAME = "CodebaseMemoryReminder.ts"

OPENSPEC_INSTALL = "sudo npm install -g @fission-ai/openspec@latest"
CBM_INSTALL = (
    "curl -fsSL "
    "https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.sh "
    "| bash -s -- --skip-config"
)

# Bounded wait for a binary install (`npm install -g` or `curl | bash`). A
# hung network fetch would otherwise block `rivet init` indefinitely.
INSTALL_TIMEOUT = 300

# Bounded wait for project setup commands that talk to a local service or db.
COMMAND_TIMEOUT = 60

# A full graph index can legitimately take minutes; still bound it.
INDEX_TIMEOUT = 600


def git_root(cwd: Path) -> Path | None:
    """
    Return the git repository root containing cwd, or None if cwd is not
    inside a repository.

    Args:
        cwd: The working directory to resolve.

    Returns:
        The resolved repo root path, or None.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    return Path(result.stdout.strip()).resolve()


def _run_checked(
    command: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess:
    """
    Run a command quietly, replaying its output only when it fails.

    Args:
        command: The argv to run.
        cwd: Working directory for the command.

    Returns:
        The completed process.

    Raises:
        subprocess.CalledProcessError: When the command exits non-zero or
            exceeds COMMAND_TIMEOUT.
    """
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        command_text = " ".join(command)
        output.warning(f"`{command_text}` timed out after {COMMAND_TIMEOUT}s")
        raise subprocess.CalledProcessError(-1, command, "", "") from None
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise subprocess.CalledProcessError(
            result.returncode, command, result.stdout, result.stderr
        )
    output.debug(" ".join(command))
    return result


def _ensure_tool(
    name: str,
    bin_name: str,
    install_cmd: str,
    confirm: Callable[[str], bool],
) -> str | None:
    """
    Return the binary path for a tool, installing it (with a prompt) if
    missing.

    Args:
        name: Display name of the tool.
        bin_name: Executable name on PATH.
        install_cmd: Shell command that installs the tool.
        confirm: Prompt callback returning True to proceed.

    Returns:
        The resolved binary path, or None if unavailable.
    """
    path = shutil.which(bin_name)
    if path:
        return path

    # Always ask explicitly — installing a binary is a system-level change.
    # The exact command is shown so the user knows what will run.
    if not confirm(
        f"{name} is not installed.\n"
        f"Install it with:\n  {install_cmd}\n"
        f"Install now?"
    ):
        output.skip(name, "not installed")
        return None

    # The command may pipe (e.g. `curl | bash`), so run it through a shell.
    # Inherit stdio so sudo's password prompt and live progress stay visible.
    try:
        result = subprocess.run(
            install_cmd,
            shell=True,
            check=False,
            timeout=INSTALL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        output.warning(f"Installing {name} timed out after {INSTALL_TIMEOUT}s.")
        output.info("Install it manually, then re-run `rivet init`.")
        return None
    if result.returncode != 0:
        output.warning(f"Could not install {name} (exit {result.returncode}).")
        output.info("Install it manually, then re-run `rivet init`.")
        return None

    path = shutil.which(bin_name)
    if not path:
        output.warning(
            f"{name} installed but not on PATH. Refresh your shell, then re-run `rivet init`."
        )
        return None

    return path


def _init_openspec(root: Path, openspec_bin: str) -> bool:
    """Initialize OpenSpec for OpenCode in the project (idempotent)."""
    try:
        _run_checked([openspec_bin, "init", "--tools", "opencode"], cwd=root)
    except subprocess.CalledProcessError:
        output.warning("OpenSpec init failed. Re-run `rivet init`.")
        return False
    output.debug("openspec initialized")
    return True


def _prepend_instruction(root: Path, src_instruction: Path) -> bool:
    """Insert or refresh the codebase-memory instructions in AGENTS.md."""
    target = root / "AGENTS.md"
    content = src_instruction.read_text(encoding="utf-8").strip()
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    start = existing.find(INSTRUCTION_MARKER)
    end = (
        existing.find(INSTRUCTION_END, start + len(INSTRUCTION_MARKER))
        if start != -1
        else existing.find(INSTRUCTION_END)
    )

    if start != -1 and end != -1:
        end += len(INSTRUCTION_END)
        if existing[start:end].strip() == content:
            return False
        destination = state.backup(
            target,
            root / ".opencode" / state.BACKUP_DIR,
            Path("AGENTS.md"),
        )
        if destination:
            output.warning(f"backed up {target} to {destination}")
        jsonc.write_atomic(
            str(target), existing[:start] + content + existing[end:]
        )
        output.debug(f"refreshed codebase-memory instructions in {target}")
        return True

    if start != -1 or end != -1:
        output.attention(
            "Conflict",
            f"{target} has an incomplete codebase-memory block; fix the markers",
        )
        return False

    jsonc.write_atomic(str(target), content + "\n\n" + existing)
    output.debug(f"added codebase-memory instructions to {target}")
    return True


def _install_plugin(root: Path, src_plugin: Path) -> None:
    """Copy the codebase-memory reminder plugin into the project.

    The installed file keeps the canonical name CodebaseMemoryReminder.ts so
    OpenCode sees one clean plugin file and re-installs overwrite the same path.
    """
    dest_dir = root / ".opencode" / "plugins"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "CodebaseMemoryReminder.ts"
    jsonc.write_atomic(str(dest), src_plugin.read_text(encoding="utf-8"))
    output.debug(f"installed {dest}")


PROJECT_CONFIG_NAMES = ("opencode.jsonc", "opencode.json")


def project_config_path(root: Path) -> Path:
    """Return the project OpenCode config, preferring an existing JSONC file."""
    directory = root / ".opencode"
    for name in PROJECT_CONFIG_NAMES:
        path = directory / name
        if path.exists():
            return path
    return directory / "opencode.json"


def _read_jsonc(path: Path) -> dict:
    """Return the parsed JSONC at path, or {} when absent or empty."""
    if not path.exists():
        return {}
    text = jsonc.read_config(str(path)).strip()
    return json.loads(jsonc.strip_jsonc(text)) if text else {}


def _managed_legacy_entry(entry) -> bool:
    """Return True for the exact V1 payload this tool wrote."""
    return (
        isinstance(entry, dict)
        and set(entry) == {"enabled", "type", "command"}
        and entry.get("enabled") is True
        and entry.get("type") == "local"
        and isinstance(entry.get("command"), list)
        and len(entry["command"]) == 1
        and isinstance(entry["command"][0], str)
    )


def _managed_mcp_entry(entry) -> bool:
    """Return True for the exact V2 entry this tool writes."""
    return (
        isinstance(entry, dict)
        and set(entry) == {"type", "command"}
        and entry.get("type") == "local"
        and isinstance(entry.get("command"), list)
        and len(entry["command"]) == 1
        and isinstance(entry["command"][0], str)
        and Path(entry["command"][0]).name == "codebase-memory-mcp"
    )


def _merge_mcp_config(root: Path, mcp_bin: str) -> None:
    """Register or refresh the codebase-memory-mcp project entry."""
    path = project_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_jsonc(path)

    mcp = data.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        output.attention("Conflict", f"{path}: mcp is not an object")
        return
    servers = mcp.setdefault("servers", {})
    if not isinstance(servers, dict):
        output.attention("Conflict", f"{path}: mcp.servers is not an object")
        return

    if "codebase-memory-mcp" in servers:
        entry = servers["codebase-memory-mcp"]
        if not _managed_mcp_entry(entry):
            return
        if entry["command"] != [mcp_bin]:
            entry["command"] = [mcp_bin]
            jsonc.write_atomic(str(path), json.dumps(data, indent=2) + "\n")
            output.debug(f"refreshed {path}")
        return

    legacy = mcp.get("codebase-memory-mcp")
    if legacy is not None:
        # Upgrade only the exact V1 payload this tool wrote; anything else is
        # user-owned and stays as-is (V2 still reads the legacy shape).
        if not _managed_legacy_entry(legacy):
            return
        del mcp["codebase-memory-mcp"]

    servers["codebase-memory-mcp"] = {"type": "local", "command": [mcp_bin]}
    jsonc.write_atomic(str(path), json.dumps(data, indent=2) + "\n")
    output.debug(f"merged {path}")


def _set_runtime_flags(root: Path, mcp_bin: str) -> bool:
    """Enable the repo-level codebase-memory runtime flags (idempotent)."""
    # Runtime settings are a plain key write in a local sqlite db — idempotent.
    # cwd=root so subdirectory installs target the same project db as the
    # rest of the per-project setup.
    ok = True
    for key in ("auto_index", "auto_watch"):
        try:
            _run_checked([mcp_bin, "config", "set", key, "true"], cwd=root)
        except subprocess.CalledProcessError:
            output.warning(f"Could not enable {key}. Re-run `rivet init`.")
            ok = False
    return ok


def _initial_index(root: Path, mcp_bin: str) -> bool:
    """Index the repo graph on first init (idempotent, best-effort).

    Returns:
        True when the graph is indexed (already or now), False on failure.
    """
    # Skip when the project is already indexed, keeping re-runs a no-op.
    if is_indexed(root, mcp_bin):
        output.debug("codebase-memory graph already indexed")
        return True

    output.info("Indexing codebase-memory graph (full mode)...")
    try:
        result = subprocess.run(
            [mcp_bin, "cli", "index_repository", "--repo-path", str(root), "--mode", "full"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=INDEX_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        output.warning(f"Codebase Memory indexing timed out after {INDEX_TIMEOUT}s.")
        output.info("Re-run `rivet init` to retry.")
        return False
    if result.returncode == 0:
        output.debug("codebase-memory graph indexed")
        return True
    output.warning("Codebase Memory initial index failed. The graph may be empty.")
    output.info("Re-run `rivet init` to retry.")
    return False


def _init_codebase(
    root: Path,
    mcp_bin: str,
    src_instruction: Path,
    src_plugin: Path,
) -> None:
    """Run the per-project codebase-memory-mcp setup for opencode (idempotent)."""
    _prepend_instruction(root, src_instruction)
    _install_plugin(root, src_plugin)
    _merge_mcp_config(root, mcp_bin)
    _set_runtime_flags(root, mcp_bin)
    output.debug("codebase-memory-mcp initialized")


def instruction_present(root: Path) -> bool:
    """Return True when the AGENTS.md codebase-memory block is installed."""
    target = root / "AGENTS.md"
    return target.exists() and INSTRUCTION_MARKER in target.read_text(encoding="utf-8")


def instruction_removable(root: Path) -> bool:
    """Return True when both markers of the AGENTS.md block are present."""
    target = root / "AGENTS.md"
    if not target.exists():
        return False
    text = target.read_text(encoding="utf-8")
    start = text.find(INSTRUCTION_MARKER)
    return start != -1 and (
        text.find(INSTRUCTION_END, start + len(INSTRUCTION_MARKER)) != -1
    )


def instruction_current(root: Path, src_instruction: Path) -> bool:
    """Return True when the installed AGENTS.md block matches the source."""
    target = root / "AGENTS.md"
    if not target.exists():
        return False
    existing = target.read_text(encoding="utf-8")
    start = existing.find(INSTRUCTION_MARKER)
    end = (
        existing.find(INSTRUCTION_END, start + len(INSTRUCTION_MARKER))
        if start != -1
        else -1
    )
    if start == -1 or end == -1:
        return False
    block = existing[start : end + len(INSTRUCTION_END)]
    return block.strip() == src_instruction.read_text(encoding="utf-8").strip()


def plugin_path(root: Path) -> Path:
    """Return the installed reminder plugin path."""
    return root / ".opencode" / "plugins" / PLUGIN_NAME


def openspec_present(root: Path) -> bool:
    """Return True when OpenSpec has been initialized in the project."""
    return (root / "openspec").is_dir()


def _mcp_entry(root: Path):
    """Return the project's codebase-memory MCP entry, or None."""
    path = project_config_path(root)
    if not path.exists():
        return None
    data = _read_jsonc(path)
    mcp = data.get("mcp", {})
    if not isinstance(mcp, dict):
        return None
    servers = mcp.get("servers", {})
    if isinstance(servers, dict) and "codebase-memory-mcp" in servers:
        return servers["codebase-memory-mcp"]
    return mcp.get("codebase-memory-mcp")


def mcp_entry_present(root: Path) -> bool:
    """Return True when the project declares the codebase-memory MCP server."""
    return _mcp_entry(root) is not None


def mcp_entry_managed(root: Path) -> bool:
    """Return True when the MCP entry has the exact shape Rivet writes."""
    entry = _mcp_entry(root)
    return _managed_mcp_entry(entry) or _managed_legacy_entry(entry)


def codebase_present(root: Path, src_instruction: Path | None = None) -> bool:
    """Return True when the project's codebase-memory wiring is complete."""
    instruction_ok = (
        instruction_current(root, src_instruction)
        if src_instruction is not None
        else instruction_present(root)
    )
    return instruction_ok and plugin_path(root).exists() and mcp_entry_present(root)


def project_name(root: Path) -> str:
    """Return the codebase-memory project name for a repository root."""
    return str(root.resolve()).lstrip("/").replace("/", "-")


def is_indexed(root: Path, mcp_bin: str) -> bool:
    """Return True when the project's codebase-memory graph is indexed."""
    try:
        result = subprocess.run(
            [mcp_bin, "cli", "index_status", "--project", project_name(root)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def remove_instruction(root: Path) -> bool:
    """Remove the tool-owned codebase-memory block from AGENTS.md."""
    target = root / "AGENTS.md"
    if not target.exists():
        return False
    text = target.read_text(encoding="utf-8")
    start = text.find(INSTRUCTION_MARKER)
    end = text.find(INSTRUCTION_END, start + len(INSTRUCTION_MARKER))
    if start == -1 or end == -1:
        return False
    end += len(INSTRUCTION_END)
    new = (text[:start] + text[end:]).lstrip("\n")
    jsonc.write_atomic(str(target), new)
    return True


def uninstall_project(root: Path, src_plugin: Path) -> list[str]:
    """
    Remove project-level Rivet wiring, preserving anything the user changed.

    OpenSpec files and the repo-level codebase-memory runtime flags are left
    alone: they may contain user content and cannot be safely attributed.

    Args:
        root: The project root.
        src_plugin: The source reminder plugin to compare against.

    Returns:
        One human-readable result line per action or preserved file.
    """
    results: list[str] = []

    if remove_instruction(root):
        results.append("removed AGENTS.md codebase-memory block")

    plugin = plugin_path(root)
    if plugin.exists():
        if plugin.read_text(encoding="utf-8") == src_plugin.read_text(encoding="utf-8"):
            plugin.unlink()
            results.append(f"removed {plugin.relative_to(root)}")
        else:
            results.append(f"kept {plugin.relative_to(root)} (modified)")

    config_path = project_config_path(root)
    if config_path.exists():
        data = _read_jsonc(config_path)
        changed = False
        mcp = data.get("mcp", {})
        servers = mcp.get("servers", {}) if isinstance(mcp, dict) else {}
        entry = servers.get("codebase-memory-mcp") if isinstance(servers, dict) else None
        if _managed_mcp_entry(entry):
            del servers["codebase-memory-mcp"]
            changed = True
        legacy = mcp.get("codebase-memory-mcp") if isinstance(mcp, dict) else None
        if _managed_legacy_entry(legacy):
            del mcp["codebase-memory-mcp"]
            changed = True
        if changed:
            jsonc.write_atomic(
                str(config_path), json.dumps(data, indent=2) + "\n"
            )
            results.append(
                f"removed codebase-memory-mcp from {config_path.relative_to(root)}"
            )
        else:
            results.append(
                f"kept {config_path.relative_to(root)} (no Rivet-owned entry)"
            )

    return results


def init_project(
    cwd: Path,
    confirm: Callable[[str], bool],
    src_instruction: Path,
    src_plugin: Path,
) -> None:
    """
    Initialize OpenSpec and codebase-memory-mcp for the project containing cwd.

    Runs only when cwd is inside a git repository; both tools' setup is
    idempotent, so it is safe to run on every init.

    Args:
        cwd: The working directory (per-project root is resolved from it).
        confirm: Prompt callback for installing missing tools.
        src_instruction: Path to the codebase-memory-mcp agents instructions.
        src_plugin: Path to the OpenCode CodebaseMemoryReminder plugin.
    """
    root = git_root(cwd)
    if root is None:
        output.skip("Project tools", "not in a Git repository")
        return

    output.debug("initializing per-project tools")

    openspec_bin = _ensure_tool("OpenSpec", "openspec", OPENSPEC_INSTALL, confirm)
    if openspec_bin and _init_openspec(root, openspec_bin):
        output.success("OpenSpec")

    mcp_bin = _ensure_tool(
        "codebase-memory-mcp", "codebase-memory-mcp", CBM_INSTALL, confirm
    )
    if not mcp_bin:
        return

    _init_codebase(root, mcp_bin, src_instruction, src_plugin)

    if _initial_index(root, mcp_bin):
        output.success("Codebase Memory")
    else:
        output.attention("Codebase Memory", "index failed. Re-run `rivet init`.")
