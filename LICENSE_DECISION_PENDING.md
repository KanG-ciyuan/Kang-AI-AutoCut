# LICENSE — Apache-2.0, Applied

```
selected_license: Apache-2.0
status:           APPLIED
license_file:     LICENSE   (repository root, applied in this commit)
```

## What is now true

**AI-AutoCut is licensed under the Apache License, Version 2.0.**

The full, unmodified Apache License 2.0 text is at [`LICENSE`](LICENSE) in the
repository root. This is how Apache recommends the licence be applied: shipping
the complete licence text with the distribution, without waiting for the
repository to be published anywhere.

The `LICENSE` file is the official text verbatim, including the `APPENDIX: How to
apply the Apache License to your work` section. Its `Copyright [yyyy] [name of
copyright owner]` placeholder is deliberately **left unmodified** — it is part
of the official text, and filling it in would make the file no longer verbatim.
A project-specific copyright notice belongs in a separate file if one is wanted.

## No NOTICE file

No top-level `NOTICE` or `THIRD_PARTY_NOTICES` file is added.

Apache-2.0 section 4(d) governs the propagation of a `NOTICE` file **that the
distributed work itself carries**. Nothing is copied or vendored into this
repository, so there is no upstream `NOTICE` to propagate and none is required.

`docs/notices/third-party.md` continues to serve as the dependency-boundary
record.

## Future obligation

If upstream MCP servers, libraries, or any other third-party files are ever
**actually included** in a distribution of this work, that decision must be
revisited: the relevant licences must be re-checked and a top-level `NOTICE` or
third-party notice file added as those licences require.

The `Bradford Operations LLC` attribution obligation for
`samuelgursky/davinci-resolve-mcp` is recorded in `docs/notices/third-party.md`
for exactly that moment. It applies to distributing that project, not to
licensing this repository, which is why it does not appear in a `NOTICE` here
today.

## Why Apache-2.0 is compatible with the current boundaries

1. **No third-party code was copied.** This work referenced upstream projects
   without vendoring them, so no upstream licence propagates into these files.
2. **The upstream licences are compatible.** The referenced projects are MIT
   (`jianying-editor-skill`, `2sem/davinci-resolve-lite-mcp`,
   `samuelgursky/davinci-resolve-mcp`) and Apache-2.0 (the vendored
   `pyJianYingDraft` inside `jianying-editor-skill`). Both are permissive and
   compatible with an Apache-2.0 project.
3. **The attribution obligation does not constrain the choice.** It is an
   upstream notice-retention duty that survives whatever licence is chosen here.

## Still open for a later stage

1. **Copyright holder statement.** The official text carries the placeholder.
   A project-specific copyright line has not been added, deliberately.
2. **Editor integrations.** DaVinci Resolve and Jianying are proprietary,
   separately licensed applications. This licence grants no rights to them.
3. **Generated media.** Source footage, product material, and generated audio are
   not in this repository and are not covered by this licence.

## History

An earlier revision of this file recorded the decision as made but **not yet
applied**, because the commit stage had not been authorized and no `LICENSE` file
existed. That state is closed: the file now exists and the licence is applied.
