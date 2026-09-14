# Supervisor Authority

## Decision

**Codex is the only top-level supervisor of AI-AutoCut.**

This is a structural constraint on the product, not an operational preference.
It is recorded here because a system that delegates production work to several
models will otherwise drift into several competing authorities.

## What the supervisor owns

- reading job state
- deciding which intelligent stage runs next
- invoking the deterministic runtime
- delegating bounded engineering tasks
- inspecting evidence
- authorizing repair
- authorizing release

## What every other agent is

DeepSeek Harness, Claude Code, and any comparable system are **engineering
workers**. They execute bounded tasks inside a scope granted by the supervisor.

A worker must not:

- override a supervisor decision
- change architecture independently
- declare a release independently
- push production changes independently
- promote a Gold record to a frozen state

Workers are peers of each other, never peers of the supervisor.

## The division of labour

| Responsibility | Owner |
|---|---|
| Intelligent decision | Codex supervisor |
| Deterministic execution | Program code |
| Independent judgement of the result | Reviewer |
| Final acceptance | Human |

The program does not decide what a video should say. A language model does not
report that a deterministic step succeeded; the step reports that itself, and
the claim is verified against artifacts.

## How this appears in code

Authority is expressed as refusal, not as documentation:

- `gold_manifest.assert_not_promoted` refuses to let automated writeback declare
  a `FROZEN` Gold. Promotion is an upper-review decision.
- `review.Review` refuses a review whose `reviewer_id` equals its `executor_id`.
  A component may not review its own output.
- `typography.assert_placement_implemented` and
  `executable_timeline.compile_for_backend` raise rather than return a
  plausible-looking result for work that does not exist yet.

Each of these turns a governance rule into something a test can fail on.
