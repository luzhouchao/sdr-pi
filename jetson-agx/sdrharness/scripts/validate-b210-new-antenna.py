#!/usr/bin/env python3
"""Three fixed .2 source repetitions with the operator's new RX1 antenna."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal

import numpy as np

if not __debug__:
    raise RuntimeError('validation assertions required')
SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('antenna_margin', SCRIPTS / 'validate-b210-2455-margin.py')
margin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(margin)
repair, lo, live = margin.repair, margin.lo, margin.live
background = live.affine.module('antenna_background', 'diagnose-b210-background.py')
ROOT = Path('/var/tmp/sdrharness-dev/b210-antenna-907t')
CASES = (('r1', .2), ('r2', .2), ('r3', .2))
REPO = live.affine.ROOT
AUDIT = REPO / 'docs/B210_RX1_NEW_ANTENNA_AUDIT_2026-09-07.json'
INVENTORY = REPO / 'docs/B210_RX1_NEW_ANTENNA_EVIDENCE_2026-09-07.json'


def feature(tag):
    if tag not in ('tone', 'r1', 'r2', 'r3'):
        raise ValueError('unregistered case')
    return ROOT.parent / f'b210-antenna-{tag}-907t'


def export():
    parent = margin.feature('low1')
    margin.validate_plan(parent, .2)
    context = dict(schema_id='b210_rx1_new_antenna_v1', operator_report='new 2.4/5GHz antenna moved from RX2 to RX1',
                   physical_input='RX1/RX0/A_BALANCED', source_parent=str(parent),
                   parent_payload_sha256=margin.HASHES[.2], cases=list(CASES),
                   historical_comparison_only=True, antenna_causal_effect_established=False,
                   recognizer_available=False, independent_labels=0)
    assert ROOT.resolve() == ROOT and ROOT.is_dir()
    lo.save(ROOT / 'antenna-context.json', context)
    for tag in ('tone', 'r1', 'r2', 'r3'):
        feature(tag).mkdir(mode=0o700)
        if tag == 'tone':
            continue
        os.link(parent / 'train-tile.fc32', feature(tag) / 'train-tile.fc32')
        lo.save(feature(tag) / 'transmission-plan.json', live.document(parent / 'transmission-plan.json'))
        margin.validate_plan(feature(tag), .2)


def prepare():
    seal = live.document(ROOT / 'seal.json')
    assert live.validate_capture_root(feature('tone'), 'tone', expected_center_hz=2455000000) == seal['tone']
    tone = live.match.tone_metrics(feature('tone'))
    assert live.match.assess_tone(tone)['passed']
    report = dict(schema_id='b210_rx1_new_antenna_results_v1', analysis_numpy=np.__version__,
                  antenna_context=live.document(ROOT / 'antenna-context.json'), seal=seal,
                  tone=tone, model_inputs={}, cases={}, model_start=repair.MODEL_START,
                  recognizer_available=False, independent_labels=0, production_profile_compatible=False)
    tensors = {}
    for tag, peak in CASES:
        case_root = feature(tag)
        assert margin.seal_case(case_root, peak) == seal['cases'][tag]
        v = np.frombuffer(live.read(case_root / 'train-tile.fc32'), dtype='<f4').reshape(1024, 2)
        source = v[:, 0].astype(float) + 1j * v[:, 1].astype(float)
        captures = {phase: live.match.read_iq(case_root, phase)[0] for phase in ('baseline', 'during-tx', 'after-tx')}
        result, inputs = repair.evaluate(source, captures, tone['frequency_difference_hz'], 250000)
        result['background_statistics'] = {phase: background.stats(raw) for phase, raw in captures.items()}
        result['tx_evidence'] = live.document(case_root / 'tx-summary.json')
        report['cases'][tag] = result
        for name, data in inputs.items():
            tensors[tag + '_' + name] = data
    report['model_inputs'] = {key: hashlib.sha256(data.tobytes()).hexdigest() for key, data in tensors.items()}
    report['qualified_cases'] = [tag for tag, result in report['cases'].items() if result['model_control_passed']]
    return report, tensors


def acquire(binary):
    for tag, peak in CASES:
        margin.validate_plan(feature(tag), peak)
    assert repair.filter_contract()['coefficients_sha256'] == 'd0e12014bedae088b71366497299adc3a1be0a45cf622e9cbb346d4ea0c8c8be'
    lo.acquire(binary, root=ROOT, cases=CASES, feature_path=feature,
               center_hz=2455000000, validate_source=margin.validate_plan, seal_source=margin.seal_case)


def historical_comparison():
    """Same amplitude/settings, different antenna/time/daemon; no causal estimate."""
    original = live.document(REPO / 'docs/B210_2455_MARGIN_AUDIT_2026-09-07.json')
    result = {}
    for tag in ('low1', 'low2'):
        assert margin.seal_case(margin.feature(tag), .2) == original['seal']['cases'][tag]
        phases = {}
        for phase in ('baseline', 'during-tx', 'after-tx'):
            raw = live.match.read_iq(margin.feature(tag), phase)[0]
            stats = background.stats(raw)
            phases[phase] = dict(raw=stats['raw'], filtered=stats['filtered'])
        result[tag] = dict(fixed_model_block=original['cases'][tag]['fixed_model_block'],
                          model_control_passed=original['cases'][tag]['model_control_passed'],
                          statistics=phases)
    return dict(causal_antenna_effect_established=False, differences=['antenna', 'session/time', 'sdrd version'],
                original_audit_sha256=hashlib.sha256(live.read(REPO / 'docs/B210_2455_MARGIN_AUDIT_2026-09-07.json')).hexdigest(),
                old_same_amplitude_cases=result)


def bounded_report(report):
    """Keep decision evidence plus a hash of every reproducible diagnostic value."""
    result = {key: value for key, value in report.items() if key != 'cases'}
    result['full_preparation_sha256'] = hashlib.sha256(json.dumps(
        report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    result['cases'] = {}
    for tag, case in report['cases'].items():
        compact = {key: value for key, value in case.items() if key not in ('pointwise', 'segments', 'background_statistics')}
        compact['source_alignment'] = case['pointwise']['alignment']
        compact['background_statistics'] = {
            phase: {key: value for key, value in stats.items() if key not in ('raw_segments', 'filtered_segments')}
            for phase, stats in case['background_statistics'].items()}
        result['cases'][tag] = compact
    return result


def verify():
    inventory = live.document(INVENTORY)
    expected = {row['path'] for row in inventory['files']}
    assert len(expected) == len(inventory['files'])
    assert {str(p) for name in inventory['roots'] for p in Path(name).rglob('*') if p.is_file()} == expected
    for row in inventory['files']:
        raw = live.read(Path(row['path']))
        assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    report, tensors = prepare()
    saved = live.document(AUDIT)
    assert saved['analysis'] == bounded_report(report)
    assert saved['historical_comparison'] == historical_comparison()
    assert set(tensors) == set(saved['inference']['results'])
    for key, data in tensors.items():
        assert hashlib.sha256(data.tobytes()).hexdigest() == saved['inference']['results'][key]['input_sha256']
    print(json.dumps(dict(qualified_cases=report['qualified_cases'], retained_files=len(expected),
                         rf_operations=0, model_reexecuted=False, replay='passed')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--export', action='store_true')
    group.add_argument('--acquire', type=Path)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--infer', action='store_true')
    group.add_argument('--verify-retained', action='store_true')
    args = parser.parse_args()
    if args.export:
        export()
    elif args.acquire:
        acquire(args.acquire)
    elif args.prepare:
        lo.save(ROOT / 'prepared.json', prepare()[0])
    elif args.verify_retained:
        verify()
    else:
        def abort(signum, frame):
            raise RuntimeError(f'stop signal {signum}')
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, abort)
        asyncio.run(repair.infer(root=ROOT, prepare_function=prepare, max_inputs=12))
