# C++ local recognizer worker

This directory contains the model-backend seam for the future persistent AGX
recognizer process. It is intentionally separate from the Rust Controller and
currently has no model runtime, socket or JSON dependency.

The `Backend` interface accepts non-owning planar I/Q spans and returns a
bounded classification. `ReplayBackend` makes input/output validation testable
before a production model is selected. The interface pins model identity,
input shape, sample rate and thread count so switching inference runtimes does
not silently change the signal contract.

`ModelPackageLoader` is the existing model-admission seam. Its version-one
filesystem Adapter validates one legacy ONNX-shaped package with canonical
paths, size and SHA-256 checks, unique labels and a fixed input contract. The
future CUDA/Mamba package format may replace those model-specific manifest
fields while preserving the backend-neutral Controller interface. The replay
Adapter exercises callers without a filesystem package. `sdr-model-inspect`
validates a package but does not initialize a runtime or classify IQ.

Run the dependency-free native check on AGX or another C++20 development host:

```bash
make test
```

Inspect a completed package before installing it:

```bash
./build/sdr-model-inspect /path/to/package model.manifest
```

No production inference worker, runtime library or model from this directory is
deployed on AGX yet. A successfully inspected package must not set
`recognizer_available=true`; that gate opens only after runtime, numerical,
accuracy, resource and thermal validation.
