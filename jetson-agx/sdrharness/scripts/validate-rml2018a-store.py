#!/usr/bin/env python3
"""Offline full96-block disk validation with synthetic IQ; no RF/GPU/model."""
import argparse
import json
from pathlib import Path
import shutil
import signal
import time

import numpy as np

import rml2018a_campaign_store as s


def run(root):
    s.c.require(root.is_absolute() and root.resolve() == root and root.is_dir() and
                root.parent == Path('/var/tmp/sdrharness-dev') and not (root/'plan.json').exists(), 'fresh validation root')
    s.c.require(shutil.disk_usage(root).free > 4*1024**3, 'four GiB finite disk reserve')
    plan = dict(schema='rml2018a-snr-store-offline-validation-v1', source='synthetic periodic tone, no RadioML file read',
        blocks=96, rows_per_block=1024, simulated_unsynchronized_rows_per_block=1,
        raw_samples=96*1024**2, raw_bytes=96*1024**2*4, maximum_corpus_bytes=4*1024**3,
        deadline_seconds=600, maximum_new_rf_seconds=0, model_windows=0, gpu_calls=0,
        free_bytes=shutil.disk_usage(root).free, stop='SIGINT/SIGTERM/600s alarm; preserve partial files')
    s.atomic_json(root/'plan.json', plan)
    def abort(sig, frame): raise RuntimeError(f'validation signal {sig}')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM): signal.signal(sig, abort)
    signal.alarm(600)
    corpus = root/'synthetic-corpus'; corpus.mkdir(mode=0o700)
    config = dict(session_id='offline-snr-storage-20260913', source_snr_db=30, max_raw_samples=plan['raw_samples'],
        source_sha256='0'*64, preprocess_id='synthetic-storage-fixture-not-model-input-evidence',
        profile_sha256='0'*64, label_map_sha256='0'*64, sample_rate_hz=2100000, center_hz=2455000000,
        bandwidth_hz=1500000, rx_gain_db=50, tx_gain_db=60)
    unit = np.exp(2j*np.pi*np.arange(1024)*.123)
    raw = np.tile(np.round(100*np.stack((unit.real, unit.imag), 1)).astype('<i2'), (1024,1))
    y = raw[:1024,0]+1j*raw[:1024,1]
    inputs = {tag:np.tile(s.c.normalize_window(unit if tag=='source' else y), (1024,1,1)) for tag in s.TAGS}
    masks = {tag:np.ones(1024,dtype=bool) for tag in s.TAGS}
    for tag in ('raw','guard'): inputs[tag][0] = np.nan; masks[tag][0] = False
    q = s.c.receive_quality('synchronized', unit, y, 30)
    quality = [dict(raw=q, sync=dict(status='synchronized', fixture=True)) for _ in range(1024)]
    quality[0] = dict(raw=s.c.receive_quality('sync_failed'), sync=dict(status='sync_failed', fixture=True))
    metadata = dict(capture_id='synthetic-tone-no-radio', timestamp_utc='2026-09-13T00:00:00Z',
        timestamp_reference='synthetic_fixture', dropped_samples=0, overflow=False, clipped_samples=0,
        background=dict(status='not_measured', reason='offline fixture, no background capture'))
    report = dict(status='failed', plan_sha256=s.c.file_hash(root/'plan.json'), blocks=[])
    started = time.perf_counter()
    try:
        with s.SnrStore(corpus, configuration=config) as store:
            for block in range(96):
                t = time.perf_counter(); receipt = store.append_raw(raw, dict(metadata, transport_sequence=block))
                raw_seconds = time.perf_counter()-t
                starts = np.arange(1024,dtype='<i8')*1024+receipt['sample_start']; starts[0] = -1
                counts = np.full(1024,1024,dtype='<i8'); counts[0] = 0
                t = time.perf_counter(); store.append_processed(inputs,masks,starts,counts,quality)
                report['blocks'].append(dict(block=block, raw_seconds=raw_seconds, processed_seconds=time.perf_counter()-t))
                s.c.require(sum(p.stat().st_size for p in corpus.iterdir()) < plan['maximum_corpus_bytes'], 'finite corpus bytes')
                if block%16 == 15: print(json.dumps(dict(blocks_written=block+1)), flush=True)
            report['append_seconds'] = time.perf_counter()-started
            t = time.perf_counter(); store.finish(); report['finish_verify_seconds'] = time.perf_counter()-t
        t = time.perf_counter()
        with s.SnrStore(corpus) as store:
            report['reopen_verify_seconds'] = time.perf_counter()-t
            seen = 0; valid = 0
            for batch in store.iter_processed('raw', 128):
                s.c.require(len(batch['source_row']) == 128 and batch['inputs'].shape == (128,2,1024), 'bounded model reader')
                seen += len(batch['source_row']); valid += int(batch['valid'].sum())
            s.c.require((seen,valid) == (98304,98208), 'full failed-row denominator')
            report.update(status='completed', stored_rows=seen, valid_raw_rows=valid, unsynchronized_rows=seen-valid,
                          completion=store.index, wall_seconds=time.perf_counter()-started)
        report['files'] = [dict(path=str(p), bytes=p.stat().st_size, sha256=s.c.file_hash(p)) for p in sorted(corpus.iterdir())]
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'; raise
    finally:
        signal.alarm(0); s.atomic_json(root/'validation.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', type=Path, required=True)
    run(parser.parse_args().root)
