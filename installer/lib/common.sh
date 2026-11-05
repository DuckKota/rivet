# Shared helpers for installer/run. Sourced, not executed.
# Functions are namespaced common:: so call sites show their origin.
# shellcheck shell=bash

# Color is opt-out (NO_COLOR) and only used on a terminal, so redirected and
# test output stays plain.
BOLD=""
DIM=""
GREEN=""
YELLOW=""
CYAN=""
RESET=""
if [[ -t 1 && -z "${NO_COLOR+x}" && "${TERM:-}" != "dumb" ]]
then
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    GREEN=$'\033[32m'
    YELLOW=$'\033[33m'
    CYAN=$'\033[36m'
    RESET=$'\033[0m'
fi

function common::die
{
    DIED=1
    printf 'error: %s\n' "$1" >&2
    exit 1
}

# Print one aligned status line: symbol, label, optional detail.
function common::component
{
    local symbol="$1"
    local label="$2"
    local detail="${3:-}"
    local color="${4:-}"
    local pad

    printf '  %s%s%s %s' "$color" "$symbol" "$RESET" "$label"
    if [[ -n "$detail" ]]
    then
        pad=$(( 24 - ${#label} ))
        (( pad < 1 )) && pad=1
        printf '%*s%s\n' "$pad" '' "$detail"
    else
        printf '\n'
    fi
}

function common::success
{
    common::component "✓" "$1" "${2:-}" "$GREEN"
}

function common::attention
{
    common::component "!" "$1" "${2:-}" "$YELLOW"
}

function common::step
{
    printf '\n  %s%s%s\n' "$BOLD" "$1" "$RESET"
}

# Render a path relative to $HOME as ~/... when possible.
function common::display_path
{
    local path="$1"
    if [[ -n "${HOME:-}" && "$path" == "$HOME"/* ]]
    then
        printf '~%s\n' "${path#"$HOME"}"
    else
        printf '%s\n' "$path"
    fi
}

# Quote a path only when it would not survive a plain shell word.
# shellcheck disable=SC2088  # the "~/" prefix is literal here
function common::shell_path
{
    local path="$1"
    if [[ "$path" == "~/"* && "$path" == *[[:space:]]* ]]
    then
        printf '~/%q\n' "${path#\~/}"
    elif [[ "$path" == *[[:space:]]* || "$path" == *[\'\"]* ]]
    then
        printf '%q\n' "$path"
    else
        printf '%s\n' "$path"
    fi
}

# Return the rc file for the current shell. Keep these paths in sync with
# src/shell_rc.py.
function common::rivet_shell_rc
{
    case "${SHELL##*/}" in
        zsh) printf '%s\n' "${HOME:-}/.zshrc" ;;
        bash) printf '%s\n' "${HOME:-}/.bashrc" ;;
        fish) printf '%s\n' "${XDG_CONFIG_HOME:-${HOME:-}/.config}/fish/config.fish" ;;
        *) return 1 ;;
    esac
}

# True when the registered function points at this install.
function common::rivet_shell_command_current
{
    local rc
    rc="$(common::rivet_shell_rc)" || return 1
    [[ -f "$rc" ]] \
        && grep -qF "# >>> rivet begin >>>" "$rc" \
        && grep -qF "$INSTALL_DIR/bin/rivet" "$rc"
}

# Run a command quietly. Successful output is hidden; on failure the captured
# output is replayed so diagnosis is not lost.
function common::run_quiet
{
    local output
    local status

    if output="$(common::run_interactive "$@" 2>&1)"
    then
        return 0
    else
        status=$?
        if [[ -n "$output" ]]
        then
            printf '%s\n' "$output" >&2
        fi
        return "$status"
    fi
}

# Report a command failure with the function stack that was active when the
# shell exited. common::die sets DIED to suppress this banner; every other
# non-zero exit gets the traceback.
function common::on_exit
{
    local status=$?
    local i

    if (( status == 0 || DIED == 1 ))
    then
        return
    fi

    printf '\nerror: install failed (exit %s)\n' "$status" >&2
    printf '  command: %s\n' "${RUN_COMMAND:-$BASH_COMMAND}" >&2

    # FUNCNAME[0] is this function. The rest are callers, with the function
    # that was running at the failure first. Bash adds a synthetic `main`
    # frame at the top level; skip it.
    for ((i = 1; i < ${#FUNCNAME[@]}; i++))
    do
        if [[ "${FUNCNAME[$i]:-}" == "main" ]]
        then
            continue
        fi
        printf '  at %s (%s)\n' \
            "${FUNCNAME[$i]:-?}" \
            "${BASH_SOURCE[$i]:-?}" >&2
    done

    printf '  Fix the problem, then re-run this installer.\n' >&2
}

function common::run_interactive
{
    local status

    RUN_COMMAND="$*"
    "$@" < /dev/tty
    status=$?
    RUN_COMMAND=""
    return "$status"
}

function common::opencode_config_dir
{
    local manifest="${1:-}"
    local config_dir

    # Precedence matches src/config.py: OC_CONFIG_DIR, manifest default,
    # `opencode debug paths`, then the XDG fallback. OpenCode itself ignores
    # OC_CONFIG_DIR, so the probe alone would miss a custom config directory.
    if [[ -n "${OC_CONFIG_DIR:-}" ]]
    then
        printf '%s\n' "${OC_CONFIG_DIR/#\~/${HOME:-}}"
        return
    fi

    if [[ -n "$manifest" && -f "$manifest" ]]
    then
        config_dir="$(sed -n 's/^[[:space:]]*default_config_dir[[:space:]]*=[[:space:]]*"\([^"]*\)".*$/\1/p' "$manifest" | head -n 1)"
        if [[ -n "$config_dir" ]]
        then
            printf '%s\n' "${config_dir/#\~/${HOME:-}}"
            return
        fi
    fi

    config_dir="$(common::run_interactive opencode debug paths 2>/dev/null \
        | sed -n 's/^config[[:space:]][[:space:]]*//p' | head -n 1 || true)"
    config_dir="${config_dir%$'\r'}"
    if [[ -z "$config_dir" ]]
    then
        config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
    fi
    printf '%s\n' "$config_dir"
}
