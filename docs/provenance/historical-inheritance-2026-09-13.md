# Historical Inheritance — Frame Boundary Kernel

- Review date: 2026-09-13
- Historical provenance status: **historical source without Git provenance**
- Canonical history starts with: the AI-AutoCut commit that adds this record
- Migration method: reviewed, narrowly extracted, rewritten, and adapted

## What was inherited

Only the general engineering lessons behind exact frame conversion, end-exclusive source ranges, relative timeline placement, timeline-start protection, candidate-boundary review, source-out guarding, and pure read-back verification were inherited. Historical product rules, editor integrations, absolute paths, media, outputs, providers, and project identity were excluded.

The new implementation treats frames as canonical. Unlike the historical helper, it does not silently round a non-frame-aligned decimal timestamp. It also keeps read-back comparison independent of DaVinci Resolve or any MCP transport.

## Historical sources reviewed

All paths below are relative to the legacy R&D experiment workspace, resolved at
runtime from `AUTOCUT_LEGACY_WORKSPACE`, and remained read-only. The absolute
location is deliberately not recorded here: see
`docs/architecture/operations.md`.

| Historical source | Capability reviewed | SHA-256 |
|---|---|---|
| `filter-v4-davinci-execution-v0.1/adapter/frame_math.py` | frame conversion, end-exclusive ranges, relative placement, timeline-start protection | `a849150106daaedfc0080ab1e8afb0995099af3b804c148dd487151a72d041ce` |
| `filter-v4-davinci-execution-v0.1/adapter/resolve_adapter.py` | request-versus-read-back comparison logic only | `d8a91c1f76d7d52b5dc3068c062bc9144b53b93a5d167170446160892c761d6f` |
| `filter-v4-davinci-execution-v0.1/tests/test_adapter.py` | offline T01–T04 and pure T06 regression intent | `479816751ac61ddd211f0145330473a22a1e172d40ff6f327b26cbd3c1c6ad61` |
| `editing-intelligence-v1-phase1/src/contracts.py` | positive source-range validity | `f8931ea204d517b54b59e9b156373ed249458570d854b2eeeaea65f390db3fcf` |
| `editing-intelligence-v1-phase1/src/reviewer.py` | candidate boundary is not automatically a valid timeline cut | `520c47e683bfa485931d69ccd75a3d070ea7e0c2b178bfc8d3346e43be85eb10` |
| `editing-intelligence-v1-phase1/tests/test_phase1.py` | candidate-boundary regression intent | `4db22b7cf240794ca56e9145c89b7801f136e8dcbcd7fe8c8638bef3c9c79b96` |

The sanitized S06 regression fixture was distilled from these additional historical records:

| Historical source | SHA-256 |
|---|---|
| `editing-intelligence-v1-phase1/constraint-replan-regression-v0.1/02-editing-plan-v3.json` | `db6b095f24d2014b002ec6eaa15042897e560f0f905efee41d82babf7c002086` |
| `editing-intelligence-v1-phase1/constraint-replan-regression-v0.1/03-review-v3.json` | `4f6e24d64efced14c49bc09f6d422deaf1a08ec232605a932be8432db3b65bcf` |
| `editing-intelligence-v1-phase1/constraint-replan-regression-v0.1/04-repair-plan.json` | `f4cbb6d29b2b18251ccfb21b478bf152bd7a0f25d1528b66c043b7cbfcb439c1` |
| `editing-intelligence-v1-phase1/constraint-replan-regression-v0.1/05-editing-plan-v4.json` | `1cd7fc184ea48dcc655f7a5920aac516313b187d1fbdcbcde10eec2f66b49742` |
| `editing-intelligence-v1-phase1/constraint-replan-regression-v0.1/08-conclusion.md` | `5d2c277e4b4c8b953278a4d3eb72b72aa88500003564b82917d684d5f31f8855` |

No historical Git commit could be attributed to these files. No historical license file was found in the two reviewed source directories. Kang explicitly authorized this bounded inheritance into AI-AutoCut; the implementation and tests were rewritten rather than copied wholesale. No OpenMontage or other third-party code was used.

## New canonical locations

- `src/ai_autocut/frame_boundary.py` — rewritten frame and boundary kernel
- `tests/test_frame_boundary.py` — focused offline tests
- `tests/fixtures/s06_boundary_regression.json` — sanitized failure-and-repair evidence
- `docs/provenance/historical-inheritance-2026-09-13.md` — this provenance record

The S06 decimal values `20.23` and `20.18` are preserved only as historical labels. At 30fps neither is exactly frame-aligned. Canonical regression behavior is therefore expressed as an unsafe legacy-rounded end-exclusive frame `607` versus the historically verified safe end-exclusive frame `605`.
