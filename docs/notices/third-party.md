# Third-party Boundary

## Rule

**No third-party repository is copied into AI-AutoCut.**

Upstream projects are integrated as **dependencies or external references**.
Where a capability was validated during earlier work, the *decision and the
integration boundary* are recorded here; the upstream source is not vendored.

## Recorded upstreams

| Project | Upstream | Licence | Role | Code copied? | Modified? |
|---|---|---|---|---|---|
| jianying-editor-skill | `luoluoluo22/jianying-editor-skill`, commit `32c5692…`, VERSION 1.7.0 | **MIT** — Copyright (c) 2026 luoluoluo22 | Jianying draft generation | **No** — reference | No |
| pyJianYingDraft | vendored inside the above, `scripts/vendor/pyJianYingDraft` | **Apache-2.0** — Copyright 2024 GuanYixuan | Jianying draft writing | **No** | No |
| davinci-resolve-lite-mcp | `2sem/davinci-resolve-lite-mcp`, commit `3e6cc1d…` | **MIT** — Copyright (c) 2026 davinci-resolve-lite-mcp contributors | Evaluated MCP route (candidate A) | **No** | No |
| davinci-resolve-mcp | `samuelgursky/davinci-resolve-mcp`, v3.1.0 | **MIT** — attribution to `Bradford Operations LLC` also required | **Selected** Resolve MCP backend | **No** | No |
| resolve-mcp-server | `guycochran/resolve-mcp-server` | **No LICENSE file** | **Excluded** | **No** | No |

Licences above were read from the checkout's own `LICENSE` text during the
original audits, not recalled or taken from a web summary.

## Specific obligations

- **MIT** requires the copyright notice and permission notice to be retained in
  copies or substantial portions. Satisfied by reference rather than
  redistribution: nothing is copied here.
- **Apache-2.0** (the vendored Jianying dependency) additionally requires
  modified vendored files to be marked. Nothing is vendored here, so no marking
  obligation is triggered.
- `samuelgursky/davinci-resolve-mcp` additionally requires attribution to
  `Bradford Operations LLC`. This must be carried into any future distribution
  that includes it.
- `guycochran/resolve-mcp-server` has **no licence file**. It was marked
  `LICENSE_RISK` and excluded. It must not be integrated without a licence.

## No re-litigation

The MCP selection and the Jianying compatibility canary were both completed and
decided — see `docs/decisions/ADR-0002` and `ADR-0003`. They are not re-run here.

## Licence of this repository

**Apache-2.0**, applied — the full licence text is at `LICENSE` in the repository
root. Decision record: `LICENSE_DECISION_PENDING.md`.

This choice is compatible with every boundary above: nothing was copied from
upstream, MIT and Apache-2.0 are both permissive, and the `Bradford Operations
LLC` attribution is an upstream notice-retention obligation rather than a
constraint on this repository's own licence. It is carried forward in any future
distribution that includes that project.

No top-level `NOTICE` file is required today, because no upstream `NOTICE` is
being redistributed. If third-party files are ever actually included in a
distribution of this work, that must be revisited — see
`LICENSE_DECISION_PENDING.md`.
