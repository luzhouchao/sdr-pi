#!/usr/bin/env python3
"""All-case numerical comparison and retained replay; never estimated RF accuracy."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[2]
ROOT = Path('/var/tmp/sdrharness-dev/b210-multiclass-907u')
AUDIT = REPO / 'docs/B210_MULTICLASS_AUDIT_2026-09-07.json'
INVENTORY = REPO / 'docs/B210_MULTICLASS_EVIDENCE_2026-09-07.json'
KINDS = ('source_original', 'source_filtered', 'received_raw', 'received_filtered')


def summarize(manifest, analysis, inference):
    assert len(manifest['cases']) == 72
    rows = []
    for p in manifest['cases']:
        tag = p['case_id']
        detail = analysis['cases'][tag]
        row = dict(case_id=tag, class_id=p['class_id'], row=p['rows'][0],
                   transport_status=detail['transport_status'], qualification_passed=detail['qualification_passed'],
                   fir_eligible=detail['fir_eligible'])
        for kind in KINDS:
            prediction = inference['results'].get(tag + '/' + kind)
            row[kind] = None if prediction is None else prediction['numeric_id']
        rows.append(row)
    def totals(selected):
        out = dict(registered=len(selected), qualification_passed=sum(r['qualification_passed'] for r in selected))
        for kind in KINDS:
            out[kind] = dict(measured=sum(r[kind] is not None for r in selected),
                             nominal_agreement=sum(r[kind] == r['class_id'] for r in selected))
        for suffix, received in (('raw', 'received_raw'), ('filtered', 'received_filtered')):
            pairs = [r for r in selected if r['source_original'] is not None and r[received] is not None]
            source_matched = [r for r in pairs if r['source_original'] == r['class_id']]
            out[suffix + '_paired'] = dict(measured=len(pairs),
                unchanged=sum(r['source_original'] == r[received] for r in pairs),
                source_nominal_matched=len(source_matched),
                source_match_preserved=sum(r[received] == r['class_id'] for r in source_matched))
        return out
    return dict(rows=rows, total=totals(rows),
                by_class={str(c): totals([r for r in rows if r['class_id'] == c]) for c in range(24)},
                semantics='train-source nominal agreement; 72-case pilot, not independent receive-domain accuracy')


def read(path):
    return json.loads(path.read_text())


def write_audit():
    manifest = read(REPO / 'jetson-agx/sdrharness/config/amc/b210-multiclass-907u.json')
    analysis, inference = read(ROOT / 'prepared.json'), read(ROOT / 'inference.json')
    report = dict(schema_id='b210_multiclass_audit_v1', analysis=analysis, inference=inference,
                  summary=summarize(manifest, analysis, inference))
    with AUDIT.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(report['summary']['total']))


def verify():
    spec = importlib.util.spec_from_file_location('multi_replay', SCRIPTS / 'validate-b210-multiclass.py')
    multi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(multi)
    inventory = read(INVENTORY)
    expected = {r['path'] for r in inventory['files']}
    assert len(expected) == len(inventory['files'])
    actual = {str(p) for root in inventory['roots'] for p in Path(root).rglob('*') if p.is_file()}
    assert actual == expected
    for item in inventory['files']:
        path = Path(item['path'])
        assert path.resolve() == path and not path.is_symlink()
        raw = path.read_bytes()
        assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
    report = read(AUDIT)
    analysis, tensors = multi.prepare()
    assert analysis == report['analysis']
    assert set(tensors) == set(report['inference']['results'])
    import numpy as np
    for key, tensor in tensors.items():
        result = report['inference']['results'][key]
        assert hashlib.sha256(tensor.tobytes()).hexdigest() == result['input_sha256']
        logits = np.asarray(result['logits'], dtype=np.float64)
        assert logits.shape == (4, 24) and np.isfinite(logits).all()
        assert logits.mean(axis=0).tolist() == result['mean_logits']
        assert int(logits.mean(axis=0).argmax()) == result['numeric_id']
        assert logits.argmax(axis=1).tolist() == result['window_numeric_ids']
    assert summarize(multi.manifest(), analysis, report['inference']) == report['summary']
    print(json.dumps(dict(replay='passed', retained_files=len(expected), model_reexecuted=False,
                         rf_operations=0, total=report['summary']['total'])))


def plot(destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report = read(AUDIT)
    summary = report['summary']
    fig, axes = plt.subplots(1, 2, figsize=(15, 7), constrained_layout=True)
    for kind, label, color, offset in (
            ('source_original', 'Original source', '#607d8b', -.24),
            ('received_raw', 'Raw reception', '#c65546', 0),
            ('received_filtered', 'Fixed FIR reception', '#237b9a', .24)):
        axes[0].barh([c+offset for c in range(24)],
                     [summary['by_class'][str(c)][kind]['nominal_agreement'] for c in range(24)],
                     height=.23, color=color, label=label)
    axes[0].set(yticks=range(24), ylabel='Dataset numeric class (names provisional)',
                xlabel='Nominal ID agreement / 3 registered source rows', xticks=range(4), xlim=(0, 3.4))
    axes[0].invert_yaxis()
    axes[0].legend(fontsize=8)
    import numpy as np
    values = np.full((24, 6), np.nan)
    for row in summary['rows']:
        r = int(row['case_id'][1])
        for col, kind in enumerate(('received_raw', 'received_filtered')):
            if row[kind] is not None:
                values[row['class_id'], r*2+col] = row[kind] == row['class_id']
    axes[1].imshow(values, vmin=0, vmax=1, cmap=matplotlib.colors.ListedColormap(['#e8bbb4', '#afd0db']), aspect='auto')
    for row in summary['rows']:
        r = int(row['case_id'][1])
        for col, kind in enumerate(('received_raw', 'received_filtered')):
            value = row[kind]
            axes[1].text(r*2+col, row['class_id'], '-' if value is None else str(value), ha='center', va='center', fontsize=8)
    axes[1].set(yticks=range(24), xticks=range(6), xticklabels=['R1 raw', 'R1 FIR', 'R2 raw', 'R2 FIR', 'R3 raw', 'R3 FIR'],
                title='Received predicted IDs; blue = source nominal ID')
    fig.suptitle('24-class train-source RF diagnostic / 1024 samples per TX unit\n72 samples, +30 dB nominal dataset condition; not independent RF test accuracy')
    fig.savefig(destination, dpi=140)
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--write', action='store_true')
    group.add_argument('--verify-retained', action='store_true')
    group.add_argument('--plot', type=Path)
    args = parser.parse_args()
    if args.write: write_audit()
    elif args.verify_retained: verify()
    else: plot(args.plot)
