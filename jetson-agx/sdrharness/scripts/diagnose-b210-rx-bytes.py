#!/usr/bin/env python3
"""Read-only byte/buffer diagnostics; no RF, inference or continuity guarantee."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import numpy as np

if not __debug__:
    raise RuntimeError('validation assertions required')
SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[2]
AUDIT = REPO / 'docs/B210_RX_BYTE_AUDIT_2026-09-07.json'
spec = importlib.util.spec_from_file_location('byte_margin', SCRIPTS / 'validate-b210-2455-margin.py')
margin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(margin)


def decode(raw):
    if not isinstance(raw, bytes) or len(raw) != 65535 * 4:
        raise ValueError('exact 65535 ci16_le samples required')
    iq = np.frombuffer(raw, dtype='<i2').reshape(-1, 2)
    independent = np.asarray(list(struct.iter_unpack('<hh', raw)), dtype=np.int16)
    if not np.array_equal(iq, independent):
        raise ValueError('independent decoder disagreement')
    return iq


def longest_run(mask):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1)
    if not len(starts):
        return dict(start=None, count=0)
    best = int(np.argmax(stops - starts))
    return dict(start=int(starts[best]), count=int(stops[best] - starts[best]))


def block_groups(payloads, size):
    """Exact complete aligned repeats, including cross-capture matches."""
    groups = {}
    for name, raw in payloads.items():
        decode(raw)
        for start in range(0, 65535 - size + 1, size):
            block = raw[start * 4:(start + size) * 4]
            groups.setdefault(block, []).append(dict(capture=name, start=start))
    return [dict(sha256=hashlib.sha256(block).hexdigest(), occurrences=rows)
            for block, rows in groups.items() if len(rows) > 1]


def characterize(raw):
    iq = decode(raw)
    v = iq.astype(np.float64)
    power = np.sum(v * v, axis=1)
    differences = np.sqrt(np.sum(np.diff(v, axis=0) ** 2, axis=1))
    same = longest_run(np.all(iq[1:] == iq[:-1], axis=1))
    # A run of k equal edges covers k+1 samples; even without equal edges
    # there is a single-sample constant run.
    same = dict(start=same['start'] if same['count'] else 0, count=same['count'] + 1)
    words = np.frombuffer(raw, dtype='<u2')
    signed12 = (words.astype(np.int32) & 4095)
    signed12 = np.where(signed12 >= 2048, signed12 - 4096, signed12)
    swapped = np.frombuffer(raw, dtype='>i2').astype(np.int32)
    segments = [dict(start=n, count=min(128, len(iq) - n),
                     power=float(power[n:n + 128].mean())) for n in range(0, len(iq), 128)]
    transitions = []
    for left, right in zip(segments, segments[1:]):
        # Compare equally sized 128-sample segments only; tail is recorded below.
        if right['count'] != 128:
            continue
        transitions.append(dict(start=right['start'], modulo4096=right['start'] % 4096,
                                absolute_power_change=abs(right['power'] - left['power'])))
    transitions.sort(key=lambda row: (-row['absolute_power_change'], row['start']))
    boundaries = []
    for start in range(4096, len(iq), 4096):
        jump = float(differences[start - 1])
        boundaries.append(dict(start=start, jump_adc=jump,
                               jump_percentile=float(100 * np.mean(differences <= jump)),
                               before_rms=float(np.sqrt(power[start - 128:start].mean())),
                               after_rms=float(np.sqrt(power[start:start + 128].mean()))))
    return dict(samples=len(iq), sha256=hashlib.sha256(raw).hexdigest(),
                independent_decode_equal=True,
                signed12_mismatch_components=int(np.count_nonzero(signed12 != iq.ravel())),
                byte_swapped_outside_12bit_components=int(np.count_nonzero((swapped < -2048) | (swapped > 2047))),
                i_range=[int(iq[:, 0].min()), int(iq[:, 0].max())],
                q_range=[int(iq[:, 1].min()), int(iq[:, 1].max())],
                zero_samples=int(np.count_nonzero(np.all(iq == 0, axis=1))),
                longest_zero_run=longest_run(np.all(iq == 0, axis=1)), longest_constant_run=same,
                block_coverage={str(n): dict(complete_blocks=len(iq) // n, tail_samples=len(iq) % n)
                                for n in (128, 4096)},
                tail_128_segment=segments[-1],
                largest_power_transitions=transitions[:10], boundaries=boundaries)


def analyze():
    live = margin.live
    inventory_path = REPO / 'docs/B210_2455_MARGIN_EVIDENCE_2026-09-07.json'
    inventory = live.document(inventory_path)
    expected = {row['path'] for row in inventory['files']}
    assert len(expected) == len(inventory['files']) == 67
    assert {str(p) for root in inventory['roots'] for p in Path(root).rglob('*') if p.is_file()} == expected
    for row in inventory['files']:
        raw = live.read(Path(row['path']))
        assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    seal = live.document(margin.ROOT / 'seal.json')
    assert live.validate_capture_root(margin.feature('tone'), 'tone', expected_center_hz=2455000000) == seal['tone']
    for tag, peak in margin.CASES:
        assert margin.seal_case(margin.feature(tag), peak) == seal['cases'][tag]
    captures, payloads = {}, {}
    for tag in ('tone', *(name for name, _ in margin.CASES)):
        for phase in ('baseline', 'during-tx', 'after-tx'):
            name = f'{tag}/{phase}'
            native = live.document(margin.feature(tag) / f'{phase}-report.json')
            payloads[name] = live.read(Path(native['dataset']['data_path']))
            point = native['points'][0]
            captures[name] = dict(path=native['dataset']['data_path'],
                                  identity={key: point[key] for key in ('request_id', 'session_generation', 'sequence', 'rx_input', 'sample_rate_hz')},
                                  statistics=characterize(payloads[name]))
    return dict(schema_id='b210_rx_byte_audit_v1', numpy_version=np.__version__, posthoc=True,
                parent_inventory_sha256=hashlib.sha256(live.read(inventory_path)).hexdigest(),
                inventory_files_verified=67, captures=captures,
                exact_repeated_blocks={str(n): block_groups(payloads, n) for n in (128, 4096)},
                rf_operations=0, model_windows=0, independent_labels=0, recognizer_available=False,
                continuity_proven=False, source_gate_changes=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='recompute and compare the committed audit')
    args = parser.parse_args()
    result = analyze()
    if args.verify:
        saved = json.loads(AUDIT.read_text())
        assert saved['analysis'] == result
        print('15 captures and 67 inventory files verified; byte audit reproduced; no RF/model.')
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
