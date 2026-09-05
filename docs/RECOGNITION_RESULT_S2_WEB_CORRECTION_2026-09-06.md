# S2 Web dependent-build correction — 2026-09-06

V1a's initial Web build exposed an omitted S2 dependent consumer: the Web
persisted-observation validator still accessed the removed `label/confidence`
fields. S2's Controller/Node tests passed, but did not build the dependent Web
crate. This was a source build regression, not an installed-service incident.

The Web validator now calls the shared S2 observation validator and requires a
current candidate reference. Persisted history may be old; this structural check
does not refresh its timestamp or grant a new generation. Runtime Controller and
Planner freshness checks still apply before planning. The regression test covers
valid unavailable history, an uncalibrated classified forgery, and a missing
candidate. No rendering, Runner, admission or V1a change is included here.

A detached checkout of `8bf6ad0` plus only this correction passed all 20 Web tests
and all-target Clippy with warnings denied. Formatting and diff checks passed.
The temporary checkout and its dedicated target tree under
`/var/tmp/sdrharness-dev/v1a-906a/s2-fix` and `s2-target` were removed; the exact
S2 patch/test-log staging files were also removed. No IQ capture, service
replacement, user result deletion or capability change occurred. V1a's separate
unfinished source and temporary root remain outside this S2 cleanup boundary.

Test log SHA-256 before cleanup:

- `s2-web-tests.log`: `fd17a3e49e0e4a8dc99d866743322bb3284c7ee27c18dc1e7c40fd191fbdd787`
- `s2-clippy.log`: `6a1047c59d0ad0a737450d21d3b0e32bd644d995401f55837fc83477b5113783`
