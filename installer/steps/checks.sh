# Platform, prerequisite, and OpenCode version checks.
# shellcheck shell=bash

function checks::check_platform
{
    local platform
    common::step "Checking"
    platform="$(uname -s)"
    case "$platform" in
        Darwin|Linux) ;;
        MINGW*|MSYS*|CYGWIN*)
            common::die "Windows is supported only through WSL. Open a WSL shell and re-run this installer."
            ;;
        *)
            common::die "unsupported operating system: $platform. Use macOS, Linux, or WSL."
            ;;
    esac
    common::success "Platform"
}

function checks::check_prerequisites
{
    local candidate
    local cmd
    local missing=""

    for cmd in git curl opencode
    do
        if ! command -v "$cmd" >/dev/null 2>&1
        then
            missing="$missing $cmd"
        fi
    done

    PYTHON=""
    for candidate in python3 python
    do
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
        then
            PYTHON="$candidate"
            break
        fi
    done

    # If we couldn't find a suitable python, add it to the missing software list
    if [[ -z "$PYTHON" ]]
    then
        missing="$missing python3(3.9+)"
    fi

    # If we found missing software, alert the user and exit
    if [[ -n "$missing" ]]
    then
        printf 'error: missing prerequisites:%s\n' "$missing" >&2
        printf '%s\n' 'Install them, then re-run the installer.' >&2
        exit 1
    fi
    common::success "Prerequisites"
}

function checks::check_opencode_version
{
    if ! OPENCODE_VERSION="$(common::run_interactive opencode --version)"
    then
        common::die "could not determine the OpenCode version (opencode --version failed)"
    fi
    if [[ ! "$OPENCODE_VERSION" =~ ([0-9]+)\.[0-9]+ ]]
    then
        common::die "could not parse the OpenCode version from: $OPENCODE_VERSION"
    fi
    OPENCODE_MAJOR=$((10#${BASH_REMATCH[1]}))
    if (( OPENCODE_MAJOR < 2 ))
    then
        common::die "OpenCode V2 is required (found: $OPENCODE_VERSION). Upgrade: opencode upgrade"
    fi
    common::success "OpenCode" "${OPENCODE_VERSION#opencode }"
}
