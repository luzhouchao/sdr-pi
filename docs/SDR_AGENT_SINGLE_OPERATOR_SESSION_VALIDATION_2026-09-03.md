# SDR Agent single-operator session validation — 2026-09-03

## Decision and scope

The operator explicitly fixed this deployment to one trusted human user. The
two bounded Web conversations are switchable histories for that same person;
they are not user identities or independent authorization domains. Supporting
multiple concurrent interactive users is therefore not a project requirement.

The enforced runtime contract is:

- one active interactive Controller connection to `session.sock`;
- one global inference lease shared with the one-shot Planner path;
- one global receive owner, independently enforced by the Controller and
  `sdrd` ownership gates;
- at most two stored Web conversation histories for the same operator;
- no command, approval or stop dispatch through an inactive Web conversation.

The trusted-LAN Web service still has no application authentication and must
not be exposed to the Internet. This validation does not claim multi-user
privacy or authorization support.

## Rejected multi-user prototype rollback

A not-yet-committed prototype briefly allowed multiple Planner session sockets
and added per-user terminal identifiers. It was rejected after the operator
clarified the single-user requirement. All five prototype source/test changes
were removed before this delivery.

The Web service was already stopped. The retained pre-prototype release was
restored directly, without rebuilding:

```text
/home/jetson/.local/lib/sdrharness/bin/sdr-agent
SHA-256 6f506e4e95ac358cebabd1928f8bd8d689655e20ed85ca0be82b7fad4429c8e7

/home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console
SHA-256 c2393185e1fba028f08029f3d1bf1a25cf36bc2de8f9157546637333b4e985a0

retained binary rollback release
/home/jetson/.local/lib/sdrharness/releases/20260903-pre-multi-session-v1/
```

`sdrharness-planner.service` was restarted so its Node process loaded the
single-connection `session-server.mjs`; `sdrharness-web.service` was then
started with the restored binaries. No result database, saved capture or user
conversation was deleted.

## Automated verification

`planner-worker/test/single-session-server.test.mjs` opens one owner socket and
then proves that a second socket receives `interactive session is busy`. The
existing Planner suite also proves that one-shot and interactive requests share
one inference lease.

```text
npm test
50 tests: 50 passed, 0 failed
```

## Deployed runtime verification

With the Web Controller already connected to `/run/sdr-agent/session.sock`, a
second local connection returned this fail-closed response without sending a
command:

```json
{"protocol_version":1,"command_id":0,"session_generation":0,"type":"response","command":"unknown","success":false,"error":"interactive session is busy"}
```

The deployed Web state contained two histories owned by the same operator:

```text
active conversation:   session-1788263597140, connected, generation 21
inactive conversation: session-1788261263788, stored, generation 8
```

Posting `{"command":"/stop"}` to the inactive conversation returned HTTP
`409`; it did not reach the Controller. The process tree contained exactly one
Web-owned Controller child:

```text
/home/jetson/.local/lib/sdrharness/bin/sdr-agent
  --socket /run/sdr-agent/session.sock
  --request /var/lib/sdrharness/web-console/runtime-request.json
  --session-state off
  --sdrd 192.168.1.10:43110
  --survey-gain-db 20
```

Both `sdrharness-planner.service` and `sdrharness-web.service` were active after
the rollback. Port `8787` listened on the configured trusted-LAN address and
`GET /api/state` returned HTTP 200.

This test performed no approval, retune, IQ acquisition, result mutation or
radio-state change.

## Delivery cleanup

The rejected prototype's two exact development directories and both Cargo
build-output directories were removed after validation:

```text
/var/tmp/sdrharness-dev/msi-0903/                         536 KiB
/var/tmp/sdrharness-dev/multi-session-isolation-20260903/ 20 KiB
raspberry-pi/sdr-agent/controller/target/                 367 MiB
raspberry-pi/sdr-agent/web-console/target/                719 MiB
```

All four paths were verified absent. Planner `node_modules`, model files,
runtime state, user-visible Web results and P201 data were retained.
