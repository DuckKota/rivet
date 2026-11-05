"""Tests for the one-command installer."""
from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import termios
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "installer" / "run"
BASH = shutil.which("bash") or "/bin/bash"


def _run_in_tty(
    argv: list[str],
    *,
    env=None,
    cwd=None,
    stdin_text: str | None = None,
    tty_input: str | None = None,
    tty_input_marker: str | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess:
    """Run argv with a controlling terminal so /dev/tty works."""
    master, slave = pty.openpty()
    if tty_input is not None:
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attrs)

    def claim_terminal() -> None:
        os.setsid()
        fcntl.ioctl(1, termios.TIOCSCTTY, 0)

    stdin = subprocess.PIPE if stdin_text is not None else slave
    proc = subprocess.Popen(
        argv,
        stdin=stdin,
        stdout=slave,
        stderr=slave,
        cwd=cwd,
        env=env,
        preexec_fn=claim_terminal,
        close_fds=True,
    )
    os.close(slave)
    if stdin_text is not None:
        assert proc.stdin is not None
        try:
            proc.stdin.write(stdin_text.encode())
        except BrokenPipeError:
            pass
        proc.stdin.close()
    pending_input = tty_input.encode() if tty_input is not None else None
    marker = tty_input_marker.encode() if tty_input_marker is not None else None
    if pending_input is not None and marker is None:
        try:
            os.write(master, pending_input)
        except OSError:
            pass
        pending_input = None

    chunks = bytearray()
    deadline = time.monotonic() + timeout
    while True:
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.extend(data)
            if pending_input is not None and marker in chunks:
                os.write(master, pending_input)
                pending_input = None
        elif proc.poll() is not None:
            break
        if time.monotonic() > deadline:
            os.killpg(proc.pid, signal.SIGKILL)
            break

    proc.wait()
    os.close(master)
    text = bytes(chunks).decode(errors="replace").replace("\r\n", "\n")
    return subprocess.CompletedProcess(argv, proc.returncode, text, text)


def _run(*args: str, env=None, cwd=None) -> subprocess.CompletedProcess:
    return _run_in_tty([BASH, str(SCRIPT), *args], env=env, cwd=cwd)


def _run_piped(*args: str, env=None, cwd=None) -> subprocess.CompletedProcess:
    return _run_in_tty(
        [BASH, "-s", "--", *args],
        env=env,
        cwd=cwd,
        stdin_text=SCRIPT.read_text(),
    )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _script(body: str, **values: str) -> str:
    for key, value in values.items():
        body = body.replace(f"@{key}@", value)
    return textwrap.dedent(body)


def _make_env(
    tmp_path: Path,
    *,
    config_text: str | None = None,
    config_name: str = "opencode.jsonc",
    rivet_exit: int = 0,
    version: str = "opencode v2.2.1",
    status_output: str = "",
    curl_exit: int = 0,
    models_output: str = "",
    plugin_add_output: str = "",
    plugin_add_exit: int = 0,
    plugin_add_writes_config: bool = True,
    plugin_list_output: str = (
        "ID  VERSION  SOURCE\n"
        "ponytail  5.3.3  @dietrichgebert/ponytail\n"
        "plannotator  0.28.38  @plannotator/opencode@latest\n"
        "headsup  0.5.0  @banburist/opencode-headsup\n"
        "opencode-subagent-statusline-v2  0.1.2  opencode-subagent-statusline-v2"
    ),
    plugin_list_exit: int = 0,
    pull_output: str = ":",
    home: Path | None = None,
    preinstall: bool = True,
    platform: str | None = None,
) -> SimpleNamespace:
    home = home or tmp_path / "home"
    fake_bin = tmp_path / "bin"
    work = tmp_path / "work"
    fake_kit = tmp_path / "fake-kit"
    for path in (
        home,
        fake_bin,
        work,
        fake_kit / "src",
        fake_kit / "bin",
        fake_kit / "content" / "commands",
    ):
        path.mkdir(parents=True, exist_ok=True)

    (fake_kit / "manifest.toml").write_text("version = 2\n")
    (fake_kit / "src" / "rivet.py").write_text("")
    shutil.copy2(REPO / "src" / "jsonc.py", fake_kit / "src" / "jsonc.py")
    shutil.copytree(REPO / "installer", fake_kit / "installer")

    rivet_log = tmp_path / "rivet.log"
    _write_executable(
        fake_kit / "bin" / "rivet",
        _script(
            """\
            #!/usr/bin/env bash
            printf 'rivet %s\\n' "$*" >> "@LOG@"
            pwd >> "@LOG@"
            exit @EXIT@
            """,
            LOG=str(rivet_log),
            EXIT=str(rivet_exit),
        ),
    )

    opencode_log = tmp_path / "opencode.log"
    _write_executable(
        fake_bin / "opencode",
        _script(
            """\
            #!/usr/bin/env bash
            printf 'opencode %s\\n' "$*" >> "@LOG@"
            case "$1" in
                --version) printf '%s\\n' "@VERSION@" ;;
                plugin)
                    case "$2" in
                        add)
                            if [[ "@WRITE_CONFIG@" == "1" && ! -f "@CONFIG@" ]]
                            then
                                mkdir -p "$(dirname -- "@CONFIG@")"
                                printf '{\\n  "plugins": []\\n}\\n' > "@CONFIG@"
                            fi
                            printf '%s\\n' "@ADD@"; exit @ADD_EXIT@
                            ;;
                        list) printf '%s\\n' "@LIST@"; exit @LIST_EXIT@ ;;
                    esac
                    ;;
                debug)
                    if [[ "$2" == "paths" ]]
                    then
                        printf 'config     %s\\n' "@HOME@/.config/opencode"
                    fi
                    ;;
                models)
                    if [[ -n "@MODELS@" ]]
                    then
                        printf '%s\\n' "@MODELS@"
                    fi
                    ;;
            esac
            exit 0
            """,
            LOG=str(opencode_log),
            VERSION=version,
            MODELS=models_output,
            ADD=plugin_add_output,
            ADD_EXIT=str(plugin_add_exit),
            LIST=plugin_list_output,
            LIST_EXIT=str(plugin_list_exit),
            WRITE_CONFIG="1" if plugin_add_writes_config else "0",
            CONFIG=str(home / ".config" / "opencode" / config_name),
            HOME=str(home),
        ),
    )

    _write_executable(
        fake_bin / "git",
        _script(
            """\
            #!/usr/bin/env bash
            if [[ "$1" == "clone" ]]
            then
                shift
                [[ "$1" == "--quiet" ]] && shift
                [[ "$1" == "--" ]] && shift
                cp -R "@KIT@" "$2"
                exit 0
            fi
            if [[ "$1" == "-C" ]]
            then
                repo="$2"
                shift 2
                [[ -d "$repo" ]] || exit 128
                case "$1" in
                    rev-parse) echo true ;;
                    status)
                        if [[ "$*" != *"--untracked-files=no"* ]]
                        then
                            echo "?? .DS_Store"
                        fi
                        @STATUS@
                        ;;
                    pull)
                        if [[ "$*" != *"--quiet"* ]]
                        then
                            @PULL@
                        fi
                        ;;
                esac
                exit 0
            fi
            exit 1
            """,
            KIT=str(fake_kit),
            STATUS=status_output,
            PULL=pull_output,
        ),
    )

    _write_executable(
        fake_bin / "curl",
        _script(
            """\
            #!/usr/bin/env bash
            if (( @EXIT@ != 0 ))
            then
                exit @EXIT@
            fi
            printf '#!/usr/bin/env bash\\nexit 0\\n'
            """,
            EXIT=str(curl_exit),
        ),
    )

    if platform is not None:
        _write_executable(
            fake_bin / "uname",
            _script(
                """\
                #!/usr/bin/env bash
                printf '%s\\n' "@PLATFORM@"
                """,
                PLATFORM=platform,
            ),
        )

    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / config_name
    if config_text is not None:
        config.write_text(config_text)

    install_path = home / ".rivet"
    if preinstall:
        shutil.copytree(fake_kit, install_path)

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["NO_COLOR"] = "1"
    # Keep tests on the success screen's static path: no animation, no clears.
    env["TERM"] = "dumb"
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]

    return SimpleNamespace(
        env=env,
        home=home,
        work=work,
        kit=fake_kit,
        fake_bin=fake_bin,
        install_dir=install_path,
        config=config,
        opencode_log=opencode_log,
        rivet_log=rivet_log,
    )


def test_install_script_parses():
    paths = [
        SCRIPT,
        REPO / "bin" / "rivet",
        REPO / "installer" / "test-installer",
        *sorted((REPO / "installer").rglob("*.sh")),
    ]
    for path in paths:
        result = subprocess.run(
            [BASH, "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{path}: {result.stderr}"


def test_shell_functions_are_namespaced_by_file():
    paths = [
        SCRIPT,
        REPO / "installer" / "test-installer",
        *sorted((REPO / "installer").rglob("*.sh")),
        *sorted((REPO / "content").rglob("*.sh")),
    ]
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.startswith("function "):
                continue
            name = line.split()[1]
            assert "::" in name, f"{path}: function {name} is not namespaced"


def test_help_exits_before_checks():
    result = _run("--help")
    assert result.returncode == 0
    assert "Usage: installer/run" in result.stdout


def test_help_works_without_a_terminal():
    result = subprocess.run(
        [BASH, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Usage: installer/run" in result.stdout


def test_piped_entrypoint_bootstraps_then_installs(tmp_path):
    env = _make_env(
        tmp_path, config_text='{\n  "theme": "x"\n}\n', preinstall=False
    )

    result = _run_piped(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr
    assert "Rivet" in result.stdout
    assert "Rivet is ready." in result.stdout
    assert "init --force" in env.rivet_log.read_text()


def test_piped_entrypoint_reuses_an_existing_checkout(tmp_path):
    env = _make_env(tmp_path, config_text='{\n  "theme": "x"\n}\n')

    result = _run_piped(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr
    assert "Rivet" in result.stdout
    assert "Rivet is ready." in result.stdout


def test_incomplete_checkout_is_rejected(tmp_path):
    env = _make_env(tmp_path, preinstall=False)
    kit = env.install_dir
    shutil.copytree(REPO / "installer", kit / "installer")
    for step in (kit / "installer" / "steps").glob("*.sh"):
        step.unlink()

    result = _run_in_tty(
        [BASH, str(kit / "installer" / "run")], env=env.env, cwd=env.work
    )
    assert result.returncode != 0
    assert "steps/checks.sh" in result.stderr


def test_partial_bootstrap_checkout_is_rejected(tmp_path):
    env = _make_env(tmp_path, preinstall=False)
    (env.install_dir / "installer").mkdir(parents=True)
    shutil.copy2(SCRIPT, env.install_dir / "installer" / "run")

    result = _run_piped(env=env.env, cwd=env.work)

    assert result.returncode != 0
    assert "does not look like Rivet" in result.stderr


def test_unknown_argument_is_rejected():
    result = _run("--bogus")
    assert result.returncode != 0
    assert "unknown argument" in result.stderr
    assert "install failed (exit" not in result.stderr


def test_removed_flags_are_rejected():
    for flag in ("--non-interactive", "--verbose", "-v"):
        result = _run(flag)
        assert result.returncode != 0
        assert "unknown argument" in result.stderr


def test_noninteractive_environment_is_rejected(tmp_path):
    env = _make_env(tmp_path, preinstall=False)

    result = subprocess.run(
        [BASH, str(SCRIPT)],
        cwd=env.work,
        capture_output=True,
        text=True,
        env=env.env,
        check=False,
    )

    assert result.returncode != 0
    assert "interactive terminal" in result.stderr
    assert not env.install_dir.exists()


def test_windows_is_rejected_with_wsl_hint(tmp_path):
    env = _make_env(tmp_path, platform="MINGW64_NT-10.0")
    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "WSL" in result.stderr


def test_home_must_be_absolute(tmp_path):
    env = _make_env(tmp_path)
    missing_home = dict(env.env)
    missing_home.pop("HOME")
    result = _run(env=missing_home, cwd=env.work)
    assert result.returncode != 0
    assert "HOME must be set" in result.stderr


def test_v1_is_rejected(tmp_path):
    env = _make_env(tmp_path, version="opencode v1.15.0")
    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "V2 is required" in result.stderr


def test_unparsable_version_is_rejected(tmp_path):
    env = _make_env(tmp_path, version="opencode")
    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "could not parse" in result.stderr


def test_missing_prerequisite_is_reported(tmp_path):
    env = _make_env(tmp_path)
    missing_bin = tmp_path / "missing-bin"
    missing_bin.mkdir()
    sources = {
        "uname": shutil.which("uname") or "/usr/bin/uname",
        "python3": shutil.which("python3") or sys.executable,
        "opencode": env.fake_bin / "opencode",
        "curl": env.fake_bin / "curl",
    }
    for name, target in sources.items():
        os.symlink(target, missing_bin / name)
    minimal_env = dict(env.env)
    minimal_env["PATH"] = str(missing_bin)

    result = _run(env=minimal_env, cwd=env.work)
    assert result.returncode != 0
    assert "missing prerequisites: git" in result.stderr


def test_magic_context_is_manual_only(tmp_path):
    env = _make_env(tmp_path)
    npx_log = tmp_path / "npx.log"
    _write_executable(
        env.fake_bin / "npx",
        _script(
            """\
            #!/usr/bin/env bash
            printf 'npx %s\\n' "$*" >> "@LOG@"
            """,
            LOG=str(npx_log),
        ),
    )

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert not npx_log.exists()
    assert "Install Magic Context now?" not in result.stdout
    assert "Install Magic Context (recommended):" in result.stdout
    assert "npx @cortexkit/magic-context@latest setup --harness opencode" in result.stdout


def test_unattended_install_configures_plannotator(tmp_path):
    env = _make_env(
        tmp_path,
        config_text='{\n  "theme": { "name": "x" }\n  // keep\n}\n',
    )

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr

    updated = env.config.read_text()
    assert "// keep" not in updated
    data = json.loads(updated)
    assert data["theme"] == {"name": "x"}
    assert data["plugins"][0]["options"]["workflow"] == "manual"
    assert "compaction" not in data
    assert not (env.home / ".config" / "cortexkit" / "magic-context.jsonc").exists()
    assert not env.config.with_name("opencode.jsonc.bak").exists()

    assert "Plannotator" in result.stdout
    assert "manual workflow" in result.stdout
    assert "Sidebar" in result.stdout
    assert "default plugins disabled" in result.stdout

    cli_config = json.loads(
        (env.home / ".config" / "opencode" / "cli.json").read_text()
    )
    assert cli_config["plugins"] == [
        "-opencode.sidebar.context",
        "-opencode.sidebar.footer",
    ]
    assert "OPENCODE USERS" not in result.stdout
    assert "CLAUDE CODE USERS" not in result.stdout

    log = env.opencode_log.read_text()
    assert "opencode plugin add @dietrichgebert/ponytail" in log
    assert "opencode plugin add @banburist/opencode-headsup" in log
    assert "opencode plugin add opencode-subagent-statusline-v2" in log
    assert "opencode plugin add @plannotator/opencode@latest" in log
    assert "opencode plugin add @cortexkit/opencode-magic-context@latest" not in log

    rivet_log = env.rivet_log.read_text()
    assert "init --force" in rivet_log
    assert str(env.work) in rivet_log


def test_invalid_json_config_is_left_untouched(tmp_path):
    original = '{ "theme": '
    env = _make_env(tmp_path, config_text=original)

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "invalid OpenCode config" in result.stderr
    assert env.config.read_text() == original
    assert not env.config.with_name("opencode.jsonc.bak").exists()


def test_plannotator_is_configured_for_manual_workflow(tmp_path):
    env = _make_env(
        tmp_path,
        config_text=(
            '{\n  "plugins": [\n    "@dietrichgebert/ponytail",\n'
            '    "@plannotator/opencode@latest"\n  ]\n}\n'
        ),
    )

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr

    data = json.loads(env.config.read_text())
    assert data["plugins"][0] == "@dietrichgebert/ponytail"
    assert data["plugins"][1] == {
        "package": "@plannotator/opencode@latest",
        "options": {"workflow": "manual"},
    }
    assert "manual workflow" in result.stdout


def test_manual_workflow_preserves_other_plugin_options(tmp_path):
    env = _make_env(
        tmp_path,
        config_text=(
            '{\n  "plugins": [\n    {\n'
            '      "package": "@plannotator/opencode@latest",\n'
            '      "options": { "workflow": "plan-agent", "runtime": "cli" }\n'
            '    }\n  ]\n}\n'
        ),
    )

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr

    data = json.loads(env.config.read_text())
    assert data["plugins"][0]["options"] == {
        "workflow": "manual",
        "runtime": "cli",
    }


def test_manual_workflow_is_idempotent(tmp_path):
    env = _make_env(
        tmp_path,
        config_text=(
            '{\n  "plugins": [\n    {\n'
            '      "package": "@plannotator/opencode@latest",\n'
            '      "options": { "workflow": "manual" }\n'
            '    }\n  ]\n}\n'
        ),
    )

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr
    assert "manual workflow" in result.stdout


def test_manual_workflow_updates_both_config_files(tmp_path):
    env = _make_env(
        tmp_path,
        config_text='{\n  "plugins": ["@plannotator/opencode@latest"]\n}\n',
    )
    json_file = env.config.with_name("opencode.json")
    json_file.write_text('{\n  "plugins": ["@plannotator/opencode@latest"]\n}\n')

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr

    for path in (env.config, json_file):
        data = json.loads(path.read_text())
        assert data["plugins"][0]["options"]["workflow"] == "manual"


def test_manual_workflow_is_added_to_both_config_files(tmp_path):
    env = _make_env(tmp_path, config_text='{\n  "theme": "jsonc"\n}\n')
    json_file = env.config.with_name("opencode.json")
    json_file.write_text('{\n  "theme": "json"\n}\n')

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr

    for path in (env.config, json_file):
        data = json.loads(path.read_text())
        assert data["plugins"][0]["options"]["workflow"] == "manual"


def test_empty_config_is_rejected(tmp_path):
    env = _make_env(tmp_path, config_text="")

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode != 0
    assert "is empty" in result.stderr
    assert env.config.read_text() == ""


def test_missing_opencode_config_is_an_error(tmp_path):
    env = _make_env(tmp_path, plugin_add_writes_config=False)

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode != 0
    assert "no OpenCode config found" in result.stderr
    assert not env.config.exists()


def test_oc_config_dir_controls_plannotator_config_location(tmp_path):
    env = _make_env(tmp_path)
    custom = tmp_path / "dotfiles" / "opencode"
    custom.mkdir(parents=True)
    custom_config = custom / "opencode.json"
    custom_config.write_text('{\n  "theme": "x"\n}\n')
    env.env["OC_CONFIG_DIR"] = str(custom)

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    data = json.loads(custom_config.read_text())
    assert data["plugins"][0]["options"]["workflow"] == "manual"
    assert "workflow" not in env.config.read_text()


def test_manifest_default_config_dir_controls_plannotator_config_location(tmp_path):
    env = _make_env(tmp_path)
    custom = env.home / "dotfiles" / "opencode"
    custom.mkdir(parents=True)
    custom_config = custom / "opencode.json"
    custom_config.write_text('{\n  "theme": "x"\n}\n')
    (env.install_dir / "manifest.toml").write_text(
        'version = 2\ndefault_config_dir = "~/dotfiles/opencode"\n'
    )

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    data = json.loads(custom_config.read_text())
    assert data["plugins"][0]["options"]["workflow"] == "manual"
    assert "workflow" not in env.config.read_text()


def test_installer_config_dir_resolution_matches_rivet(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "opencode",
        '#!/usr/bin/env bash\nprintf "config     %s\\n" "$HOME/.config/opencode"\n',
    )
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('version = 2\ndefault_config_dir = "~/dotfiles/opencode"\n')
    script = (
        f'source "{REPO}/installer/lib/common.sh"\n'
        f'common::opencode_config_dir "{manifest}"\n'
    )
    base_env = {
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "NO_COLOR": "1",
    }

    manifest_run = subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, env=base_env, check=False
    )
    assert manifest_run.stdout.strip() == str(home / "dotfiles" / "opencode")

    env_run = subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        env={**base_env, "OC_CONFIG_DIR": "~/env-dir"},
        check=False,
    )
    assert env_run.stdout.strip() == str(home / "env-dir")


def test_comment_only_config_is_rejected(tmp_path):
    env = _make_env(tmp_path, config_text="// keep\n")

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode != 0
    assert "is empty" in result.stderr
    assert env.config.read_text() == "// keep\n"


def test_jsonc_strings_with_comment_and_brace_markers_are_preserved(tmp_path):
    original = (
        '{\n  "url": "https://example.com/a//b",\n'
        '  "pattern": "a,b}c"\n}\n'
    )
    env = _make_env(tmp_path, config_text=original)

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr
    updated = env.config.read_text()
    assert '"https://example.com/a//b"' in updated
    assert '"a,b}c"' in updated
    assert '"workflow": "manual"' in updated


def test_config_symlink_is_preserved(tmp_path):
    env = _make_env(tmp_path)
    target = env.home / "dotfiles" / "opencode.jsonc"
    target.parent.mkdir()
    target.write_text('{\n  "theme": "x"\n}\n')
    env.config.symlink_to(target)

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr
    assert env.config.is_symlink()
    assert '"workflow": "manual"' in target.read_text()


def test_untracked_files_do_not_block_update(tmp_path):
    env = _make_env(tmp_path, config_text='{\n  "theme": "x"\n}\n')
    first = _run(env=env.env, cwd=env.work)
    assert first.returncode == 0, first.stderr

    (env.install_dir / ".DS_Store").write_text("junk\n")
    second = _run(env=env.env, cwd=env.work)
    assert second.returncode == 0, second.stderr


def test_tracked_changes_block_update(tmp_path):
    env = _make_env(
        tmp_path,
        config_text='{\n  "theme": "x"\n}\n',
        status_output='echo " M file"',
        preinstall=False,
    )
    first = _run(env=env.env, cwd=env.work)
    assert first.returncode == 0, first.stderr

    second = _run(env=env.env, cwd=env.work)
    assert second.returncode != 0
    assert "uncommitted changes" in second.stderr


def test_rivet_failure_reports_the_call_stack(tmp_path):
    env = _make_env(tmp_path, rivet_exit=1)
    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "error: install failed (exit 1)" in result.stderr
    assert "init --force" in result.stderr
    assert "at rivet::install" in result.stderr
    assert "at run::main" in result.stderr
    assert "plugin add @dietrichgebert/ponytail" not in env.opencode_log.read_text()


def test_curl_failure_stops_before_plannotator_plugin(tmp_path):
    env = _make_env(tmp_path, curl_exit=1)
    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "Plannotator installer failed" in result.stderr
    log = env.opencode_log.read_text()
    assert "plugin add @dietrichgebert/ponytail" in log
    assert "plugin add @plannotator/opencode" not in log


def test_plannotator_installer_output_is_suppressed(tmp_path):
    env = _make_env(tmp_path)
    _write_executable(
        env.fake_bin / "curl",
        "#!/usr/bin/env bash\n"
        "printf '#!/usr/bin/env bash\\n"
        "echo OPENCODE-USERS\\n"
        "exit 0\\n'\n",
    )

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr
    assert "Plannotator" in result.stdout
    assert "OPENCODE-USERS" not in result.stdout


def test_plannotator_installer_failure_output_is_replayed(tmp_path):
    env = _make_env(tmp_path)
    _write_executable(
        env.fake_bin / "curl",
        "#!/usr/bin/env bash\n"
        "printf '#!/usr/bin/env bash\\n"
        "echo PLANNATATOR-BOOM\\n"
        "exit 1\\n'\n",
    )

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "PLANNATATOR-BOOM" in result.stderr
    assert "Plannotator installer failed" in result.stderr
    assert "plugin add @plannotator/opencode" not in env.opencode_log.read_text()


def test_opencode_json_fallback_is_updated(tmp_path):
    env = _make_env(
        tmp_path,
        config_name="opencode.json",
        config_text='{\n  "theme": "x"\n}\n',
    )

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr
    assert '"workflow": "manual"' in env.config.read_text()


def test_install_dir_with_spaces(tmp_path):
    env = _make_env(tmp_path, home=tmp_path / "home with spaces")
    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr
    assert "~/.rivet/bin/rivet" in result.stdout


def test_install_dir_file_is_rejected(tmp_path):
    env = _make_env(tmp_path, preinstall=False)
    env.install_dir.write_text("x\n")
    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "not a git clone" in result.stderr


def test_incomplete_clone_is_rejected(tmp_path):
    env = _make_env(tmp_path)
    (env.install_dir / "bin" / "rivet").unlink()
    result = _run(env=env.env, cwd=env.work)
    assert result.returncode != 0
    assert "does not look like Rivet" in result.stderr


def test_git_worktree_is_accepted(tmp_path):
    env = _make_env(tmp_path)
    (env.install_dir / ".git").write_text("gitdir: /tmp/elsewhere\n")

    result = _run(env=env.env, cwd=env.work)
    assert result.returncode == 0, result.stderr


def test_successful_output_is_structured_and_quiet(tmp_path):
    env = _make_env(tmp_path, pull_output="echo 'Already up to date.'")

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert out.startswith("Rivet\n")
    for heading in ("Checking", "Integrations", "Verifying"):
        assert f"\n  {heading}\n" in out
    assert "==>" not in out
    assert "Already up to date." not in out
    assert "✓ Platform" in out
    assert "✓ Prerequisites" in out
    assert "✓ OpenCode" in out
    assert "init --force" in env.rivet_log.read_text()
    assert "✓ Ponytail" in out
    assert "✓ HeadsUp" in out
    assert "✓ Subagent Statusline" in out
    assert "✓ Sidebar" in out
    assert "✓ Plannotator" in out
    assert "✗" not in out
    assert out.count("npx @cortexkit/magic-context@latest setup") == 1
    assert out.count("rivet init") == 1
    assert "Rivet is ready." in out
    assert "To initialize Rivet in new projects:" in out
    assert "To update Rivet:" in out
    assert "Install Magic Context (recommended):" in out
    assert "$ ~/.rivet/bin/rivet init" in out
    assert "$ ~/.rivet/bin/rivet update" in out
    assert "$ npx @cortexkit/magic-context@latest setup" in out


def test_success_screen_animates_on_a_real_terminal(tmp_path):
    env = _make_env(tmp_path)
    env.env["TERM"] = "xterm"
    env.env["FIREWORKS_DURATION"] = "1800"

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "\x1b[2J" in result.stdout
    assert "Rivet is ready." in result.stdout


def test_plugin_success_output_is_suppressed(tmp_path):
    env = _make_env(
        tmp_path,
        plugin_add_output='Plugin "@dietrichgebert/ponytail" installed and added',
    )

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "installed and added" not in result.stdout


def test_plugin_add_failure_is_reported_and_replayed(tmp_path):
    env = _make_env(
        tmp_path,
        plugin_add_exit=1,
        plugin_add_output="PLUGIN-BOOM",
    )

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode != 0
    assert "PLUGIN-BOOM" in result.stderr
    assert "error: could not install Ponytail" in result.stderr
    assert "install failed (exit" not in result.stderr
    assert "plugin add @plannotator/opencode" not in env.opencode_log.read_text()


def test_verification_failure_is_a_warning_not_a_failure(tmp_path):
    env = _make_env(
        tmp_path,
        plugin_list_exit=1,
        plugin_list_output="VERIFY-BOOM",
    )

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "VERIFY-BOOM" in result.stderr
    assert "verification failed" in result.stdout
    assert "Installed with warnings." in result.stdout
    assert "Rivet is installed." in result.stdout


def test_verification_uses_plugin_list(tmp_path):
    env = _make_env(tmp_path)

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "opencode plugin list\n" in env.opencode_log.read_text()


def test_missing_plugin_fails_verification(tmp_path):
    env = _make_env(
        tmp_path,
        plugin_list_output=(
            "ID  VERSION  SOURCE\n"
            "ponytail  5.3.3  @dietrichgebert/ponytail"
        ),
    )

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "verification failed" in result.stdout
    assert "Installed with warnings." in result.stdout


def test_summary_uses_shell_command_when_registered(tmp_path):
    env = _make_env(tmp_path)
    env.env["SHELL"] = "/bin/zsh"
    (env.home / ".zshrc").write_text(
        "# >>> rivet begin >>>\n"
        f'rivet() {{ {env.install_dir}/bin/rivet "$@"; }}\n'
        "# <<< rivet end <<<\n"
    )

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "rivet update" in result.stdout
    assert "rivet init" in result.stdout
    assert "exec zsh" not in result.stdout
    assert "~/.rivet/bin/rivet update" not in result.stdout
    assert "~/.rivet/bin/rivet init" not in result.stdout


def test_summary_reloads_stale_shell_command(tmp_path):
    env = _make_env(tmp_path)
    env.env["SHELL"] = "/bin/zsh"
    (env.home / ".zshrc").write_text(
        "# >>> rivet begin >>>\n"
        'rivet() { /kit/bin/rivet "$@"; }\n'
        "# <<< rivet end <<<\n"
    )

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "exec zsh" in result.stdout
    assert "~/.rivet/bin/rivet update" in result.stdout
    assert "~/.rivet/bin/rivet init" in result.stdout


def test_summary_falls_back_without_shell_command(tmp_path):
    env = _make_env(tmp_path)
    env.env["SHELL"] = "/bin/zsh"

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "~/.rivet/bin/rivet update" in result.stdout
    assert "~/.rivet/bin/rivet init" in result.stdout


def test_normal_output_has_no_temporary_paths(tmp_path):
    env = _make_env(tmp_path)

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert str(tmp_path) not in result.stdout
    assert "~/.rivet/bin/rivet" in result.stdout


def test_output_has_no_ansi_when_no_color_is_set(tmp_path):
    env = _make_env(tmp_path)
    env.env["NO_COLOR"] = "1"

    result = _run(env=env.env, cwd=env.work)

    assert result.returncode == 0, result.stderr
    assert "\x1b[" not in result.stdout
    assert "\x1b[" not in result.stderr


def test_test_installer_requires_terminal():
    result = subprocess.run(
        [BASH, str(REPO / "installer" / "test-installer")],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "requires an interactive terminal" in result.stderr


def test_test_installer_snapshot_omits_deleted_files(tmp_path):
    repo = tmp_path / "repo"
    installer = repo / "installer"
    installer.mkdir(parents=True)
    shutil.copy2(REPO / "installer" / "test-installer", installer / "test-installer")
    _write_executable(
        installer / "run",
        _script(
            """\
            #!/usr/bin/env bash
            if [[ -e "$(dirname -- "$0")/../deleted.txt" ]]
            then
                printf 'SNAPSHOT-STALE\\n'
                exit 1
            fi
            printf 'SNAPSHOT-CLEAN\\n'
            """
        ),
    )
    (repo / "deleted.txt").write_text("tracked then deleted\n")
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "init", "--quiet"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run(
        [
            *git,
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "snapshot",
        ],
        check=True,
    )
    (repo / "deleted.txt").unlink()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "opencode", "#!/usr/bin/env bash\nexit 0\n")

    env = dict(os.environ)
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]

    result = _run_in_tty(
        [BASH, str(installer / "test-installer")],
        env=env,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SNAPSHOT-CLEAN" in result.stdout


def test_test_installer_forwards_enter_and_sets_terminal_size(tmp_path):
    """test-installer must pass Enter through as CR, not translate it to LF."""
    repo = tmp_path / "repo"
    installer = repo / "installer"
    installer.mkdir(parents=True)
    shutil.copy2(REPO / "installer" / "test-installer", installer / "test-installer")
    _write_executable(
        installer / "run",
        _script(
            """\
            #!/usr/bin/env bash
            python3 - <<'PY'
            import os
            import termios

            fd = os.open("/dev/tty", os.O_RDWR)
            attrs = termios.tcgetattr(fd)
            attrs[0] &= ~termios.ICRNL
            attrs[3] &= ~(termios.ECHO | termios.ICANON)
            attrs[6][termios.VMIN] = 1
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            os.write(fd, b"READY\\n")
            reply = b""
            while not reply.endswith(b"\\r"):
                reply += os.read(fd, 1)
            size = os.get_terminal_size(fd)
            os.write(fd, b"reply=" + reply + f" size={size.lines} {size.columns}\\n".encode())
            PY
            """
        ),
    )
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "init", "--quiet"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run(
        [
            *git,
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "snapshot",
        ],
        check=True,
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "opencode", "#!/usr/bin/env bash\nexit 0\n")

    env = dict(os.environ)
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]

    result = _run_in_tty(
        [BASH, str(installer / "test-installer")],
        env=env,
        tty_input="y\r",
        tty_input_marker="READY",
        timeout=20,
    )

    assert result.returncode == 0, result.stdout
    assert "reply=y\r size=24 80" in result.stdout
