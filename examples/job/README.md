# Example Job

```
EXAMPLE ONLY
Pipeline Runner: NOT_IMPLEMENTED
```

`example_job.json` shows the **shape** of a job request: what a supervisor would
need to state before production could begin.

**Nothing consumes this file.** There is no stage runner, no job state machine,
and no command that turns a job manifest into a finished video. Given raw media,
product information, a platform, a language, and a target duration, this system
cannot yet produce a final MP4 in one command.

The example exists to define the interface boundary that a future pipeline will
implement — not to imply that the pipeline is implemented.

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
| Job manifest shape | defined by example |
| `job_manifest.v1` schema | **NOT_YET_A_CONTRACT** |
| Pipeline runner | **NOT_IMPLEMENTED** |
| Stage runner, resume/retry, artifact registry, queue | **NOT_IMPLEMENTED** |

The contract is deliberately not frozen yet. Freezing a job schema before the
runner exists would encode guesses about stages that have not been automated.
