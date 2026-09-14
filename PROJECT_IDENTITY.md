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
last_verified: 2026-09-14
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

The First Real Multi-Agent Engineering Pilot completed through separate Agent A and Agent B engineering commits, ending at implementation HEAD `the First Real Multi-Agent Engineering Pilot completion commit in canonical historyd8723b41d2f332549f652f502bb3402c8`. Its 45 offline tests passed on 2026-09-13. Material / Candidate Identity v1 was implemented afterward as ordinary product engineering, with exact-byte Material IDs, deterministic frame-range Candidate IDs, a path-free catalog, and an upstream binding into the unchanged Boundary Preflight v1 contract.

## Current stage

**Gold Knowledge Baseline / Pre-Pipeline.**

Editing Plan v1 is frozen at commit `the Editing Plan v1 freeze commit in canonical historye8d86ce0c4549bb1dc9f63b0ace3ffb56`. That commit is the freeze point, not the repository HEAD: HEAD may be later, and it is. Gold Consolidation Phase 2 added the Gold record, the path-sanitization contract, the backend-neutral Executable Timeline contract, and the typography, audio, and review policies described in `docs/`.

Product and video quality were **NOT EVALUATED** by this repository's own engineering work. The Gold result recorded in `schemas/gold_manifest/filter-gold-v1.json` carries status `RECONCILED`; the canonical visual source and selected master have verified long-term logical locations below `AUTOCUT_MEDIA_ROOT`. No repository freeze has been declared, and declaring one is an upper-review decision.

The end-to-end production pipeline — automatic raw-media Shot Intelligence, a stage runner, resume/retry, an artifact registry, a job queue, and a one-command runner — is **NOT_IMPLEMENTED**.
