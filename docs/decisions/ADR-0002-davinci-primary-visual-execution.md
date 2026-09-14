# ADR-0002 — DaVinci Resolve is the primary automated visual execution backend

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

Automated visual execution needs an editor that can be driven programmatically,
read back, and validated at the pixel level. Two candidate MCP routes were
evaluated against a locally installed DaVinci Resolve **21.0.0 Free (Mac App
Store sandboxed)** build, chosen over tool count:

```
Editing Intelligence
  -> Minimal Resolve Adapter / Guard
  -> Samuel compound MCP
  -> Resolve
```

The evaluator's stated criterion was *"which is least likely to let an AI
silently cut the wrong thing"*, not feature count.

## Measured findings

Candidate A (`2sem/davinci-resolve-lite-mcp`) and candidate B
(`samuelgursky/davinci-resolve-mcp`) both connected and both completed a
round-trip. They diverged on safety:

- **Timing:** A accepted an invalid record frame, reported success, read back as
  consistent, and rendered **one frame of pure black**. B rejected the same
  invalid value before the call.
- **Render:** A treated `{"jobId", "started": true}` as the result, without
  checking the file or its pixels. B verified the real output file and probed it.
- **Guards:** A's repository contained no dry-run, confirmation, or archive path.
  B provided confirmation tokens, pre-change archiving, dry-run, and read-back.
- **Errors:** A returned bare strings with no category or retryability, and
  reported a failed media import as a successful `count: 0`.

Decision: **switch to the compound (B) route.**

## Decision

DaVinci Resolve is the primary automated visual execution backend, driven
through the selected compound MCP route behind a minimal adapter and guard.

The adapter is not optional. It exists to close specific, measured API gaps.

## Core verification rule

```
Write -> Read-back -> Render -> Pixel Validation
```

`success=true` is never accepted as evidence that a write took effect. This rule
is not stylistic: it is the direct consequence of a measured silent failure.

## Operation rules

- Resolve work routes through **ASCII-safe staging** (see
  `docs/architecture/operations.md`). Resolve Free 21.0.0 fails silently on
  non-ASCII I/O paths.
- External Python `scriptapp("Resolve")` does not connect to this sandboxed
  distribution; the supported route is the in-application bridge.
- Timeline writes are verified by read-back **and** by decoding the render.

## Third-party boundary

The upstream project is **not vendored**. See `docs/notices/third-party.md` for
the recorded upstream, licence, role, and integration boundary. Only the
integration boundary is owned here.

## What this forbids

- Trusting an editor API's success flag as evidence.
- Treating a render job ID as a rendered file.
- Writing to Resolve through a non-ASCII path.
- Re-running the MCP selection experiment — the decision is made.
