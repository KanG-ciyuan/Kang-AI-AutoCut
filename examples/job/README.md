# Example Job

```
ILLUSTRATIVE SHAPE — NOT CONSUMED BY ANY CODE
```

`example_job.json` shows the **shape** of a job request as it was imagined before
the production control path existed: what a supervisor might state before
production begins.

**Nothing consumes this file.** It is not the job manifest the system writes, and
no code reads it. The real manifests are `job_manifest.v2` (generic jobs) and
`filter_job.v1` (the historical Filter job), both written by
`src/ai_autocut/job_foundation.py` during initialization.

This file is retained as a record of the interface as originally conceived. It is
**not** the current contract, and it should not be treated as one. For the current
picture see the production control path in `src/ai_autocut/fast_path.py`, the
artifact producer registry in `src/ai_autocut/producer_registry.py`, and
`docs/audit/execution-runbook.md`.

## What it describes

| Field | Meaning |
|---|---|
| `product` | the product, described by facts rather than adjectives |
| `platform` | delivery target and its frame geometry |
| `language` | on-screen and narration language |
| `target_duration_seconds` | a target, not a hard law |
| `source_media` | **logical** references resolved through `AUTOCUT_MEDIA_ROOT` |
| `creative_constraints` | what the edit must and must not do |
| `output_expectations` | what must be true of the delivered artifact |

## Rules the example follows

- **No absolute paths.** Source media is logical; locations resolve from
  `AUTOCUT_MEDIA_ROOT`. See `docs/architecture/operations.md`.
- **No media in the repository.** Media identity is a hash, never a file.
- **No credentials.** Providers are referenced by environment variable name.
- **Duration is a target.** Creative timing outranks hitting an exact number —
  see `docs/policies/audio-intelligence.md`.

## Status

| Part | Status |
|---|---|
| This example (`job_manifest.draft`) | **ILLUSTRATIVE — not consumed** |
| `job_manifest.v2` written by `initialize_job` | **IMPLEMENTED** — the generic job manifest |
| `filter_job.v1` written by `initialize_filter_job` | **IMPLEMENTED** — the historical Filter job |
| Production stage runner | **IMPLEMENTED** — `src/ai_autocut/fast_path.py` |
| Resume and downstream invalidation | **IMPLEMENTED** |
| Artifact registry, job queue | **NOT_IMPLEMENTED** |

This example file remains an unfrozen sketch and is retained for historical
context. The job manifests the system actually writes are defined by
`src/ai_autocut/job_foundation.py`, and the stage runner that consumes a job is
`src/ai_autocut/fast_path.py`.
