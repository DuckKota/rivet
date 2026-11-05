#!/usr/bin/env python3
"""
Rivet: a development workflow for AI coding agents.

Subcommands:
    init:      Initialize or reconcile Rivet in the current project.
    status:    Show the current installation state and what needs attention.
    update:    Update Rivet and reconcile the current project.
    uninstall: Remove Rivet-managed configuration.
    vendor:    Re-vendor upstream artifacts (maintainers).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT_PATH / "manifest.toml"

# Import our own modules from the src/ directory
# pylint: disable=wrong-import-position
import config  # noqa: E402
import manifest  # noqa: E402
import merge  # noqa: E402
import operations  # noqa: E402
import output  # noqa: E402
import plan  # noqa: E402
import project  # noqa: E402
import shell_rc  # noqa: E402
import status  # noqa: E402
import version  # noqa: E402

SRC_INSTRUCTION_PATH = ROOT_PATH / "content" / "instructions" / "codebase-memory-mcp-agents.md"
SRC_PLUGIN_PATH = ROOT_PATH / "content" / "plugins" / "CodebaseMemoryReminder.ts"


def build_parser() -> argparse.ArgumentParser:
    """
    Build and return the command-line argument parser.

    Returns:
        A configured ArgumentParser covering every subcommand.
    """
    parser = argparse.ArgumentParser(
        prog="rivet",
        description="A development workflow for AI coding agents.",
        epilog="Run `rivet <command> --help` for details.",
    )
    parser.add_argument("--version", action="version", version=f"Rivet {version.VERSION}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    init_parser = subparsers.add_parser(
        "init", help="initialize or reconcile Rivet in the current project"
    )
    init_parser.add_argument(
        "--dry-run", action="store_true", help="show what would change without changing it"
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="back up and overwrite conflicting files, and remove stale links",
    )
    init_parser.add_argument(
        "--no-project", action="store_true", help="skip per-project tool initialization"
    )
    init_parser.add_argument(
        "--verbose",
        action="store_true",
        help="show every installed file and subprocess command",
    )

    subparsers.add_parser("status", help="show the current Rivet installation state")

    update_parser = subparsers.add_parser(
        "update", help="update Rivet and reconcile the current project"
    )
    update_parser.add_argument(
        "--dry-run", action="store_true", help="check for updates without applying them"
    )
    update_parser.add_argument(
        "--force",
        action="store_true",
        help="back up and overwrite conflicting files during reconciliation",
    )
    update_parser.add_argument("--verbose", action="store_true")

    uninstall_parser = subparsers.add_parser(
        "uninstall", help="remove Rivet-managed configuration, keeping user files"
    )
    uninstall_parser.add_argument(
        "--dry-run", action="store_true", help="show what would be removed"
    )
    uninstall_parser.add_argument("--verbose", action="store_true")

    vendor_parser = subparsers.add_parser(
        "vendor", help="re-vendor upstream artifacts (maintainers)"
    )
    vendor_parser.add_argument(
        "--yes", action="store_true", help="pull changes without prompting"
    )
    vendor_parser.add_argument(
        "names",
        nargs="*",
        metavar="NAME",
        help="artifact names to vendor (default: all)",
    )

    return parser


def _confirm(prompt: str, assume_yes: bool) -> bool:
    """
    Ask the user to confirm an action.

    Args:
        prompt: The confirmation question.
        assume_yes: Skip the prompt and assume yes.

    Returns:
        True if the action should proceed.
    """
    if assume_yes:
        return True
    # Non-interactive stdin (e.g. piped input): never block on a prompt,
    # treat it as a "no".
    if not sys.stdin.isatty():
        return False

    reply = input(f"{prompt} [y/N] ").strip().lower()
    return reply in ("y", "yes")


def _bootstrap_shell_command() -> None:
    """
    Register or refresh a `rivet` shell function in the user's rc file.

    Shell-gated and idempotent: unsupported shells are skipped, and an existing
    marker block is replaced when it points at a stale checkout path.
    """
    shell = shell_rc.login_shell()
    rc = shell_rc.rc_path(shell)
    if rc is None or shell is None:
        name = shell or "unset"
        output.debug(f"skipped shell command bootstrap (unsupported shell: {name})")
        return
    script = ROOT_PATH / "bin" / "rivet"
    result = shell_rc.ensure_block(rc, shell_rc.bootstrap_block(script, shell))
    if result == "ready":
        output.success("Shell command", "already registered")
        return
    if result == "repaired":
        output.attention("Shell command", "repaired incomplete block")
    else:
        output.success("Shell command")
    output.info(f"Run `exec {shell}` to load it in this terminal.")


def _unbootstrap_shell_command() -> None:
    """Remove the Rivet shell function from every supported rc file."""
    removed = []
    for shell in shell_rc.RC_FILES:
        rc = shell_rc.rc_path(shell)
        if rc is None:
            continue
        if shell_rc.remove_block(rc):
            removed.append(rc)
    if removed:
        for rc in removed:
            output.info(f"Removed shell command from {rc}.")
    else:
        output.info("No Rivet shell command registered.")


def _attention_detail(count: int) -> str:
    """Return '1 item needs attention' or '3 items need attention'."""
    items = output.plural(count, "item")
    verb = "needs" if count == 1 else "need"
    return f"{items} {verb} attention"


def _stale_symlinks(manifest_data: dict, config_dir: Path) -> list[str]:
    """Return managed symlinks no longer declared in the manifest."""
    expected = operations.expected_symlink_targets(manifest_data)
    return [
        relative
        for _, relative in operations.managed_symlinks(config_dir, ROOT_PATH)
        if relative not in expected
    ]


def _run_init(
    manifest_data: dict,
    config_dir: Path,
    cwd: Path,
    *,
    force: bool,
    skip_project: bool,
    dry_run: bool,
) -> int:
    """Initialize or reconcile Rivet in the current project."""
    # The installer or `rivet update` already printed the banner.
    if os.environ.get("SKIP_RIVET_BANNER") != "1":
        output.banner("Rivet")

    root = project.git_root(cwd)
    output.heading("Project")
    if root is not None:
        output.success("Git repository", root.name)
    else:
        output.skip(
            "Git repository",
            "not a Git repository, so project tools were skipped",
        )

    if dry_run:
        changes = plan.config_changes(manifest_data, ROOT_PATH, config_dir)
        if not skip_project and root is not None:
            changes += plan.project_changes(ROOT_PATH, cwd)
        plan.print_changes(changes)
        output.info("Dry run: no files were changed.")
        return 0

    stale = _stale_symlinks(manifest_data, config_dir)
    prune = True
    if stale and not force:
        noun = "stale managed symlink"
        prune = _confirm(
            f"Remove {output.plural(len(stale), noun)}?",
            assume_yes=False,
        )

    output.heading("Installing")
    groups = operations.sync(
        manifest_data, ROOT_PATH, config_dir, force, prune=prune
    )
    _bootstrap_shell_command()

    if not skip_project and root is not None:
        project.init_project(
            cwd,
            # Never bypassed by --force: installing a binary is a system-level
            # change that must always be an explicit user choice.
            lambda prompt: _confirm(prompt, False),
            SRC_INSTRUCTION_PATH,
            SRC_PLUGIN_PATH,
        )

    output.heading("Verifying")
    core_remaining = plan.config_changes(manifest_data, ROOT_PATH, config_dir)
    project_remaining = (
        plan.project_changes(ROOT_PATH, cwd)
        if not skip_project and root is not None
        else []
    )
    # A failed initial index is a warning from project.init_project, not an
    # install failure; leave it out of the verification count.
    project_remaining = [
        change for change in project_remaining if change.path != "codebase-memory graph"
    ]
    skipped = sum(group["skipped"] for group in groups.values())
    if core_remaining or skipped:
        output.attention("Installation", _attention_detail(len(core_remaining)))
        if skipped:
            output.info("Re-run with --force to replace conflicting files.")
        output.info("Run `rivet status` to see what is left.")
        return 1
    if project_remaining:
        output.attention("Project", _attention_detail(len(project_remaining)))
        output.info("Install the missing tools, then run `rivet init` again.")
        return 0
    output.success("Installation")
    print()
    output.info("Ready.")
    return 0


def _run_status(manifest_data: dict, config_dir: Path, cwd: Path) -> int:
    """Print the current installation state and return non-zero on failure."""
    return status.print_status(manifest_data, ROOT_PATH, config_dir, cwd)


def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a git command against the Rivet checkout."""
    return subprocess.run(
        ["git", "-C", str(ROOT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _checkout_state() -> str:
    """Return "current", "behind", "unknown", or "error" for the checkout."""
    if not (ROOT_PATH / ".git").exists():
        return "unknown"
    try:
        fetched = _git("fetch", "--quiet")
        head = _git("rev-parse", "HEAD")
        upstream = _git("rev-parse", "@{u}")
    except (OSError, subprocess.SubprocessError):
        return "error"
    if fetched.returncode != 0:
        return "error"
    if head.returncode != 0 or upstream.returncode != 0:
        return "unknown"
    return "current" if head.stdout.strip() == upstream.stdout.strip() else "behind"


def _update_checkout() -> bool | None:
    """Pull the Rivet checkout. Returns True/False, or None when not a checkout."""
    state = _checkout_state()
    if state == "unknown":
        output.skip("Rivet", "not a Git checkout")
        return None
    if state == "error":
        output.attention("Rivet", "could not check for updates")
        return None
    if state == "current":
        output.success("Rivet", "up to date")
        return True

    changes = _git("status", "--porcelain", "--untracked-files=no")
    if changes.returncode != 0 or changes.stdout.strip():
        output.failure("Rivet", "checkout has uncommitted changes")
        output.info("Commit or stash them, then re-run `rivet update`.")
        return False

    pulled = _git("pull", "--ff-only", "--quiet")
    if pulled.returncode != 0:
        output.failure("Rivet", "could not update the checkout")
        for line in (pulled.stderr or pulled.stdout).strip().splitlines()[-3:]:
            output.info(line)
        return False
    output.success("Rivet", "updated")
    return True


def _run_update(
    manifest_data: dict,
    config_dir: Path,
    cwd: Path,
    *,
    dry_run: bool,
    force: bool,
    verbose: bool,
) -> int:
    """Update the Rivet checkout, then reconcile the current project."""
    output.banner("Rivet")
    output.heading("Rivet")
    if dry_run:
        state = _checkout_state()
        if state == "behind":
            output.attention("Rivet", "update available")
            output.info("Run `rivet update` to apply.")
        elif state == "current":
            output.success("Rivet", "up to date")
        elif state == "error":
            output.attention("Rivet", "could not check for updates")
        else:
            output.skip("Rivet", "not a Git checkout")
        plan.print_changes(plan.all_changes(manifest_data, ROOT_PATH, config_dir, cwd))
        return 0

    updated = _update_checkout()
    if updated is False:
        return 1

    # Re-run init in a fresh process so a pull that changed Rivet's own code
    # takes effect immediately.
    args = [sys.executable, str(ROOT_PATH / "src" / "rivet.py"), "init"]
    if force:
        args.append("--force")
    if verbose:
        args.append("--verbose")
    env = os.environ.copy()
    env["SKIP_RIVET_BANNER"] = "1"
    return subprocess.run(args, cwd=cwd, check=False, env=env).returncode


def _run_uninstall(
    manifest_data: dict,
    config_dir: Path,
    cwd: Path,
    *,
    dry_run: bool,
) -> int:
    """Remove Rivet-managed configuration while preserving user files."""
    output.banner("Rivet")
    root = project.git_root(cwd)
    if dry_run:
        plan.print_changes(
            plan.uninstall_changes(manifest_data, ROOT_PATH, config_dir, cwd)
        )
        output.info("Dry run: no files were changed.")
        return 0

    output.heading("Removing")
    operations.uninstall(manifest_data, ROOT_PATH, config_dir)
    _unbootstrap_shell_command()
    if root is not None:
        for line in project.uninstall_project(root, SRC_PLUGIN_PATH):
            output.info(line)
    print()
    output.info("Files that differ from what Rivet installed were left in place.")
    if root is not None:
        output.info("OpenSpec files and codebase-memory runtime flags stay in the project.")
    output.info(f"Rivet itself remains at {ROOT_PATH}.")
    return 0


def _run_vendor(
    manifest_data: dict,
    names: list[str],
    assume_yes: bool,
) -> int:
    """
    Report upstream drift and pull changes for vendor/fork artifacts.

    Args:
        manifest_data: The parsed manifest dictionary.
        names: Artifact names to vendor; empty vendors all.
        assume_yes: Pull changes without prompting.

    Returns:
        0 on success, non-zero if any artifact failed.
    """
    # No explicit names given — vendor every artifact declared in the manifest.
    targets = names if names else manifest.artifact_names(manifest_data)

    # Pass 1: report drift and collect the artifacts that are behind.
    behind = []
    exit_code = 0
    for artifact_name in targets:
        artifact = manifest.find(manifest_data, artifact_name)

        if artifact is None:
            # This should only happen if the user provided names manually
            output.info(f"Unknown artifact: {artifact_name}.")
            exit_code = 1
            continue

        result = merge.update_artifact(MANIFEST_PATH, ROOT_PATH, artifact, check_only=True)
        if result == merge.DRIFT:
            behind.append(artifact_name)
        elif result != merge.UP_TO_DATE:
            exit_code = 1

    if not behind:
        # Unresolved forks report an error without drift, so only claim
        # everything is current when nothing failed.
        if exit_code == 0:
            output.success("Vendor", "up to date")
        return exit_code

    noun = "artifact"
    if not _confirm(
        f"Pull upstream changes for {output.plural(len(behind), noun)}?",
        assume_yes,
    ):
        output.info("Update skipped.")
        return exit_code

    # Pass 2: pull upstream for the artifacts that drifted.
    for artifact_name in behind:
        artifact = manifest.find(manifest_data, artifact_name)
        if artifact is None:
            continue
        if merge.update_artifact(MANIFEST_PATH, ROOT_PATH, artifact, check_only=False) != 0:
            exit_code = 1

    return exit_code


def main(argv: list[str] | None = None) -> int:
    """
    Parse arguments and dispatch to the requested subcommand.

    Args:
        argv: The argument list, or None to use sys.argv.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "verbose", False):
        output.set_verbose(True)

    # No subcommand given — print usage to stderr and exit 2
    if not args.command:
        parser.print_help(sys.stderr)
        return 2

    # Load the project manifest
    try:
        manifest_data = manifest.load(MANIFEST_PATH)
    except manifest.ManifestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    try:
        if args.command == "vendor":
            return _run_vendor(
                manifest_data,
                args.names,
                args.yes
            )

        config_dir = config.opencode_config_dir(manifest_data)
        cwd = Path.cwd()

        if args.command == "init":
            return _run_init(
                manifest_data,
                config_dir,
                cwd,
                force=args.force,
                skip_project=args.no_project,
                dry_run=args.dry_run,
            )
        if args.command == "status":
            return _run_status(
                manifest_data,
                config_dir,
                cwd
            )
        if args.command == "update":
            return _run_update(
                manifest_data,
                config_dir,
                cwd,
                dry_run=args.dry_run,
                force=args.force,
                verbose=args.verbose,
            )
        if args.command == "uninstall":
            return _run_uninstall(
                manifest_data,
                config_dir,
                cwd,
                dry_run=args.dry_run
            )
    except Exception as error:  # pylint: disable=broad-except
        print(f"error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
