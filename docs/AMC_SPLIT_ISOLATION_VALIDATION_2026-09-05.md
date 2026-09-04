# AMC split isolation validation — 2026-09-05

## Outcome

The Chapter 5 split-isolation gate is complete for the retained RML2018A and
HisarMod2019 assets and the current application-owned P201 receive corpus. All
3,335,904 offline source rows occur exactly once across train, validation and
test. Every split is internally unique and in range, each three-way union is
complete, and all six pairwise intersection counts are zero.

The current P201 store contains one fully asset-verified
`receive_domain/unknown` row and zero train/validation/test rows. It therefore
does not contribute to labeled accuracy. The cross-package auditor rejects a
future collision by `source_sample_id`, `capture_session_id` or UTC
`capture_day`, rejects a derived crop/augmentation that changes any parent
lineage key, and rejects an unknown P201 row placed in an accuracy split.

This was an offline, read-only audit. It did not train or fine-tune a model,
change a checkpoint, capture RF, use N210/B210, transmit, or use FPGA state.
The compact machine-readable evidence is
[`AMC_SPLIT_ISOLATION_AUDIT_2026-09-05.json`](AMC_SPLIT_ISOLATION_AUDIT_2026-09-05.json).
It is 5,222 bytes with SHA-256
`1266bb64cec6e88aec18c663cf2299cb0ac81ca4f7bf150668f70501cee8a01a`.

## Auditable source boundary

Neither retained HDF5 container exposes an upstream generator parent ID. The
strongest identity that can be reproduced from the delivered assets is one
immutable `/X` global row, named by:

```text
<dataset-id>-<full-dataset-sha256>-X-row-<10-digit-global-row>
```

The full container SHA-256, HDF5 path and global row are all part of the
identity; a row number alone is not. Any later crop, augmentation or other
derived view must point to its parent record and inherit this exact
`source_sample_id`. For independently annotated P201 data, repeated receptions
of one scheduled waveform item must share its source ID, all windows in one
capture retain the same session ID, and all evaluation captures on one UTC day
retain the same split.

Both retained training configs declare a 1,024-sample sequence, matching one
complete HDF5 `/X` row. Denoising, IQ augmentation, time masking, signal
synthesis, low-SNR view consistency and low-SNR VC regularization are all
disabled. Thus the retained seed44/seed43 baselines contain no declared crop or
augmented training views that need retroactive grouping. This statement is
about the delivered configs and assets; the source HDF5 files cannot establish
an unavailable latent generator identity beyond their rows.

## Full offline result

The audit first verified the exact asset-manifest sizes and SHA-256 values,
then inspected HDF5 keys/shapes without loading a model. It required the exact
NPZ key set and metadata, one-dimensional sorted `int64` membership arrays,
in-range unique rows, no occupied assignment slot, and a fully occupied union.

| Dataset | Train | Validation | Test | Union / expected | Missing | Pairwise intersections |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RML2018A seed44 | 1,789,132 | 383,385 | 383,387 | 2,555,904 / 2,555,904 | 0 | 0 / 0 / 0 |
| HisarMod2019 seed43 | 546,000 | 117,000 | 117,000 | 780,000 / 780,000 | 0 | 0 / 0 / 0 |

Assignment vectors use `train=1`, `validation=2`, `test=3` at each global row.
Their reproducibility hashes are:

```text
RML assignment:          84daf0686196c3a0ed04c4d62eb4e5290fabc9f6574676fe8240eddc2f6624ea
RML lineage assignment:  f61e2648fad39004fc526684584403717a03624a1617aa3b66d930527339acf6
Hisar assignment:        daa2ef3eaebbb96c2c058ed7d5a236eccd8919197bf61776eded495c7f1afd3f
Hisar lineage assignment: 9118519fad2b0bab890072927e7ea125c54639e145b7eb5bc8dd5c00dfed6d8a
```

The full read verified these existing bulk assets again:

```text
RML2018A HDF5, 21,449,148,312 bytes
e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38

HisarMod2019 HDF5, 6,399,126,728 bytes
b4b2d2dcde17691b09e3d6b1aa91a9fbadd096980d5103a47af18f93ae1b596f

RML split, 3,906,249 bytes
5b8ccdc0183455445d5beab20f2ed7e553ff616da76a31114f700929607d0792

Hisar split, 1,193,298 bytes
fd79c0ba607b3504180fc0fe4d3cf2bbc367f0a2d4f3cf86691b04d33e518b0a
```

## P201 corpus result

The auditor used the existing v1 contract validator with full package asset
hashing, then merged lineage across all package directories. The stable package
snapshot contained:

```text
package / record count:          1 / 1
split:                           receive_domain
provenance:                      unknown / no_independent_label
evaluation record count:         0
unknown P201 evaluation records: 0
source/session/day collisions:   0 / 0 / 0
manifest SHA-256:                174df3a32cb05304979233cf0eb577a6032011c657fc9ce8cea24c5397851b83
record-index SHA-256:            541c40067da5d705a5a8e4e4df02f6fd0074d37f1881c0b0925f28227910604b
```

The user-visible retained IQ result was read and hashed through its manifest;
it was not copied, rewritten or deleted.

## Reproduction and negative gates

The final full audit ran in the existing AMC venv:

```bash
local-assets/amc-eval/runtime/venv/bin/python \
  jetson-agx/sdrharness/scripts/audit-amc-split-isolation.py \
  --verify-dataset-hashes \
  --output /var/tmp/sdrharness-dev/amc-split-isolation-20260905/final-audit-v2.json
```

It completed in 37.0 seconds with `status=pass`. The temporary 10,351-byte
result SHA-256 was:

```text
c9883dc13f005eafacc94088a7af8b42f00662a328c5ed20c83a10695aaa9b05
```

Thirteen focused tests cover the valid complete partition and valid inherited
derivative plus these failure cases:

- duplicate row inside one split;
- one row crossing splits;
- missing and out-of-range rows;
- source-sample, capture-session and capture-day collisions independently;
- a crop changing its parent's source identity;
- an unknown P201 row entering test;
- a parent-lineage cycle.

The 13 focused tests and the existing 9 corpus-contract plus 3 Mamba Worker
tests passed together, 25/25, in the AMC venv. The implementation hashes at
validation time were:

```text
auditor  f575c3458a1faa03d962088e229456d2655b3f53461b0bca3eff785e4b595870
tests    f2299a9d377a4cebbddfda20e1b5f661eebf0efe486a9cee43b56cf68363e55a
```

## Cleanup and next boundary

All development output was confined to the 44,295-byte feature directory:

```text
/var/tmp/sdrharness-dev/amc-split-isolation-20260905/
```

That exact temporary directory was removed after its summary and hashes were
recorded, and its absence was verified. The application-owned P201 result and
all ignored datasets, splits, checkpoints and runtime files remain intact.

The next Chapter 5 gate is still open: use only train/validation plus versioned
receive-domain evidence to select and freeze `rf_preprocess_v1`, calibration
and acceptance thresholds before consulting the held-out test. This audit does
not admit seed44 as a production checkpoint or enable `recognizer_available`.
