# Filter Gold v1

The validated Gold result inherited by this repository. The machine-readable
record is `schemas/gold_manifest/filter-gold-v1.json`; this document explains it.

## Status

```
PASS_WITH_RECONCILIATION_REQUIRED
```

The split matters:

| Dimension | State |
|---|---|
| Creative / review | **PASS / FREEZE / COMPLETED** |
| Media production | **COMPLETED AND VERIFIED** |
| Canonical Gold manifest | **missing before Phase 2** — written now |
| Canonical external asset references | **not fully closed** — see below |
| Canonical repository writeback | **not completed before Phase 2** — written now |
| Long-term Gold media storage | **NOT YET RECONCILED** |

**What reconciliation actually means here.** The creative work is finished and
the media is produced and verified. Reconciliation is outstanding for exactly one
reason: the verified media has not yet been placed in the **long-term Gold media
root**. `MASTER-A` exists right now, but it still lives where it was produced
rather than at its permanent address.

It is **not** open because "the media is not in Git". Large media should never be
in Git — that is a standing repository boundary, and it will still be true after
reconciliation is complete. Conflating the two would make a permanent design
decision look like an outstanding defect.

The future target structure is:

```
$AUTOCUT_MEDIA_ROOT/gold/filter-gold-v1/
    visual/
    audio/
    master/
    evidence/
```

with the selected master at
`$AUTOCUT_MEDIA_ROOT/gold/filter-gold-v1/master/FILTER-V4-FINAL-MASTER-A.mp4`.

None of those directories exists yet. This phase copied nothing, moved nothing,
and created no media directory, because doing so is outside its scope.

This manifest does **not** declare a repository freeze — that is an upper-review
decision.

## Final timeline

| Property | Value |
|---|---|
| Frames | 518 |
| Frame rate | 30 fps |
| Duration | 17.266667 s |
| Resolution | 1080 × 1920 |

Lineage, reconstructed and cross-checked against the stage reports:

```
Resolve main                   443 frames
  + CTA hold, 97 frames    ->  540 frames / 18.000 s
  upper review: 97 -> 75        (hold reduced)
  = 443 + 75               ->  518 frames / 17.266667 s
```

The 540-frame state was a valid intermediate, not the final spine. The reduction
to 518 came from an explicit upper-review decision.

## Authorities

| Role | Artifact | SHA-256 |
|---|---|---|
| Final frozen visual source | `TYPO-P3-B.mp4` | `eec4730b…b08c7cdf65` |
| Selected final master | `FILTER-V4-FINAL-MASTER-A.mp4` | `2d481ef1…1b56ee7ac8` |

`TYPO-P3-B.mp4` is video-only: the frozen picture carries **no audio track**. The
selected master is the artifact that carries both the frozen picture and the
mastered audio.

`FILTER-V4-FINAL-MASTER-B.mp4` is **REJECTED AS FINAL** and is retained as an
A/B reference. It must not be migrated or deleted.

## Voice-over

Three lines, at final authority:

1. `Bikin aktivitas di wastafel jadi lebih praktis.`
2. `Mau bilas dari arah mana, tinggal kamu sesuaikan.`
3. `Sebelum beli, pastikan ukurannya cocok dengan ujung keranmu.`

**Provenance note.** An earlier four-line script was locked during the Audio
Prototype stage, marked "do not rewrite". It belonged to that stage only and is
superseded by the three-line final authority, produced through the later
production chain. The distinction is recorded rather than silently dropped,
because the superseded script is still present in the historical workspace and
would otherwise look like the authoritative copy.

## Editorial text

| Role | Lines |
|---|---|
| Hook | `FILTER KERAN` |
| Feature | `ARAH AIR` / `BISA DIATUR` |
| CTA | `COCOK BUAT KERANMU?` / `CEK UKURAN` / `UJUNG KERAN DULU` |

Text is editorial emphasis, not voice-over subtitles — see
`docs/policies/typography.md`.

## Loudness

| | Value |
|---|---|
| Reference target | ≈ −16 LUFS, ≈ −1.4 dBTP |
| Measured on the delivered MP4 | ≈ −16.1 LUFS, −1.4 dBTP |

Measured after AAC encoding, on the delivered file. This is a **Gold reference,
not a universal law** — see `docs/policies/audio-intelligence.md`.

## Asset reconciliation

Each asset is recorded as a logical role, a bare filename, a SHA-256, and a
storage class. Three assets are recorded, and all three hashes were verified
against the located files while writing this record:

| Logical role | Filename | Storage class |
|---|---|---|
| `final_visual_source` | `TYPO-P3-B.mp4` | external workspace |
| `final_master` | `FILTER-V4-FINAL-MASTER-A.mp4` | local runtime |
| `ab_reference_master` | `FILTER-V4-FINAL-MASTER-B.mp4` | local runtime |

Every asset is `EXTERNAL_ASSET_VERIFIED`: the recorded hash matches the located
bytes. That is a statement about **identity**, and it is already closed.

What is still open is **placement**. Each asset currently sits in the working
location where it was produced rather than under the long-term Gold media root
described above. Identity is proven; the permanent address is not yet assigned.

Absolute locations are deliberately absent from the record. They resolve from
`AUTOCUT_MEDIA_ROOT` and `AUTOCUT_WORKSPACE` — see
`docs/architecture/operations.md`.

Reconciliation is therefore a **media-placement task for a later authorized
stage**, not a knowledge gap. The knowledge is written back; the bytes still need
a permanent home.

## What this Gold established

- A Resolve-driven automated visual pipeline reaches a validated, frozen picture.
- Conservative color matching protects product identity at a measured cost in
  background convergence.
- Shot-aware typography survives professional review as a policy.
- A continuous voice-over performance solves speaker consistency.
- Audio repair can be provably contained to one line.
- Every one of these was verified against decoded pixels or measured audio, not
  against an API's success flag.

## What this Gold did not establish

It is a single product, a single language, a single platform, at a single
duration. Generalization to other product categories was explicitly **not**
validated. Automatic raw-media Shot Intelligence was not built. No end-to-end
pipeline ran unattended.
