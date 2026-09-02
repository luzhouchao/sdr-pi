# Iteration workflow

All new AGX Agent, SDR Linux control-plane and recognizer work is tracked in
this repository. Raspberry Pi releases remain rollback evidence; FPGA work is
retired.

## Branch and commit rules

1. Start from `main` and create a focused branch such as
   `agent/session-recovery`, `sdr/iiod-throughput`, or
   `recognizer/cuda-adapter`.
2. Keep commits small and evidence-based: source change, test, then result
   documentation.
3. Do not mix Agent runtime, SDR control-plane and recognizer changes in one
   unreviewable commit.
4. Update the relevant README, test result, version route, and rollback note in
   the same branch.

## Required evidence

Raspberry Pi/Rust changes:

- formatting and unit-test result;
- target architecture and SHA-256;
- hardware probe/capture result when applicable;
- final SDR configuration readback.

SDR-system changes:

- pre-change snapshot;
- exact changed files/sysctls/process arguments;
- throughput, errors, CPU, temperature, and IIO health before/after;
- rollback procedure.

Recognizer changes:

- exact model package, labels, preprocessing and SHA-256;
- numerical comparison with the training reference;
- latency, GPU memory, RSS, drops and thermal measurements;
- accuracy, per-class recall and open-set behavior before enabling capability.

## Binary artifacts

Generated binaries, model weights, capture data and deployment staging do not
belong in Git history. After all gates pass, publish distributable artifacts
through a versioned release or model store with hashes and a link to the exact
source commit.
