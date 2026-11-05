## Why

`src/` currently holds two different things: the Python CLI (`rivet.py`, `manifest.py`, and the rest) and the payload that `rivet init` installs (`commands/`, `skills/`, `instructions/`, `plugins/`, `themes/`). That makes `src/` mean "code" and "data" at the same time, and it hides the fact that `manifest.toml` maps installable content to OpenCode config targets. Separating the two makes the CLI boundary explicit and keeps the payload independent of the CLI's flat import layout.

## What Changes

- Move the installable payload from `src/` to a new top-level `content/` directory: `commands/`, `skills/`, `instructions/`, `plugins/`, and `themes/`.
- **BREAKING** Update every manifest artifact's local `src` path from `src/...` to `content/...` (85 entries). `source_path` remains upstream-relative and `target` is unchanged.
- Update the Python path constants and per-project wiring that reference payload files directly (`src/rivet.py`, `src/plan.py`).
- Scope managed-symlink detection to `<repo>/content`, so `rivet uninstall`, prune, and stale-link cleanup never treat a symlink into `src/` as Rivet-managed.
- Require `content/commands` in the clone guards in `bin/rivet` and `installer/steps/rivet.sh`, so a partial checkout fails early with the existing "does not look like Rivet" message.
- Update real-repo test assertions and the shell-namespace scan; add one layout regression test that enforces the boundary.
- Update `MAINTAINING.md` payload references.
- No migration code. There are no public installs. An existing local checkout needs one `rivet init --force` after the move.

## Capabilities

### New Capabilities
- `content-layout`: Defines the repository contract that installable payload lives under `content/`, the manifest references only `content/` local paths, and managed symlink ownership is limited to that directory.

### Modified Capabilities
<!-- No existing spec-level requirements change. codebase-memory-gate and codebase-memory-initial-index are unaffected. -->

## Impact

- `manifest.toml`: 85 `src = "src/..."` paths become `content/...`; `source_path`, `source_sha`, `target`, and the schema version are unchanged.
- `src/rivet.py`: `SRC_INSTRUCTION` and `SRC_PLUGIN` point into `content/`; `rivet update` still re-execs `src/rivet.py`.
- `src/plan.py`: the two per-project plugin paths point into `content/plugins/`.
- `src/operations.py`: `managed_symlinks` scopes to `<repo>/content` instead of `<repo>/src`.
- `bin/rivet`, `installer/steps/rivet.sh`: add the `content/commands` sentinel.
- `tests/test_install_script.py`: fake kit creates `content/commands`; the shell-namespace scan covers `content/`.
- `tests/test_oc.py`, `tests/test_cli.py`: real-repo payload assertions move to `content/`.
- `tests/test_layout.py`: new test enforcing the manifest and directory boundary.
- `MAINTAINING.md`: payload references move to `content/`.
- No changes to `bin/` or `installer/` placement, the Python module layout, `src/tomli/`, the manifest schema, or the OpenSpec workflow.
