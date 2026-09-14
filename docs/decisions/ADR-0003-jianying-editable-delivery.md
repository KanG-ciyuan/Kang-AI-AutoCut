# ADR-0003 — Jianying is the editable delivery / human takeover layer

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

Editable delivery means a human editor can open the result, change a title, and
export it themselves. That is a different requirement from automated rendering,
and it was validated separately.

The route:

```
Executable Timeline
  -> Jianying Timeline Compiler
  -> Jianying Draft
  -> Human Takeover
```

## Measured findings

A draft was generated entirely programmatically with no manual editing, then
opened in Jianying 11.4.2. It opened without crashing or prompting, the timeline
was correct (7.000 s, pixel ratio 0.748 against an expected 0.750, all four trim
samples matching), video / text / audio were independently editable, and the
project reopened intact after saving.

**The PASS carries one qualification that must travel with it.** The draft was
written in the older plaintext schema. Real 11.4.2 drafts are encrypted. On
open, Jianying migrated the draft: 7 files became 62, and `draft_info.json` went
from 18304 bytes of plaintext to 9880 bytes encrypted. Migration was
semantically lossless, which is why the result was a PASS rather than a PARTIAL
— but Jianying **rewrote the project's metadata**, and would do the same for any
older-format draft.

## Decision

Jianying is the **editable delivery and human takeover layer**, not the primary
AI GUI operator.

The **System Editing Plan / Executable Timeline is the source of truth**. The
Jianying project is a **compiled artifact** — an output that a human may then
own and modify.

## Consequences

- Handing over to a human is an explicit, expected end state of this route, not
  a failure of automation.
- A Jianying draft must never be treated as the canonical record of an edit.
  Once a human edits the draft, the artifact has diverged from the timeline by
  design.
- Because Jianying rewrites metadata on open, a generated draft is not
  byte-stable. Verification compares **semantics** — duration, trims, track
  structure, element editability — not file bytes.
- Auto-export is not part of this route. Upstream documents draft generation and
  automatic export as separate capabilities with different platform support.

## Third-party boundary

The upstream project and its vendored dependency are **not copied** into this
repository. See `docs/notices/third-party.md`.

## What this forbids

- Treating the Jianying draft as the source of truth.
- Asserting byte-level stability for a draft Jianying has opened.
- Re-running the Jianying compatibility canary — the decision is made.
- Driving the Jianying GUI as the primary production route.
