# Download and install Rivet.
# shellcheck shell=bash

function rivet::download
{
    local changes
    local status=0

    # Piped mode (`curl | bash`) downloads only installer/run, then clones
    # ~/.rivet and re-execs from there. This function runs again inside that
    # checkout to ensure it is current.
    # File mode runs installer/run from a checkout directly (instead of using the
    # documented piped install command) so this is the first download of ~/.rivet.

    if [[ -e "$INSTALL_DIR" ]]
    then
        # rev-parse also accepts git worktrees, where .git is a file.
        if [[ "$(git -C "$INSTALL_DIR" rev-parse --is-inside-work-tree 2>/dev/null)" != "true" ]]
        then
            common::die "$INSTALL_DIR exists but is not a git clone. Remove it, then re-run this installer."
        fi

        # Untracked files cannot be lost by a fast-forward pull; only local
        # edits to tracked files block an update. This keeps e.g. .DS_Store
        # harmless.
        changes="$(git -C "$INSTALL_DIR" status --porcelain --untracked-files=no)" \
            || status=$?
        if (( status != 0 ))
        then
            common::die "could not read the git status of $INSTALL_DIR"
        fi
        if [[ -n "$changes" ]]
        then
            common::die "$INSTALL_DIR has uncommitted changes. Commit or stash them, then re-run this installer."
        fi
        git -C "$INSTALL_DIR" pull --ff-only --quiet
    else
        mkdir -p -- "$(dirname -- "$INSTALL_DIR")"
        git clone --quiet -- "$REPO_URL" "$INSTALL_DIR"
    fi

    if [[ ! -f "$INSTALL_DIR/manifest.toml" ]] \
        || [[ ! -f "$INSTALL_DIR/src/rivet.py" ]] \
        || [[ ! -f "$INSTALL_DIR/bin/rivet" ]] \
        || [[ ! -d "$INSTALL_DIR/content/commands" ]]
    then
        common::die "$INSTALL_DIR does not look like Rivet. Remove it, then re-run this installer."
    fi
}

function rivet::install
{
    # Capture this before init repairs the shell block: afterwards the block
    # always looks current, even when the running shell has not loaded it.
    SHELL_RELOAD=0
    if ! common::rivet_shell_command_current
    then
        SHELL_RELOAD=1
    fi

    cd -- "$ORIGINAL_DIR" || common::die "could not enter $ORIGINAL_DIR"

    # This function only runs through installer/run, which already printed the
    # banner, so skip it when entering the Python code.
    export SKIP_RIVET_BANNER=1

    common::run_interactive "$BASH_BIN" -- "$INSTALL_DIR/bin/rivet" init --force
}
