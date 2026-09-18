---
project_id: ai-autocut
authoritative_entry: project knowledge base entry (external; not stored in this repository)
repository_or_workspace: canonical checkout of ai-autocut (machine-local path, resolved from AUTOCUT_WORKSPACE)
canonical_repo: ai-autocut
runtime_data_root_role: AUTOCUT_WORKSPACE
media_root_role: AUTOCUT_MEDIA_ROOT
relationship_to_other_projects:
  adflow: separate_project
  openmontage: third_party_reference_and_capability_candidate
  kang-agent-collab: independent_skill_with_ai-autocut_as_pilot_testbed
  legacy_rd_workspace: read_only_evidence_source
status: verified
confirmed_by: Kang
last_verified: 2026-09-18
---

# Project Identity

AI-AutoCut is the canonical engineering repository for the AI automatic precision-editing system.

It is not AdFlow and does not share AdFlow's engineering identity. It is not OpenMontage and does not treat OpenMontage as its source of truth. It may be used as a Pilot Testbed for `kang-agent-collab`, while AI-AutoCut remains an independent real project and `kang-agent-collab` remains an independent collaboration Skill.

Historical R&D work lives in a separate legacy workspace that is a **read-only evidence source**. It does not carry canonical Git history for this product.

## Machine independence

This repository contains no machine-bound absolute path. Every runtime location is a logical role resolved from an environment variable — `AUTOCUT_WORKSPACE`, `AUTOCUT_MEDIA_ROOT`, `AUTOCUT_LEGACY_WORKSPACE`, `AUTOCUT_ASCII_STAGING`, `DAVINCI_PATH`, `JIANYING_PATH`. See `docs/architecture/operations.md` and `src/ai_autocut/paths.py`.

Media never enters this repository. Assets are referenced by logical role, bare filename, and SHA-256.

## Stage history

A narrowly reviewed Frame Boundary Kernel and sanitized regression evidence were inherited with explicit provenance. Other historical editing assets remain outside this repository.

The First Real Multi-Agent Engineering Pilot completed through separate Agent A and Agent B engineering commits and was closed out in commit `9580ba597430f9329fcbdb348843815df31d82d6` (`docs: close first multi-agent pilot state`). Its 45 offline tests passed on 2026-09-13. Material / Candidate Identity v1 was implemented afterward as ordinary product engineering, with exact-byte Material IDs, deterministic frame-range Candidate IDs, a path-free catalog, and an upstream binding into the unchanged Boundary Preflight v1 contract.

Editing Plan v1 was introduced in commit `1ec1c3ad8be59d82ade70b0ad3d08a3bf394b697` (`feat: add editing plan v1`), which added the contract, the implementation, and its tests together. That commit is the freeze point for the contract, not the repository HEAD: HEAD is later, and it is.

## Current stage

**Gated production control path — frozen pre-exam baseline.**

The repository holds a working eight-stage production control path, its contracts and policies, and an offline regression suite. It is not a pre-pipeline knowledge base: a complete gated chain runs and has produced a real, independently verified delivery master.

The frozen baseline is the annotated tag `pre-third-sku-blind-v1`, targeting commit `b65a73b53040bd1ff5defe25e624a28f623b6847`. Gate G.0 is `CLOSED_AND_FROZEN` and its exam validity is `PASS_WITH_EXPLICIT_PRODUCER_GATES`. The Third-SKU blind exam **has not started** at this baseline.

Because the system is gated, a run may stop and name a producer — a Codex/Supervisor, a job-scoped adapter, or a human — instead of proceeding. That is the designed behaviour, not a defect: the alternative is inventing a creative decision or claiming work that was not done. `README.md` states which capabilities are automatic and which remain job-authored.

Product and video quality were **NOT EVALUATED** by this repository's own engineering work; creative and content acceptance remains a human gate. The execution proof verifies technical properties — decoding, frame count, geometry, black frames, freezes, loudness, true peak, and master integrity — and does not by itself establish that a video is good.

The Gold result recorded in `schemas/gold_manifest/filter-gold-v1.json` carries status `RECONCILED`; the canonical visual source and selected master have verified long-term logical locations below `AUTOCUT_MEDIA_ROOT`.

Still absent, and not claimed: an unattended one-command runner, an automated commercial reviewer, generic backend compilers, an artifact registry, and a job queue. Several capabilities are reachable but consume artifacts authored per job; `docs/audit/production-chain-manifest.md` records each one and its readiness.
