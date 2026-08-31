# C++ local recognizer worker

This directory contains the model-backend layer for the future persistent local
recognizer process. It is intentionally separate from the Rust Controller and
currently has no ONNX Runtime, ncnn, socket or JSON dependency.

The `Backend` interface accepts non-owning planar I/Q spans and returns a
bounded classification. `ReplayBackend` makes input/output validation testable
before a production model is selected. The interface pins model identity,
input shape, sample rate and thread count so switching inference runtimes does
not silently change the signal contract.

Run the dependency-free native check in WSL:

```bash
make test
```

The next layer will map the Rust JSONL contract onto this interface. The
planned parser is yyjson 0.12.0, pinned to official tag commit
`7871d321ff4cd8068c1f777c97975dc2fb640ab3` under its MIT license. Do not fetch
an unpinned branch during production builds.

No worker binary or model from this directory is deployed on the Pi yet.
