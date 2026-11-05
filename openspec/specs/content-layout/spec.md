# content-layout Specification

## Purpose

Defines the repository layout contract: installable payload lives under `content/`, the manifest references only `content/` local paths, managed symlinks are limited to that directory, and partial checkouts are rejected.

## Requirements

### Requirement: Installable payload lives under content
The repository SHALL keep the installable payload — commands, skills, instructions, plugins, and themes — under a top-level `content/` directory. `src/` SHALL contain only the Python CLI modules and the vendored `tomli` package.

#### Scenario: Payload directories exist under content
- **WHEN** the repository layout is inspected
- **THEN** `content/commands`, `content/skills`, `content/instructions`, `content/plugins`, and `content/themes` exist
- **AND** the same directories do not exist under `src/`

#### Scenario: CLI modules remain under src
- **WHEN** the repository layout is inspected
- **THEN** `src/rivet.py` and the CLI modules exist under `src/`
- **AND** `src/` contains no installable payload directories

### Requirement: Manifest references content paths
Every manifest artifact's local `src` value SHALL be a repository-relative path beginning with `content/`. The upstream `source_path` SHALL remain relative to `source_repo`, and `target` SHALL remain relative to the OpenCode config directory.

#### Scenario: Every local source starts with content
- **WHEN** `manifest.toml` is loaded
- **THEN** every artifact and entry `src` begins with `content/`

#### Scenario: Vendor metadata stays upstream-relative
- **WHEN** a vendored artifact is inspected
- **THEN** its `source_path` does not begin with `content/`
- **AND** its `source_repo` and `source_sha` are unchanged

### Requirement: Managed symlink ownership is limited to content
`rivet uninstall`, stale-link pruning, and `rivet init --dry-run` SHALL treat only symlinks that resolve inside `<repo>/content` as Rivet-managed. Symlinks that resolve into `<repo>/src` SHALL be left untouched.

#### Scenario: Uninstall leaves src symlink
- **WHEN** the config directory contains a symlink into the repository's `src/`
- **THEN** `rivet uninstall` does not remove it

#### Scenario: Uninstall removes content symlink
- **WHEN** the config directory contains a managed symlink into the repository's `content/`
- **THEN** `rivet uninstall` removes it

### Requirement: Partial checkout is rejected
`bin/rivet` and `installer/steps/rivet.sh` SHALL require `content/commands` in addition to the existing sentinels. A checkout missing it SHALL fail with the existing "does not look like Rivet" error and SHALL NOT install anything.

#### Scenario: Missing payload fails early
- **WHEN** a checkout lacks `content/commands`
- **THEN** the bootstrap and installer exit non-zero with "does not look like Rivet"
- **AND** no configuration is installed

#### Scenario: Complete checkout proceeds
- **WHEN** a checkout contains `content/commands`
- **THEN** the bootstrap and installer proceed past the guard

### Requirement: Layout boundary is enforced by tests
The test suite SHALL fail when an artifact's local `src` does not begin with `content/` or when a payload directory exists under `src/`.

#### Scenario: Manifest drift is caught
- **WHEN** an artifact `src` is changed to a path outside `content/`
- **THEN** the layout test fails

#### Scenario: Payload drift is caught
- **WHEN** a payload directory is added under `src/`
- **THEN** the layout test fails
