# Design: split-src-content

## Context

`src/` currently serves two roles. It holds the Python CLI (`rivet.py`, `manifest.py`, `operations.py`, `plan.py`, and the rest) and the payload that `rivet init` installs (`commands/`, `skills/`, `instructions/`, `plugins/`, `themes/`). The manifest already distinguishes artifacts by `type` and `target`, but every local path is under `src/`, so the directory name carries no information about the artifact's role.

The CLI is a flat set of modules imported by `src/rivet.py`. There is no package and no `pyproject.toml`. The product is distributed as a Git checkout: `bin/rivet` locates Python and runs `src/rivet.py`; `installer/run` clones the checkout and calls `bin/rivet init --force`. There are no public installs.

## Goals / Non-Goals

**Goals:**

- Separate CLI source from installable payload.
- Make every manifest local path self-describing.
- Keep the flat Python layout, the bash bootstrap, and the installer where they are.
- Keep `uninstall`, prune, and stale-link cleanup limited to payload links.
- Make the move mechanical, reviewable, and covered by tests.

**Non-Goals:**

- Packaging the CLI (`pyproject.toml`, `python -m rivet`, `src/rivet/`).
- Moving `bin/` or `installer/`.
- Changing the manifest schema or version.
- Migrating public installs; none exist.
- Validating every manifest source before install (deferred).
- Reworking `src/tomli/`.

## Decisions

### Decision: top-level `content/` for the payload

All five payload directories move flat into `content/`: `commands/`, `skills/`, `instructions/`, `plugins/`, and `themes/`.

Rationale: `src/` conventionally means code, and the payload is data installed into another directory. A top-level `content/` makes the manifest's job obvious and keeps the payload independent of the CLI's import layout.

Alternatives considered: `artifacts/` matches the manifest vocabulary but reads like build output; `share/` is a Unix convention most contributors will not recognize; `assets/` implies images and fonts; `src/content/` keeps the ambiguity and lengthens every path.

### Decision: explicit `content/...` paths in the manifest

Every local `src` becomes `content/commands/fix.md`, `content/skills/glab`, and so on. No `content_dir` key and no resolver indirection.

Rationale: there is exactly one payload root and it is not expected to move again. The manifest's `src` stays a repository-relative path, which is what every resolver already assumes. A `content_dir` key would make `src` mean "relative to content_dir", forcing `operations.py`, `plan.py`, `merge.py`, validation, and every synthetic test manifest to join three pieces.

Alternatives considered: a `[config] content_dir` key with shorter `src` values. Rejected because it moves complexity into five call sites to save a prefix in one file.

### Decision: keep the Python CLI flat in `src/`

`src/rivet.py` and its sibling modules stay where they are. Imports remain `import manifest`, `import plan`, and so on.

Rationale: the product is a Git checkout, not a wheel. `bin/rivet` already locates the interpreter and executes `src/rivet.py`; `rivet update` re-execs the same path. A package layout would force every import, the re-exec, and the test `sys.path` inserts to change for no user-visible benefit.

Alternatives considered: `src/rivet/` with `__init__.py` and `__main__.py` plus `pyproject.toml`. Rejected as packaging work the product does not need.

### Decision: managed symlinks scoped to `<repo>/content`

`operations.managed_symlinks` resolves the payload root as `<repo>/content` instead of `<repo>/src`.

Rationale: `uninstall`, prune, and stale-link cleanup may only remove links Rivet created. A link into Python source is not payload; treating it as managed could delete a link the user made deliberately. Scoping to `content/` is the narrowest correct boundary.

Alternatives considered: keep the boundary at the repository root. Rejected because it would claim ownership of every in-repo symlink, including future non-payload directories.

### Decision: no migration code

The in-repo symlink auto-replace considered during design is dropped.

Rationale: there are no public installs, so there is no migration to smooth. The only checkout that can have old links is the maintainer's local `~/.rivet`, and `rivet init --force` replaces each conflicting link in one pass.

Alternatives considered: replace any symlink resolving inside the repo without `--force`, making `rivet update` self-healing. Rejected as code for a hypothetical future move.

### Decision: sentinel guard, not full source validation

`bin/rivet` and `installer/steps/rivet.sh` add `content/commands` to their existing checkout checks. `installer/run` keeps its current guard; the `rivet.sh` check runs immediately after the clone.

Rationale: the sentinel catches the realistic failure — a partial or corrupted checkout — before `rivet init` can create dangling symlinks. Validating every manifest source is a broader behavior change that belongs in its own proposal.

Alternatives considered: validate all manifest sources at plan time. Deferred; it changes `rivet diff` and `rivet init` behavior for every artifact, not just this move.

### Decision: tests follow real paths, synthetic fixtures stay

Real-repo assertions in `test_oc.py` and `test_cli.py` move to `content/`. Synthetic fixtures that build a temporary repo with `root / "src"` and `src = "src/..."` stay unchanged, because they test generic path handling, not this repository's layout. The shell-namespace scan moves from `src/` to `content/` so the one shell template remains covered. A new `tests/test_layout.py` enforces the boundary.

Rationale: updating synthetic fixtures adds churn without adding coverage. The layout test is the one place that should know the real directory names.

## Risks / Trade-offs

- [A hardcoded `src/` path is missed] → grep for `src/` after the move; `rivet diff` and the full test suite; the layout test catches manifest drift.
- [A partial checkout creates dangling symlinks] → the `content/commands` sentinel fails before install; full source validation is a documented follow-up.
- [The maintainer's local checkout keeps stale links] → one `rivet init --force`; documented in the change and in `MAINTAINING.md`.
- [Vendored artifacts break] → `rivet vendor` resolves `artifact["src"]` and `source_path` separately; `source_path` stays upstream-relative and `source_sha` is untouched.
- [85 manifest edits are error-prone] → one mechanical substitution plus the layout test; any missed `src = "src/..."` fails the test.
- [Test fixtures diverge from the real layout] → accepted; they exercise generic path resolution, and the layout test covers the real repository.

## Migration Plan

No public installs. For a local checkout:

1. Pull the change.
2. Run `rivet init --force`.
3. Run `rivet status` and `rivet diff` to confirm no stale links remain.

Rollback: revert the commit, then run `rivet init --force` again to relink the old `src/` paths.

## Open Questions

None.
