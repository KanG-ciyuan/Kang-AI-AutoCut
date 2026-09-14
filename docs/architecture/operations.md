# Operations

## Path configuration

No committed source file, test, fixture, schema, or configuration carries a
personal absolute path. Every machine-specific location is a **logical role**
resolved from an environment variable at runtime.

| Logical role | Environment variable | Meaning |
|---|---|---|
| `workspace` | `AUTOCUT_WORKSPACE` | runtime workspace for job state and artifacts |
| `media_root` | `AUTOCUT_MEDIA_ROOT` | external source and render media root |
| `legacy_workspace` | `AUTOCUT_LEGACY_WORKSPACE` | read-only historical R&D evidence |
| `ascii_staging` | `AUTOCUT_ASCII_STAGING` | ASCII-safe staging root for Resolve |
| `davinci_path` | `DAVINCI_PATH` | DaVinci Resolve application path |
| `jianying_path` | `JIANYING_PATH` | Jianying application or draft path |

Implementation: `src/ai_autocut/paths.py`.

Roles are **not defaulted to a developer's home directory**. An unset required
role raises `PathConfigurationError` naming the variable to set. A silent
fallback to one machine's layout is how a canonical repository starts depending
on one person's disk.

Copy `config/examples/autocut.env.example` to a local, untracked file to
configure a machine. The example file contains no real values.

## Resolve ASCII staging rule

**Validated rule.** DaVinci Resolve Free 21.0.0 was observed to fail *silently*
on non-ASCII I/O paths. An external volume with a non-ASCII name is therefore
not a safe Resolve I/O location, and Resolve workflows must route through
short-lived ASCII-safe staging:

```
External Media
  -> ASCII-safe staging
  -> Resolve
  -> Render
  -> Verify
  -> External Workspace
```

Staging is temporary and must be cleaned up when the task ends. It is a working
directory, not an archive.

Implementation: `paths.assert_ascii_safe` and
`PathConfiguration.require_ascii_safe`. The rule is enforceable rather than
advisory, because the failure mode is silence: Resolve reports success and
writes nothing usable.

## Verification rule for every backend write

A write is not complete when it returns success. It is complete when:

```
Write -> Read-back -> Render -> Pixel Validation
```

A `success=true` response from an editor API is a claim, not evidence. The
historical work recorded a real case where a call reported success, read back as
consistent, and rendered one frame of pure black. Read-back plus pixel
validation is what caught it.

## Cache growth

A staging cache directory once grew to roughly 9.1 GB before being cleaned up
manually. This is recorded as **evidence that an Artifact Registry and a cleanup
policy are genuinely needed**, not as a bug report.

Neither is implemented here. Phase 2 records the requirement; it does not build
the registry. Until one exists, staging directories are cleaned up by hand and
large intermediate media is kept outside the repository.

## What stays out of Git

Media, renders, caches, virtual environments, dependency trees, model weights,
editor project binaries, provider raw outputs, credentials, and secrets. See
`.gitignore` for the enforced list.
