# ADR-0006 — One continuous voice-over performance, cut into segments

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

Scripted narration can be produced two ways: generate one clip per sentence, or
generate one performance and cut it. The per-sentence route looks cheaper and
more controllable, and it was rejected on a specific, reproducible ground:

> The same prompt does not reliably reproduce the same sampled speaker.

Generating line 2 in a separate call can return a different voice, accent, or
timbre than line 1, even with identical parameters. Concatenating the results
produces an audibly inconsistent narrator that no amount of level matching
fixes, because the problem is identity, not loudness.

The validated work produced a continuous performance and cut `VO1 / VO2 / VO3`
from it. Because all three lines share one performance, no per-segment RMS
normalization was applied — there was no discontinuity to correct.

## Decision

**One continuous voice-over performance produces a continuous VO master, which
is then cut into segments.**

The alternative — independently generating each sentence — is not the default
and requires an explicit reason.

## Creative timing window

Suggested timing windows are **targets, not laws**. When a locked line does not
fit its nominal window at a natural pace, the honest outcomes are: honour the
creative zone, adjust pacing within a defensible range, or report a timing
conflict for a decision.

Natural performance outranks forced mechanical timing. The historical work
recorded a case where a line physically could not fit its suggested window at
any usable speed — the fix was a decision, not more speed. A related failure
mode to avoid is a provider hard-truncating speech to hit a duration.

## Repair scope

A targeted repair stays inside its own range. The validated repair applied a
gain change of **−1.25 dB to one line only, over its own window, with no
regeneration, no time-stretch, no copy change, and no mechanical RMS matching**.

Sidechain behaviour was deliberately preserved: the ducking key came from the
unmodified bus, so background and water behaviour stayed sample-identical. The
repair changed one line's contribution and nothing else. This was verified by
re-running with the adjustment set to zero and confirming the output was
**byte-identical** to the previous mix.

## What this forbids

- Generating each sentence independently by default.
- Treating a suggested timing window as a hard constraint.
- Letting a provider truncate speech to fit a duration.
- Re-normalizing segments that came from one continuous performance.
- Changing global mix behaviour to fix a local problem.
