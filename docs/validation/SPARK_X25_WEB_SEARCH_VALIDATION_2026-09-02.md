# Spark-X2.5 bounded web-search validation — 2026-09-02

## Delivered path

The AGX Planner now reuses the previously installed local SearXNG service at
`127.0.0.1:8080` for the `spark-local` structured-output adapter. This is a
host-side evidence tool, not a capability of the Spark weights and not a new
Controller or SDR action.

The first constrained Spark response may be either:

- a final `submit_plan` payload; or
- one `web_search` text query for the host adapter.

For a search, the Planner calls the fixed `/search` endpoint, returns sanitized
public snippets to a second Spark inference turn, and converts only the final
plan into Pi Agent's existing `submit_plan` event. Search lifecycle events are
correlated to the active planning request. The Rust terminal validates them and
the Web Console renders the query and each source under `网络搜索`.

## Enforced boundaries

- The configured search service must be explicit loopback HTTP at `127.0.0.1`
  or `::1`; credentials, query strings and fragments in the configured URL are
  rejected.
- Spark supplies only a bounded text query. It cannot select an endpoint or
  directly fetch a result URL.
- Redirects are rejected. Responses are bounded to 512 KiB and valid UTF-8
  JSON. A turn may request at most two searches, each returning at most eight
  unique HTTP(S) sources.
- The deployed search timeout is 15 seconds. The overall Planner timeout is
  120 seconds so two model turns can complete without removing a bound.
- Titles, snippets, URLs and error text are length-bounded and stripped of
  control characters. Snippets are explicitly marked as untrusted evidence and
  cannot override the system prompt, PlanningContext, measured SDR data or
  hardware limits.
- Search failure is returned to Spark as a failure, never as invented results.
  The model must still submit a conservative final plan.
- Rust remains the only plan validator and execution authority. Search receives
  no Shell, filesystem, SSH, IIO, FPGA or SDR access.
- Other upstream providers retain their existing Pi Agent path; the adapter is
  enabled only for provider ID `spark-local`.

## Automated validation

The deployed source passed:

- Planner Worker: 47/47 Node tests, including local HTTP query encoding,
  sanitization, duplicate/unsafe URL rejection, 512 KiB response rejection,
  two-turn search-to-plan conversion, cumulative usage accounting, search
  failure handling and correlated session events.
- Controller: 44/44 library tests and 5/5 terminal tests, including bounded
  source-event validation and rejection of a non-HTTP(S) source URL.
- Web Console: 15/15 Rust tests, JavaScript syntax validation and release
  build/clippy checks.
- The local client queried SearXNG for `Apache Arrow official documentation`
  and returned three `https://arrow.apache.org` sources in 2.9 seconds.

## Live model and browser validation

All deployed services reported active:

- `spark-x25.service`, loopback `127.0.0.1:8010`;
- local SearXNG, loopback `127.0.0.1:8080`;
- `sdrharness-planner.service` and `sdrharness-web.service`, with the Web
  Console on the previously authorized LAN listener `0.0.0.0:8787`.

A real one-shot PlanningContext asked Spark to search the Apache Arrow official
site for the latest stable version and explicitly prohibited SDR work. Spark
requested web search, consumed the returned sources and submitted a correlated
`hold`. Rust accepted the plan; the visible answer identified 25.0.1 and the
2026-08-10 release date. No SDR action or approval gate was produced.

A second validation used headless Chromium against the deployed Web Console.
The terminal visibly showed:

1. the Spark-generated query;
2. eight source rows, including the Apache Arrow release page and GitHub
   releases;
3. the Rust-validated `hold` plan; and
4. the final answer in the upstream-model panel.

The browser reported no console errors. The temporary screenshot SHA-256 was
`49f31bd0f39441c009af831e009319fa8dfdf7c4d5743d1ebbb0b113dfe212f8`.
The screenshot and validation script were development artifacts and were
removed after recording this evidence.

## Deployed artifacts

- `sdr-agent` SHA-256:
  `cced8d1bd423eeb7c39de7f523800689f9edd029c42276eac6175b22b6f0bf51`
- `sdr-agent-web-console` SHA-256:
  `1670e90c4a151975658471a45a927d31c126f772a65b6d6e4216f8240b1693d3`
- `web-search.mjs` validation-source SHA-256:
  `cbb0931d9ba720ef3ecc4b298ddf7a6f31596029241b6a2a806a0ee6b6add57f`

The local search and Spark API keys, if any, were not printed, copied into this
document or committed.
