"""Status reporting for Rivet."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import jsonc
import output
import plan
import project
import shell_rc
import version

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"


@dataclass(frozen=True)
class Check:
    """One user-facing health check."""

    label: str
    state: str
    detail: str = ""
    fix: str = ""


def _opencode_config(config_dir: Path) -> Path | None:
    """Return the active OpenCode config file, preferring JSONC."""
    for name in ("opencode.jsonc", "opencode.json"):
        path = config_dir / name
        if path.exists():
            return path
    return None


def _plugin_entries(config_dir: Path) -> list[str]:
    """Return plugin package names from every OpenCode config."""
    entries: list[str] = []
    # TUI plugins live in cli.json; server plugins live in opencode.json(c).
    for name in ("opencode.jsonc", "opencode.json", "cli.json"):
        path = config_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(jsonc.strip_jsonc(jsonc.read_config(str(path))))
        except (jsonc.ConfigError, json.JSONDecodeError, ValueError):
            continue
        plugins = data.get("plugins", []) if isinstance(data, dict) else []
        for entry in plugins if isinstance(plugins, list) else []:
            if isinstance(entry, str):
                entries.append(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("package"), str):
                entries.append(entry["package"])
    return [entry.lower() for entry in entries]


def detect_integrations(config_dir: Path) -> dict[str, bool]:
    """Return which optional integrations are configured."""
    plugins = _plugin_entries(config_dir)

    def present(package: str) -> bool:
        return any(package in entry for entry in plugins)

    return {
        "Ponytail": present("@dietrichgebert/ponytail"),
        "Plannotator": present("@plannotator/opencode"),
        "HeadsUp": present("@banburist/opencode-headsup"),
        "Subagent Statusline": present("opencode-subagent-statusline-v2"),
        "Magic Context": present("magic-context"),
    }


def _artifact_targets(manifest: dict, kind: str) -> list[str]:
    """Return the config-dir targets for one artifact type."""
    targets: list[str] = []
    for artifact in manifest["artifacts"]:
        if artifact.get("type") != kind:
            continue
        if artifact["operation"] == "symlink":
            entries = artifact.get("entries") or [artifact]
            targets.extend(entry["target"] for entry in entries)
    return targets


def _installed_count(config_dir: Path, targets: list[str]) -> int:
    """Count targets that exist and, for symlinks, point at a real file."""
    count = 0
    for target in targets:
        path = config_dir / target
        if path.is_symlink():
            count += int(path.resolve().exists())
        else:
            count += int(path.exists())
    return count


def _core_checks(
    manifest: dict, repo_root: Path, config_dir: Path
) -> list[Check]:
    """Return one check per core component group."""
    changes = plan.config_changes(manifest, repo_root, config_dir)
    checks: list[Check] = []
    for label, kind, prefix in (
        ("Commands", "command", "commands/"),
        ("Skills", "skill", "skills/"),
        ("Themes", "theme", "themes/"),
    ):
        targets = _artifact_targets(manifest, kind)
        installed = _installed_count(config_dir, targets)
        affected = [change for change in changes if change.path.startswith(prefix)]
        if installed == 0:
            checks.append(Check(label, SKIP, "not installed"))
        elif affected:
            checks.append(
                Check(label, WARN, f"{len(affected)} need attention", "run `rivet init`")
            )
        elif installed == len(targets):
            checks.append(Check(label, OK, f"{installed} ready"))
        else:
            checks.append(
                Check(
                    label,
                    WARN,
                    f"{installed}/{len(targets)} installed",
                    "run `rivet init`",
                )
            )

    agents_file = config_dir / "AGENTS.md"
    anchors = [
        artifact["anchor"]
        for artifact in manifest["artifacts"]
        if artifact["operation"] == "text-insert"
    ]
    instructions = agents_file.exists() and all(
        anchor in agents_file.read_text(encoding="utf-8") for anchor in anchors
    )
    instruction_changes = [c for c in changes if c.path == "AGENTS.md"]
    if not agents_file.exists():
        checks.append(Check("Instructions", SKIP, "not installed"))
    elif instruction_changes or not instructions:
        checks.append(
            Check("Instructions", WARN, "needs attention", "run `rivet init`")
        )
    else:
        checks.append(Check("Instructions", OK, "ready"))

    config_name = "cli.json"
    config_changes = [c for c in changes if c.path == config_name]
    if not (config_dir / config_name).exists():
        checks.append(Check("Configuration", SKIP, "not installed"))
    elif config_changes:
        checks.append(
            Check("Configuration", WARN, "needs attention", "run `rivet init`")
        )
    else:
        checks.append(Check("Configuration", OK, "ready"))
    return checks


def _project_checks(cwd: Path) -> tuple[list[Check], Path | None]:
    """Return project-level checks and the detected root."""
    root = project.git_root(cwd)
    if root is None:
        return [Check("Git repository", SKIP, "not a Git repository")], None

    checks = [Check("Git repository", OK, root.name)]
    initialized = (
        project.openspec_present(root)
        or project.instruction_present(root)
        or project.codebase_present(root)
    )
    checks.append(
        Check(
            "Rivet initialized",
            OK if initialized else SKIP,
            "ready" if initialized else "not initialized",
        )
    )
    return checks, root


def _project_tool_checks(
    root: Path | None, repo_root: Path
) -> list[Check]:
    """Return OpenSpec and Codebase Memory checks for a project."""
    if root is None:
        return []
    checks = [
        Check(
            "OpenSpec",
            OK if project.openspec_present(root) else SKIP,
            "ready" if project.openspec_present(root) else "not initialized",
        )
    ]
    instruction_source = (
        repo_root / "content" / "instructions" / "codebase-memory-mcp-agents.md"
    )
    if project.codebase_present(root, instruction_source):
        checks.append(Check("Codebase Memory", OK, "ready"))
    elif (
        project.instruction_present(root)
        or project.plugin_path(root).exists()
        or project.mcp_entry_present(root)
    ):
        checks.append(Check("Codebase Memory", WARN, "partial", "run `rivet init`"))
    else:
        checks.append(Check("Codebase Memory", SKIP, "not initialized"))
    return checks


def _integration_checks(config_dir: Path) -> list[Check]:
    """Check required integrations and report optional ones."""
    required = {"Ponytail", "Plannotator", "HeadsUp", "Subagent Statusline"}
    checks: list[Check] = []
    for name, installed in detect_integrations(config_dir).items():
        if installed:
            checks.append(Check(name, OK, "installed"))
        elif name in required:
            checks.append(
                Check(name, WARN, "not installed", "re-run the Rivet installer")
            )
        else:
            checks.append(Check(name, SKIP, "not installed (optional)"))
    return checks


def _opencode_check() -> Check:
    """Check that OpenCode is installed and supports V2."""
    binary = shutil.which("opencode")
    if not binary:
        return Check(
            "OpenCode",
            FAIL,
            "not found",
            "install OpenCode V2: https://opencode.ai/docs/",
        )
    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return Check("OpenCode", FAIL, "could not run", "run `opencode --version`")
    raw_version = result.stdout.strip()
    if result.returncode != 0 or not raw_version:
        return Check("OpenCode", FAIL, "could not read version", "run `opencode --version`")
    number = next(
        (
            part.lstrip("vV")
            for part in raw_version.split()
            if part.lstrip("vV")[:1].isdigit()
        ),
        "0",
    )
    major = int(number.split(".")[0])
    if major < 2:
        return Check("OpenCode", FAIL, raw_version, "upgrade: opencode upgrade")
    return Check("OpenCode", OK, raw_version.replace("opencode ", ""))


def _environment_checks(repo_root: Path) -> list[Check]:
    """Return environment checks for `rivet status`."""
    system = platform.system()
    if system in ("Darwin", "Linux"):
        detail = "WSL" if "microsoft" in platform.release().lower() else ""
        os_check = Check("Operating system", OK, detail or system)
    else:
        os_check = Check(
            "Operating system", FAIL, system, "use macOS, Linux, or WSL"
        )

    git = shutil.which("git")
    python_ok = sys.version_info >= (3, 9)
    shell = shell_rc.login_shell()
    if shell is None:
        shell_command = Check("Shell command", SKIP, "unsupported shell")
    else:
        rc = shell_rc.rc_path(shell)
        block = shell_rc.bootstrap_block(repo_root / "bin" / "rivet", shell)
        state = shell_rc.block_state(rc, block) if rc is not None else "missing"
        if state == "ready":
            shell_command = Check("Shell command", OK, "registered")
        elif state == "outdated":
            shell_command = Check(
                "Shell command", WARN, "outdated path", "run `rivet init`"
            )
        elif state == "incomplete":
            shell_command = Check(
                "Shell command", WARN, "incomplete block", "run `rivet init`"
            )
        else:
            shell_command = Check(
                "Shell command", WARN, "not registered", "run `rivet init`"
            )
    return [
        os_check,
        Check("Git", OK if git else FAIL, "" if git else "not found", "install Git"),
        Check(
            "Python",
            OK if python_ok else FAIL,
            platform.python_version(),
            "install Python 3.9+",
        ),
        _opencode_check(),
        Check(
            "Shell",
            OK if shell else WARN,
            shell or "unsupported",
            "register the command manually in your shell config",
        ),
        shell_command,
    ]


def _config_valid(config_dir: Path) -> Check:
    """Check that the OpenCode config is readable JSON/JSONC."""
    path = _opencode_config(config_dir)
    if path is None:
        return Check("OpenCode config", SKIP, "not found")
    try:
        data = json.loads(jsonc.strip_jsonc(jsonc.read_config(str(path))))
    except (jsonc.ConfigError, json.JSONDecodeError, ValueError) as error:
        return Check("OpenCode config", FAIL, str(error), f"fix {path}")
    if not isinstance(data, dict):
        return Check("OpenCode config", FAIL, "root is not an object", f"fix {path}")
    return Check("OpenCode config", OK, path.name)


def _writable_check(label: str, path: Path) -> Check:
    """Check that a path (or its nearest existing parent) is writable."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if os.access(probe, os.W_OK):
        return Check(label, OK, str(path))
    return Check(label, FAIL, f"{path} is not writable", "fix the directory permissions")


def _promote_skips(checks: list[Check], fix: str) -> list[Check]:
    """Turn optional skips into warnings for status output."""
    return [
        Check(check.label, WARN, check.detail, fix) if check.state == SKIP else check
        for check in checks
    ]


def _render_checks(checks: list[Check], show_fix: bool = False) -> None:
    """Print a group of checks."""
    for check in checks:
        if check.state == OK:
            output.success(check.label, check.detail)
        elif check.state == WARN:
            output.attention(check.label, check.detail)
        elif check.state == FAIL:
            output.failure(check.label, check.detail)
        else:
            output.skip(check.label, check.detail)
        if show_fix and check.fix and check.state in (WARN, FAIL):
            output.info(f"    fix: {check.fix}")


def print_status(
    manifest: dict, repo_root: Path, config_dir: Path, cwd: Path
) -> int:
    """
    Print the current installation state and any pending changes.

    Returns:
        1 when any check failed, 0 otherwise.
    """
    environment = _environment_checks(repo_root)
    project_checks, root = _project_checks(cwd)
    if root is not None:
        project_checks = _promote_skips(project_checks, "run `rivet init`")
        project_checks += _promote_skips(
            _project_tool_checks(root, repo_root), "run `rivet init`"
        )
    project_checks.append(_config_valid(config_dir))
    project_checks.append(_writable_check("Config writable", config_dir))
    if root is not None:
        project_checks.append(_writable_check("Project writable", root))
    core = _core_checks(manifest, repo_root, config_dir)
    integrations = _integration_checks(config_dir)
    changes = plan.all_changes(manifest, repo_root, config_dir, cwd)

    output.banner("Rivet")
    output.heading("Project")
    _render_checks(project_checks, show_fix=True)
    output.heading("Environment")
    _render_checks(environment, show_fix=True)
    output.heading("Core")
    _render_checks(core, show_fix=True)
    output.heading("Integrations")
    _render_checks(integrations, show_fix=True)

    if changes:
        output.heading("Changes")
        plan.print_changes(changes, show_scopes=False)

    all_checks = environment + project_checks + core + integrations
    failures = sum(1 for check in all_checks if check.state == FAIL)
    warnings = sum(1 for check in all_checks if check.state == WARN)
    print()
    if failures:
        failure_count = output.plural(failures, "failure")
        warning_count = output.plural(warnings, "warning")
        output.info(f"{failure_count}, {warning_count}.")
        output.info("Fix the failures above, then run `rivet status` again.")
        code = 1
    elif warnings:
        issue_count = output.plural(warnings, "issue")
        output.info(f"{issue_count} found.")
        output.info("Run `rivet init` to repair the project.")
        code = 0
    elif changes:
        change_count = output.plural(len(changes), "change")
        output.info(f"{change_count} pending.")
        output.info("Run `rivet init` to apply.")
        code = 0
    else:
        output.info("No issues found.")
        code = 0
    print()
    output.info(f"Rivet {version.VERSION}")
    return code
