#!/usr/bin/env python3
"""Finite, offline CUDA payload benchmark; never loads a model or opens a radio."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import statistics
import subprocess
import time

import h5py
import numpy as np

import rml2018a_campaign as c
import rml2018a_campaign_gpu as g
from gpu_lease import GpuLease


def spark_stopped():
    state = subprocess.check_output(['systemctl', 'show', 'spark-x25.service',
        '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID'], text=True, timeout=5)
    c.require(set(state.splitlines()) == {'MainPID=0', 'ActiveState=inactive', 'SubState=dead'}, 'Spark must remain stopped')
    c.require(subprocess.run(['pgrep', '-x', 'llama-server'], capture_output=True).returncode == 1, 'llama-server present')
    return state.splitlines()


def timed(call, repeats=3):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter(); result = call(); samples.append(time.perf_counter()-start)
    return result, dict(seconds=samples, median_seconds=statistics.median(samples))


def quality_difference(expected, actual):
    maximum = 0.
    for a, b in zip(expected, actual):
        c.require(a.keys() == b.keys(), 'quality fields')
        for key in a:
            if key == 'rx_sinr_diagnostics':
                c.require((a[key] is None) == (b[key] is None), 'quality diagnostics status')
                if a[key] is not None:
                    c.require(a[key].keys() == b[key].keys(), 'quality diagnostic fields')
                    for name, value in a[key].items():
                        if value is None: c.require(b[key][name] is None, 'quality null diagnostic')
                        else: np.testing.assert_allclose(b[key][name], value, rtol=1e-10, atol=1e-10)
            elif key == 'rx_sinr_db' and a[key] is not None:
                maximum = max(maximum, abs(a[key]-b[key]))
            else:
                c.require(a[key] == b[key], 'quality status/reason/contract')
        c.validate_receive_quality(b, b['rx_sinr_diagnostics']['source_snr_db'] if b['rx_sinr_diagnostics'] else 30.)
    c.require(maximum <= 1e-9, 'quality SINR numerical agreement')
    return maximum


def run(root):
    c.require(root.is_absolute() and root.resolve() == root and root.parent == Path('/var/tmp/sdrharness-dev') and
              root.is_dir() and not (root/'benchmark-plan.json').exists(), 'new private benchmark root')
    c.require(shutil.disk_usage(root).free > 2*1024**3, 'benchmark disk reserve')
    scratch = root/'scratch'; scratch.mkdir(mode=0o700, exist_ok=True)
    os.environ.update(TMPDIR=str(scratch), CUDA_CACHE_PATH=str(scratch/'cuda'), XDG_CACHE_HOME=str(scratch))
    parents = [Path('/var/tmp/sdrharness-dev/b210-rml2018a-resident-live-'+x+'-20260913') for x in ('a', 'b')]
    plan = dict(schema='rml2018a-gpu-payload-benchmark-v1', batch_rows=[24, 1024, 4096, 8192], repeats=3,
        source_snr_db=30, unique_source_rows=8192, maximum_new_tx_seconds=0, maximum_new_rx_bytes=0,
        model_windows=0, maximum_seconds=600, maximum_temporary_output_bytes=67108992,
        expected_gpu_allocated_limit_bytes=4*1024**3, disk_reserve_bytes=2*1024**3,
        free_bytes=shutil.disk_usage(root).free, parents=[str(p) for p in parents],
        normalization_absolute_tolerance=1e-6, normalization_hash_equality_required_for_frozen_admission=True,
        sinr_absolute_tolerance_db=1e-9, diagnostic_tolerance=1e-10, status_reason_exact=True,
        stop='SIGINT/SIGTERM; 600 second alarm; no radio/model processes',
        scope='Payload normalization and crossfit SINR only. Excludes synchronization, guard correction, RF startup and inference.',
        rf_repetition='Repeat existing raw synchronized RF rows to fill benchmark batches; no additional independent RF evidence.',
        spark_before=spark_stopped(), created_ns=time.time_ns())
    c.save(root/'benchmark-plan.json', plan)
    def abort(sig, frame): raise RuntimeError(f'benchmark signal {sig}')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM): signal.signal(sig, abort)
    signal.alarm(600)
    report = dict(status='failed', plan_sha256=c.file_hash(root/'benchmark-plan.json'), results=[])
    lease = GpuLease(scratch/'gpu-gate', 'mamba'); token = None
    try:
        import rml2018a_campaign_events as e
        source = e.m.DATASET
        c.require(c.file_hash(source) == 'e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38', 'source SHA')
        ids = g.snr_rows(30, 0, 8192)
        start = time.perf_counter()
        with h5py.File(source, 'r') as f:
            # Two contiguous class segments avoid slow HDF5 point selection.
            iq = np.concatenate([f['X'][int(ids[k]):int(ids[k])+4096] for k in (0, 4096)])
            zs = np.concatenate([f['Z'][int(ids[k]):int(ids[k])+4096] for k in (0, 4096)])
            ys = np.concatenate([f['Y'][int(ids[k]):int(ids[k])+4096] for k in (0, 4096)])
        c.require((zs == 30).all() and np.array_equal(ys.argmax(1), ids//106496), 'actual source Y/Z')
        x = iq[:, :, 0]+1j*iq[:, :, 1]
        report.update(source_read_seconds=time.perf_counter()-start,
            source=dict(path=str(source), bytes=source.stat().st_size, sha256=c.file_hash(source),
                        row_ids_sha256=c.digest(ids.tobytes()), snr_db=30, unique_rows=8192))
        references, received, snrs = [], [], []
        report['parents'] = []
        for parent in parents:
            p = e.m.document(parent/'run-plan.json')
            prepared, tensors = e.prepare(parent, p, e.indices(p))
            report['parents'].append(dict(path=str(parent), plan_sha256=c.file_hash(parent/'run-plan.json'),
                prepared_sha256=c.digest(json.dumps(prepared, sort_keys=True).encode()),
                captures=[dict(batch=b['batch'], capture_sha256=b['parent_capture_sha256']) for b in prepared['results']]))
            for b in prepared['results']:
                parts = tensors[b['batch']]
                c.require(parts['raw'] is not None, 'benchmark synchronized RF parent')
                references.extend(parts['source']); received.extend(parts['raw'])
                snrs.extend(row['source_snr_db'] for row in b['rows'])
        ref, rx, z = np.array(references), np.array(received), np.array(snrs)
        report['unique_rf_rows'] = len(rx)
        token = asyncio.run(lease.acquire(time.monotonic()+10, request='offline-payload-benchmark'))
        spark_stopped()
        start = time.perf_counter(); gpu = g.PayloadBatch('cuda'); cpu = g.PayloadBatch('cpu')
        gpu.normalize(x[:24]); gpu.quality(ref[:24], rx[:24], z[:24])
        report['cuda_startup_seconds'] = time.perf_counter()-start
        t = gpu.torch
        report.update(torch_version=t.__version__, device=t.cuda.get_device_name(),
            cuda_device_total_bytes=t.cuda.get_device_properties(0).total_memory)
        for n in plan['batch_rows']:
            spark_stopped()
            take = np.arange(n)%len(rx)
            a, b, zz = ref[take], rx[take], z[take]
            gpu.normalize(x[:n]); gpu.quality(a, b, zz)
            t.cuda.reset_peak_memory_stats()
            expected, scalar_time = timed(lambda: np.stack([c.normalize_window(v) for v in x[:n]]))
            vector, cpu_time = timed(lambda: cpu.normalize(x[:n]))
            actual, gpu_time = timed(lambda: gpu.normalize(x[:n]))
            np.testing.assert_array_equal(vector, expected)
            np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-6)
            cq, cq_time = timed(lambda: cpu.quality(a, b, zz))
            gq, gq_time = timed(lambda: gpu.quality(a, b, zz))
            difference = quality_difference(cq, gq)
            output = scratch/'normalized.npy'
            start = time.perf_counter()
            with output.open('xb') as stream:
                np.save(stream, actual, allow_pickle=False); stream.flush(); os.fsync(stream.fileno())
            write_seconds = time.perf_counter()-start
            c.require(output.stat().st_size <= plan['maximum_temporary_output_bytes'], 'output bytes')
            np.testing.assert_array_equal(np.load(output, allow_pickle=False), actual)
            size = output.stat().st_size; output.unlink()
            peak = t.cuda.max_memory_allocated()
            c.require(peak <= plan['expected_gpu_allocated_limit_bytes'], 'GPU allocation budget')
            result = dict(rows=n, normalization_scalar_cpu=scalar_time, normalization_vector_cpu=cpu_time,
                normalization_gpu_host_to_host=gpu_time, quality_scalar_cpu=cq_time, quality_gpu_host_to_host=gq_time,
                normalization_max_abs=float(np.max(abs(actual-expected))),
                identical_normalized_rows=int(np.all(actual == expected, axis=(1, 2)).sum()),
                sinr_max_abs_db=difference, quality_status_reason_agree=True,
                disk_write_fsync_seconds=write_seconds, disk_bytes=size, disk_roundtrip_equal=True,
                cuda_peak_allocated_bytes=peak, cuda_peak_reserved_bytes=t.cuda.max_memory_reserved(),
                process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
            report['results'].append(result); c.save(root/'benchmark-results.json', report)
            print(json.dumps(result), flush=True)
        report.update(status='completed', spark_after=spark_stopped())
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'; raise
    finally:
        signal.alarm(0)
        if token is not None: lease.release(token)
        report['lease'] = lease.metrics.copy(); lease.close()
        report['finished_ns'] = time.time_ns(); c.save(root/'benchmark-results.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    run(parser.parse_args().root)
