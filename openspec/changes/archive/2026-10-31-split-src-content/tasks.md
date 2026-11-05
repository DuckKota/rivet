## 1. Move the payload

- [x] 1.1 Move `src/commands`, `src/skills`, `src/instructions`, `src/plugins`, and `src/themes` to `content/`.
- [x] 1.2 Confirm no payload directory remains under `src/`.

## 2. Update the manifest

- [x] 2.1 Replace every local `src = "src/..."` with `src = "content/..."` in `manifest.toml` (85 entries).
- [x] 2.2 Confirm `source_path`, `source_sha`, `target`, and `version` are unchanged.
- [x] 2.3 Load the manifest and confirm validation passes.

## 3. Update CLI paths

- [x] 3.1 Point `SRC_INSTRUCTION` and `SRC_PLUGIN` in `src/rivet.py` at `content/`.
- [x] 3.2 Point the plugin paths in `src/plan.py` at `content/plugins/`.
- [x] 3.3 Scope `managed_symlinks` in `src/operations.py` to `<repo>/content` and update its comment.
- [x] 3.4 Grep `src/` for remaining payload references and resolve each one.

## 4. Update the guards

- [x] 4.1 Add `content/commands` to the checkout guard in `bin/rivet`.
- [x] 4.2 Add `content/commands` to the checkout guard in `installer/steps/rivet.sh`.
- [x] 4.3 Confirm `installer/run` stays unchanged and the `rivet.sh` guard still runs after the clone.

## 5. Update the tests

- [x] 5.1 Create `content/commands` in the fake kit in `tests/test_install_script.py`.
- [x] 5.2 Change the shell-namespace scan in `tests/test_install_script.py` from `src/` to `content/`.
- [x] 5.3 Update real-repo payload assertions in `tests/test_oc.py` and `tests/test_cli.py`.
- [x] 5.4 Leave synthetic `root / "src"` fixtures unchanged.
- [x] 5.5 Add `tests/test_layout.py`: every manifest local `src` starts with `content/`, and no payload directory exists under `src/`.
- [x] 5.6 Run `pytest tests/ -q` and fix failures.

## 6. Update the docs

- [x] 6.1 Update payload references in `MAINTAINING.md` to `content/`.
- [x] 6.2 Add one line defining `content/` as the installable payload.
- [x] 6.3 Confirm `README.md` and `.gitlab-ci.yml` need no change (`mypy src/` and `pylint src/` stay).

## 7. Verify

- [x] 7.1 Run `mypy src/` and `pylint src/`.
- [x] 7.2 Run `bash -n bin/rivet installer/run installer/test-installer` and the installer shell checks.
- [x] 7.3 Run `openspec validate --changes split-src-content`.
- [x] 7.4 Run `./installer/test-installer` in a terminal.
- [x] 7.5 Document the one-time `rivet init --force` for the maintainer's local checkout; do not run it without approval.
