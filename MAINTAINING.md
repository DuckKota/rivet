# Maintaining Rivet

This document is the human record of *why* Rivet exists and how it stays
current. It complements `openspec/`, which records the *design rationale* of
Rivet itself. This file records the *content* decisions: what each artifact
is, where it came from, what we customized, and how to merge upstream changes.

OpenCode support requires V2. V1 config and plugin APIs are not supported.

## Usage

| Command | What it does |
| --- | --- |
| `rivet init` | Install managed files, remove stale symlinks, and initialize OpenSpec and codebase-memory-mcp in a Git repository (prompts first). |
| `rivet init --no-project` | Install global configuration only; skip per-project tool setup. |
| `rivet status` | Show the current installation state and what needs attention. |
| `rivet update` | Update the Rivet checkout, then reconcile the project. |
| `rivet uninstall` | Remove managed configuration and keep user files. |

`init` prompts before removing stale symlinks (`--force` overwrites conflicting
files and skips that prompt). `vendor` prompts before pulling upstream changes
(`--yes` skips). `uninstall` does not prompt: it only removes what Rivet
installed (managed symlinks, exact-content copies, and matched text blocks), so
it never touches your own config. In a non-interactive shell the prompts default
to no.

To update, pull the latest release and re-apply:

```bash
git pull
./bin/rivet init --force
```

Or run:

```bash
rivet update
```

After a release that moves managed payload paths, run `rivet init --force` once
to relink the affected files.

The machine-readable source of truth is `manifest.toml`. Every artifact in
that file has a `provenance` of `original`, `vendor`, or `fork`:

| Provenance | Meaning and `rivet vendor` behavior |
| --- | --- |
| `original` | Ours, no upstream. `rivet vendor` skips it. |
| `vendor` | Stolen, pristine, untouched. `rivet vendor` overwrites from upstream. |
| `fork` | Stolen and customized. `rivet vendor` three-way merges and reviews. |

Installable payload lives under `content/`; `src/` holds the Python CLI.

---

## Upstream index

| Upstream repo | What we take | Relationship |
| --- | --- | --- |
| [mattpocock/skills](https://github.com/mattpocock/skills) | **Command:**<br>`/grill-me`<br><br>**Skills:**<br>`diagnosing-bugs`, `codebase-design`, `domain-modeling`, `improve-codebase-architecture`, `grilling`, `writing-for-agents` | vendor |
| [obra/superpowers](https://github.com/obra/superpowers) | **Skill:**<br>`verification-before-completion` | vendor |
| [shir-danishyar/humanize](https://github.com/shir-danishyar/humanize) | **Command:**<br>`/humanizer`<br><br>**Skill:**<br>`humanize-writing` | vendor |
| [anthropics/skills](https://github.com/anthropics/skills) | **Skill:**<br>`frontend-design` | vendor |

---

## How to pull upstream changes

```bash
./bin/rivet vendor   # report drift, then pull changes (prompts first)
```

`vendor` alone is enough: every vendored artifact is a plain symlink into
`content/`, so pulling updates propagates to the live config automatically. No
reinstall needed.

The artifacts that install as copies, text inserts, or config merges are all
`original` and never vendored: `commit-message`'s substituted copy, the
`caveman` and `file-edit-limits` text inserts into `AGENTS.md`, and the
`theme-default` config merge. If you edit one by hand, a plain `rivet init`
won't refresh it. Use `--force`, or run `rivet uninstall` and then `rivet init`.

Behavior by provenance:

| Provenance | Behavior |
| --- | --- |
| `original` | Skipped. |
| `vendor` | Overwritten from upstream HEAD; `source_sha` bumped. |
| `fork` | Three-way merge with `git merge-file`. Details below. |

For a `fork`, the merge base is upstream at the pinned `source_sha`, ours is
our file, and theirs is upstream HEAD. A clean merge applies and bumps
`source_sha`. A conflict writes conflict markers into the file and bumps
`source_sha` to upstream HEAD, the revision the resolved file will be based
on. A file that still carries markers is never re-merged: `rivet vendor`
reports it as unresolved and refuses, so repeated runs cannot nest markers.
Resolve the markers, and the next `rivet vendor` sees the artifact as up to
date. The first fork update, with no `source_sha`, pins upstream as the base
and leaves our file untouched. That is deliberate: customizations are never
clobbered on the first run.

Hard rule: after any successful update, bump `source_sha`. Otherwise the merge
base drifts and future merges lie.

---

## Per-artifact notes

### Commands

#### grill-me (vendor, mattpocock)
Stolen verbatim; used as `/grill-me`. Upstream already delegates to the
`/grilling` skill rather than embedding the interview logic, so there is
nothing local to protect. See `grilling` below.

#### humanizer (vendor, shir-danishyar/humanize)
Single-file command; cleanly vendorable. Pulls `commands/humanizer.md`
verbatim.

#### commit-message (original)
Our `/commit-message` command plus the `verify-commit` validation script. The
command references the installed script path at install time.

#### fix (original)
Our `/fix` command (renamed from `/debug`).

#### opsx-refine (original)
Our `/opsx-refine` command: a deliberate second planning pass over an existing
OpenSpec change. Slots after `/opsx-propose` (and plan review) and before
`/opsx-apply`. Uses only the `description:` frontmatter, matching the generated
`opsx-*` command family.

### Skills

#### grilling (vendor, mattpocock)
The interview engine `/grill-me` invokes. When upstream changes wording, the
merge should carry it in.

#### diagnosing-bugs / codebase-design / domain-modeling / improve-codebase-architecture / writing-for-agents (vendor, mattpocock)
Pristine copies. Nothing local to protect; overwrite freely.

#### verification-before-completion (vendor, obra/superpowers)
Pristine copy.

#### humanize-writing (vendor, shir-danishyar/humanize)
The upstream repo keeps `SKILL.md` at the repo root, so the skill can't live
in one vendorable subdir. Instead it's assembled from three vendor artifacts,
each mirroring one upstream path into `content/skills/humanize-writing/`:

- `humanize-writing` → `SKILL.md`
- `humanize-writing-references` → `references/`
- `humanize-writing-scripts` → `scripts/`

Together they install as the `skills/humanize-writing/` skill directory.
Pulling upstream changes is a plain `rivet vendor`; the skill's own `tests/`
stay upstream (we don't vendor them).

#### frontend-design (vendor, anthropics/skills)
Pristine copy of the whole `skills/frontend-design` directory (`SKILL.md` plus
the `LICENSE.txt` its frontmatter references). Vendored as a directory artifact
so `rivet vendor` mirrors upstream wholesale. Pulling upstream changes is a
plain `rivet vendor`.

### Themes and instructions

#### caveman (original)
The terse "smart caveman" speaking rules, prepended to the global `AGENTS.md`.

#### file-edit-limits (original)
The chunked-assembly rule for large file writes, appended to `AGENTS.md`.

#### oc-github-dark (original)
Our own GitHub-dark theme. Not the default anymore; kept as a fallback theme
(`themes/oc-github-dark.json`).

#### poimandres / poimandres-turquoise-expanded / poimandres-accessible (vendor, ajaxdude)
Vendored from [ajaxdude/opencode-ai-poimandres-theme](https://github.com/ajaxdude/opencode-ai-poimandres-theme)
(`.opencode/themes/*.json`), kept exactly as upstream ships them. The default
theme is selected by the `theme-default` artifact (`config-merge` into
`cli.json`, key `theme.name`).

### Per-project

#### OpenSpec (original)
Per-project. `rivet init` sets it up when it runs inside a Git repository, not
through the manifest. `src/project.py` runs `openspec init --tools opencode`
in the repo root. Idempotent.

#### codebase-memory-reminder / codebase-memory-mcp (original)
Both are per-project. `rivet init` sets them up when it runs inside a Git
repository, not through the manifest. `src/project.py` prepends the
codebase-memory instructions to `AGENTS.md`, copies
`CodebaseMemoryReminder.ts` to `.opencode/plugins/CodebaseMemoryReminder.ts`,
merges the MCP server into `.opencode/opencode.json`, then sets `auto_index`
and `auto_watch`.
