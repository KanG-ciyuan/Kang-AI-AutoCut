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
| `production_root` | `AUTOCUT_PRODUCTION_ROOT` | external production storage root for heavy media |
| `davinci_path` | `DAVINCI_PATH` | DaVinci Resolve application path |
| `jianying_path` | `JIANYING_PATH` | Jianying application or draft path |

Implementation: `src/ai_autocut/paths.py`.

Roles are **not defaulted to a developer's home directory**. An unset required
role raises `PathConfigurationError` naming the variable to set. A silent
fallback to one machine's layout is how a canonical repository starts depending
on one person's disk.

Copy `config/examples/autocut.env.example` to the local, untracked
`.env.local` file to configure a machine. The example file contains no real
values. Use `scripts/with-local-env` to load that file for a command without
manually exporting variables in each shell; for example:

```
scripts/with-local-env python3 -m unittest discover -s tests -v
```

The helper is intentionally a command wrapper, not a shell-startup change and
not a replacement for the environment-variable contract in `paths.py`.

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

## Production storage contract

Storage policy belongs to the production system, not to an Agent's memory. An Agent
does not need to know where frames, proxies, previews, intermediate renders or
temporary audio belong; it asks, and the system answers.

```text
Agent -> production entry point -> storage preflight -> job workspace -> production
```

The decision is made by `src/ai_autocut/storage_contract.py`, and it is the same
decision for every Agent — Work, Codex, DSH, a future Agent, or a direct
command-line tool. There is no Codex path policy, no Work path policy, and no DSH
path policy; there is one Kang AI-AutoCut storage contract.

### Resolution order

| Condition | Result |
|---|---|
| `production_root` is mounted and writable | `PRODUCTION_STORAGE` / `EXTERNAL` |
| it is not mounted, not writable, or unset | `PRODUCTION_STORAGE_BLOCKED` |
| blocked, **and** the Producer authorized this job internally | `INTERNAL_AUTHORIZED` |

A resolved job workspace is:

```text
<AUTOCUT_PRODUCTION_ROOT>/AI-AutoCut-Staging/<job-id>/
```

Completed jobs archive beneath `<AUTOCUT_PRODUCTION_ROOT>/AI-AutoCut-Archive/jobs/<job-id>/`.

### No silent internal fallback

**This is a hard rule.** When external production storage is unavailable,
production stops *before* heavy media is written. It never quietly continues on the
internal disk. The blocked result is machine-readable, so the operating Agent can
tell the Producer that the production volume must be connected:

```json
{"status": "PRODUCTION_STORAGE_BLOCKED",
 "reason": "EXTERNAL_PRODUCTION_STORAGE_UNAVAILABLE"}
```

A blocked decision carries **no** `job_workspace` at all. There is no internal path
for a caller to reach for, so a component that ignores `status` fails on `None`
rather than silently writing somewhere unexpected.

### Explicit one-time internal override

External storage is preferred whenever it is available; the override never
pre-empts it. When external storage is genuinely unavailable, the Producer may
authorize internal production for **one named job**:

```text
AUTOCUT_INTERNAL_PRODUCTION_JOB=<job-id>
```

This names an exact job id and nothing else. It is deliberately not a boolean,
because a boolean switch is how a one-time exception becomes a standing policy.
Even when authorized, the job must leave an internal free-space floor of **30 GB**
intact; an authorization permits internal production, it does not permit filling
the disk. Internal free space is always measurable, so this check always runs, and
an unmeasurable disk is treated as full — the safety decision fails closed.

### Asking the contract

Any Agent, and any direct tool operation such as a repair, an inspection, a
throwaway render or a preview build, resolves the authoritative workspace the same
way instead of inventing a path:

```bash
# Resolve the workspace for shell substitution
WORKSPACE="$(python3 -m src.ai_autocut.storage_contract --job-id JOB_ID --print-workspace)"

# Describe the policy itself, without running a job
python3 -m src.ai_autocut.storage_contract --job-id JOB_ID --describe
```

Exit codes: `0` resolved, `1` malformed question, `3` blocked.

### Known limitation: the compatibility workspace parameter

`job_foundation.initialize_job(workspace=...)` still accepts a caller-supplied
location. It is no longer the production entry point, and when a
`storage_decision` is passed it enforces that `workspace` **is** the resolved
location — but a caller that passes neither can still name its own path.

This is retained deliberately, not overlooked: `production.ensure_job` and the
offline test suite both depend on it, and removing the parameter in this change
would have traded a storage guarantee for a test-suite regression.

It is recorded here as a **future deprecation candidate**. The intended sequence
is (1) route `production.ensure_job` through `initialize_production_job`, (2) give
the offline suite a storage-resolved temporary root, (3) remove the parameter.
Until then, prefer `initialize_production_job` for anything that is real
production.

## Artifact lifecycle

Production intermediates are useful while a job is active. They are not
automatically permanent records.

```text
ACTIVE -> FINAL REVIEW -> ACCEPTED -> MASTER LOCKED -> RECORD FINALIZED
       -> ARCHIVE AUTHORITATIVE -> PRUNE REGENERABLE -> CLOSED
```

`src/ai_autocut/artifact_lifecycle.py` implements the classification. Two
properties make it Agent-independent:

* **The state decides, not the Agent.** A Work-produced variant and a
  DSH-produced variant follow the same retention rule because no Agent is
  consulted.
* **Nothing is prunable before `CLOSED`.** Every artifact is reported as retained
  until the job reaches the closing state, so an active or awaiting-review job is
  structurally protected rather than protected by the caller remembering to ask.

Classification is by production **role**, never by file extension: a `.mp4` may be
a Final Master and a `.png` may be required evidence. A role that is not positively
identified is reported `UNCERTAIN` and kept. The module never deletes anything — it
produces a classification and a byte total, and removal stays a separate,
Producer-approved act.

### A note on the earlier cache growth

A staging cache directory once grew to roughly 9.1 GB before being cleaned up
manually, and a later audit found a further multi-gigabyte body of production
scratch written to the internal temporary directory rather than the external
production volume. Both are recorded as evidence for the contract above rather
than as bug reports. The Artifact Registry itself remains unbuilt; the lifecycle
classification and the storage contract are what replace it for now.

## What stays out of Git

Media, renders, caches, virtual environments, dependency trees, model weights,
editor project binaries, provider raw outputs, credentials, and secrets. See
`.gitignore` for the enforced list.
