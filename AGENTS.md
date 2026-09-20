# AI-AutoCut Agent Entry

Before acting in this repository:

1. Confirm the project identity in `PROJECT_IDENTITY.md`.
2. Read the current task Manifest and Handoff when the task provides them.
3. Check the repository root, branch, HEAD, staged, unstaged, and untracked state.
4. Do not guess ownership of unknown files or changes. Never stash, reset, clean, discard, overwrite, move, or commit them to make the tree look clean.
5. Treat capability as evidence, not permission. Stay within the current task's allowed scope and write paths.
6. Keep large media, generated outputs, renders, previews, caches, local environments, model weights, credentials, and secrets out of Git.
7. Keep real secret values out of replies, code, documentation, logs, examples, and commits.
8. Do not equate engineering completion with video content or creative quality completion; Kang's review remains a separate gate.
9. For cross-Agent takeover, follow the installed `kang-agent-collab` Skill's own `SKILL.md` and its referenced `references/contracts.md`, resolved from the local skill root outside this repository. Do not copy or extend that Skill inside this repository.
10. Never commit a machine-bound absolute path. Every runtime location is a logical role resolved from an environment variable; see `docs/architecture/operations.md` and `src/ai_autocut/paths.py`. The offline test suite enforces this.
11. Never choose where heavy production media is written. Frames, proxies, previews, intermediate renders, temporary audio and working media belong in the job workspace the production system resolves — never in the internal temporary directory, a home folder, or a desktop folder. That workspace is `<AUTOCUT_PRODUCTION_ROOT>/AI-AutoCut-Staging/<job-id>/`, and `AUTOCUT_PRODUCTION_ROOT` is the only location you need to know. Ask the storage contract rather than recalling a path:
    ```
    python3 -m src.ai_autocut.storage_contract --job-id JOB_ID --print-workspace
    ```
    If it exits `3`, production storage is **blocked**. Say so, and tell the Producer the external production volume must be connected. Do not fall back to the internal disk, and do not authorize yourself: only the Producer may permit internal production, for one named job, through `AUTOCUT_INTERNAL_PRODUCTION_JOB`. See `docs/architecture/operations.md` and `src/ai_autocut/storage_contract.py`. This rule is identical for every Agent; it is not a Codex, Work, or DSH convention.
12. A finished job does not keep its regenerable intermediates forever, and it does not lose its authoritative ones. Archive the Final Master, brief, approved copy, manifest, Production Record and integrity record; prune regenerable intermediates only once the job is `CLOSED`. Classification is by production role, never by file extension. See `src/ai_autocut/artifact_lifecycle.py`.

AI-AutoCut is separate from AdFlow and OpenMontage. Do not import either project's identity or files without an explicitly approved review and task scope.
