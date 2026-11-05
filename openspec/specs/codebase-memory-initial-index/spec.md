# codebase-memory-initial-index Specification

## Purpose

Defines how `rivet init` builds the codebase-memory graph on first init: a synchronous, idempotent, best-effort index, so a freshly initialized project has a usable graph.

## Requirements

### Requirement: Initial graph index on first install
When `rivet init` runs inside a git repository and the `codebase-memory-mcp` binary is available, Rivet SHALL index the repository's codebase-memory graph synchronously in `full` mode. Rivet SHALL skip the index when the project is already indexed. Rivet SHALL NOT fail or abort `rivet init` when the index fails.

#### Scenario: First install indexes the repo
- **WHEN** the user runs `rivet init` in a git repository whose codebase-memory graph is not yet indexed and the `codebase-memory-mcp` binary is available
- **THEN** Rivet prints an indexing progress line
- **AND** Rivet runs `index_repository` in `full` mode against the repository root
- **AND** on success, `index_status` reports the project as indexed

#### Scenario: Re-run skips when already indexed
- **WHEN** `rivet init` runs again on a project whose codebase-memory graph is already indexed
- **THEN** Rivet does not re-run `index_repository`
- **AND** Rivet reports that the graph is already indexed

#### Scenario: Index failure does not fail install
- **WHEN** `index_repository` exits non-zero during `rivet init`
- **THEN** Rivet prints a warning that the index failed
- **AND** Rivet continues and completes the install without error
