# Web UI verification

Run the dependency-free state regressions with Node.js:

```sh
node raspberry-pi/sdr-agent/web-console/tests/ui-state.test.cjs
```

The suite executes production functions with controlled HTTP promises. It covers
late state/detail replies, cross-session input acknowledgement, priority stop,
UTF-8 limits, unsaved navigation, partial startup failure, invalid JSON and
coalesced SSE refresh under slow responses.

For browser checks, use a new canonical directory directly below
`/var/tmp/sdrharness-dev/`:

```sh
python3 -B raspberry-pi/sdr-agent/web-console/tests/preview_server.py \
  --root /var/tmp/sdrharness-dev/your-unique-feature-id --port 8798
```

The listener defaults to loopback. An explicitly selected LAN interface may be
passed with `--listen` for remote browser verification. The server copies the
three current public assets into the feature directory. Restart it to copy later
edits. It appends a visibly labelled scenario selector; production assets never
load that selector.

All API operations use fixed, in-memory fixtures. There is no proxy, Controller,
Planner, socket, radio, model or real-result access. Provider discovery returns
synthetic model IDs; posted keys are discarded and omitted from the request log.
The response CSP allows connections only to the preview's own origin. This is
a UI fixture, not a backend-policy or RF integration test.

Check complete/streaming/approval/running/empty/error/disconnected/loading/late
states; session creation/cancel/switch; shortcut commands and Ctrl+Enter; settings
query/save/discard/unsaved navigation; archive detail/delete-cancel/delete-confirm;
keyboard details/dialog/escape/focus-return; desktop, laptop and narrow layouts.
Judge readiness by HTTP responses and rendered controls, never `networkidle`
with a persistent SSE connection.

Stop this process and delete only its verified feature directory after recording
the minimal needed screenshots/test receipts. Do not point tests at production,
create production sessions or delete user results to verify the UI.
