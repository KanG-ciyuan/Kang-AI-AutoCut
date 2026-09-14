# Architecture Decision Records

Each record captures a decision that historical work already validated. These
are written back as decisions rather than rediscovered as opinions.

| ADR | Decision | Status |
|---|---|---|
| [0001](ADR-0001-codex-supervisor-authority.md) | Codex is the only top-level supervisor | Accepted |
| [0002](ADR-0002-davinci-primary-visual-execution.md) | DaVinci Resolve is the primary automated visual execution backend | Accepted |
| [0003](ADR-0003-jianying-editable-delivery.md) | Jianying is the editable delivery / human takeover layer | Accepted |
| [0004](ADR-0004-backend-neutral-timeline.md) | One backend-neutral Executable Timeline, three compilers | Accepted |
| [0005](ADR-0005-conservative-color-match.md) | Conservative color match, product authenticity first | Accepted |
| [0006](ADR-0006-continuous-voice-over.md) | One continuous voice-over performance, cut into segments | Accepted |
| [0007](ADR-0007-local-first.md) | Local-first, no cloud infrastructure in Phase 1 | Accepted |
| [0008](ADR-0008-targeted-repair.md) | Targeted repair by default, never full regeneration | Accepted |

## Format

A record states the decision, the context that forced it, what was measured, and
what the decision forbids. A decision that forbids nothing is not a decision.
