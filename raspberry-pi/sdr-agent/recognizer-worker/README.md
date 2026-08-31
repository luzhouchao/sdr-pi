# C++ local recognizer worker

This directory contains the model-backend layer for the future persistent local
recognizer process. It is intentionally separate from the Rust Controller and
currently has no ONNX Runtime, ncnn, socket or JSON dependency.

The `Backend` interface accepts non-owning planar I/Q spans and returns a
bounded classification. `ReplayBackend` makes input/output validation testable
before a production model is selected. The interface pins model identity,
input shape, sample rate and thread count so switching inference runtimes does
not silently change the signal contract.

`ModelPackageLoader` is now the model-admission seam. The filesystem Adapter
parses a strict version-one manifest, contains every artifact to one canonical
package directory, rejects symlinks and traversal, caps the ONNX file at
32 MiB, streams SHA-256 verification, validates unique labels and fixes the
input/preprocessing/thread contract. The replay Adapter exercises callers
without a filesystem package. `sdr-model-inspect` exposes this validation for
future deployment checks but does not initialize ONNX Runtime or classify IQ.

Run the dependency-free native check in WSL:

```bash
make test
```

Inspect a completed package before installing it:

```bash
./build/sdr-model-inspect /path/to/package model.manifest
```

The next layer will map the Rust JSONL contract onto this interface. The
planned parser is yyjson 0.12.0, pinned to official tag commit
`7871d321ff4cd8068c1f777c97975dc2fb640ab3` under its MIT license. Do not fetch
an unpinned branch during production builds.

No inference worker, runtime library or model from this directory is deployed
on the Pi yet. A successfully inspected package must not set
`recognizer_available=true`; that gate opens only after runtime, numerical,
accuracy, resource and thermal validation.
