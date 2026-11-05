# Install Rivet's OpenCode plugins, then put Plannotator in manual mode.
# shellcheck shell=bash

PLANNOTATOR_PACKAGE="@plannotator/opencode@latest"

function plugins::install_plugin
{
    local label="$1"
    local package="$2"

    common::run_quiet opencode plugin add "$package" || common::die "could not install $label"
    common::success "$label"
}

function plugins::install_plannotator
{
    local output

    # The upstream installer prints a multi-section summary on stdout. Capture
    # stdout so a normal install stays quiet; stderr still reaches the user.
    # Replay captured stdout when the install fails so errors printed there are
    # not hidden. --non-interactive below is Plannotator's flag, not ours.
    if ! output="$(
        curl -fsSL --proto '=https' --proto-redir '=https' \
            --connect-timeout 10 --max-time 60 \
            https://plannotator.ai/install.sh \
            | "$BASH_BIN" -s -- --non-interactive --no-extras \
                --model-invocable none \
                --skip-codex --skip-gemini --skip-kiro --skip-vibe \
                --skip-qwen --skip-claude-plugin
    )"
    then
        if [[ -n "$output" ]]
        then
            printf '%s\n' "$output" >&2
        fi
        common::die "Plannotator installer failed"
    fi
    common::run_quiet opencode plugin add "$PLANNOTATOR_PACKAGE" || common::die "could not install Plannotator"
}

function plugins::configure_plannotator_manual
{
    local config_dir
    local config_file
    local name
    local status

    config_dir="$(common::opencode_config_dir "$INSTALL_DIR/manifest.toml")"
    if [[ ! -f "$config_dir/opencode.jsonc" && ! -f "$config_dir/opencode.json" ]]
    then
        common::die "no OpenCode config found in $config_dir after installing plugins"
    fi

    # OpenCode may read either file, so keep both in sync.
    for name in opencode.jsonc opencode.json
    do
        config_file="$config_dir/$name"
        [[ -f "$config_file" ]] || continue

        status=0
        PLANNOTATOR_PACKAGE="$PLANNOTATOR_PACKAGE" \
            "$PYTHON" "$SCRIPT_DIR/python/plannotator.py" "$config_file" || status=$?
        if (( status != 0 && status != 2 ))
        then
            common::die "could not set Plannotator to manual workflow in $config_file (file left unchanged)"
        fi
    done
}

function plugins::disable_default_sidebar_plugins
{
    local config_dir
    local status=0

    config_dir="$(common::opencode_config_dir "$INSTALL_DIR/manifest.toml")"
    "$PYTHON" "$SCRIPT_DIR/python/disabled_plugins.py" "$config_dir/cli.json" || status=$?
    if (( status != 0 && status != 2 ))
    then
        common::die "could not disable OpenCode's default sidebar plugins"
    fi
    common::success "Sidebar" "default plugins disabled"
}

function plugins::install_plugins
{
    common::step "Integrations"
    plugins::disable_default_sidebar_plugins
    plugins::install_plugin "Ponytail" "@dietrichgebert/ponytail"
    plugins::install_plugin "HeadsUp" "@banburist/opencode-headsup"
    plugins::install_plugin "Subagent Statusline" "opencode-subagent-statusline-v2"
    plugins::install_plannotator
    plugins::configure_plannotator_manual
    common::success "Plannotator" "manual workflow"
}
