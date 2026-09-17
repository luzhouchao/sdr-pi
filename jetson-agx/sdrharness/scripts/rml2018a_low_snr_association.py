#!/usr/bin/env python3
"""Posthoc association of existing validation predictions and guard diagnostics.

Reads sealed JSON/NPZ only: no ADC, HDF5, source IQ, model or hardware access.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import resource
import shutil
import signal
import time

import numpy as np

REPO = Path(__file__).resolve().parents[3]
ROOT = Path('/var/tmp/sdrharness-dev')
OUT = ROOT / 'rml2018a-low-snr-association-20260917'
BASE = ROOT / 'rml2018a-offline-baseline-20260916'
LEAD = ROOT / 'rml2018a-leading-guard-20260916'
TIME = ROOT / 'rml2018a-lo-temporal-20260917'
SHARED = ROOT / 'rml2018a-shared-raw-rms-20260916-a2'
METRICS = ('phase_curvature_abs_rad', 'guard_error_margin', 'guard_holdout_counts2',
           'guard_holdout_over_tone_power', 'payload_lo_counts2', 'payload_lo_over_raw_power',
           'guard_to_raw_rms', 'conditional_sinr_delta_db')


def read(p):
    return json.loads(Path(p).read_text())


def save(p, v):
    Path(p).write_text(json.dumps(v, indent=2, allow_nan=False) + '\n')


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(ok, why):
    if not ok:
        raise ValueError(why)


def checked(item):
    p = Path(item['path'])
    require(p.stat().st_size == item['bytes'] and digest(p) == item['sha256'], str(p))
    return item


def index_unique(rows):
    result = {int(r['source_row']): r for r in rows}
    require(len(result) == len(rows), 'duplicate source row')
    return result


def stratified_comparison(rows, metric):
    """Same-class/SNR regression vs retained-correct pairs; no pseudo p-values."""
    cells = {}
    for r in rows:
        if r['state'] in ('regressed', 'retained_correct'):
            cells.setdefault((r['truth'], r['source_snr_db']), []).append(r)
    result = []
    for (cid, snr), group in sorted(cells.items()):
        a = np.array([r[metric] for r in group if r['state'] == 'regressed'])
        b = np.array([r[metric] for r in group if r['state'] == 'retained_correct'])
        if not len(a) or not len(b):
            continue
        d = a[:, None] - b[None, :]
        result.append(dict(class_id=cid, source_snr_db=snr, regressions=len(a), controls=len(b),
                           pairs=d.size, mean_difference=float(d.mean()),
                           fraction_regression_higher=float(np.mean((d > 0) + .5*(d == 0)))))
    return dict(metric=metric, matched_cells=len(result),
                regressions=sum(x['regressions'] for x in result),
                controls=sum(x['controls'] for x in result),
                pairs=sum(x['pairs'] for x in result),
                cell_equal_mean_difference=float(np.mean([x['mean_difference'] for x in result])) if result else None,
                cell_equal_fraction_higher=float(np.mean([x['fraction_regression_higher'] for x in result])) if result else None,
                cells=result)


def parents():
    files = []
    requests = [
        ('RML2018A_OFFLINE_BASELINE_2026-09-16.json', ('plan.json', 'baseline-rows.json', 'predictions.npz')),
        ('RML2018A_SHARED_RAW_RMS_2026-09-16.json', ('predictions.npz',)),
        ('RML2018A_LEADING_GUARD_2026-09-16.json', ('rows.json', 'frame-identities.json')),
        ('RML2018A_LO_TEMPORAL_2026-09-17.json', ('rows.json',))]
    for name, names in requests:
        p = REPO / 'docs/evidence' / name
        files.append(dict(path=str(p), bytes=p.stat().st_size, sha256=digest(p)))
        audit = read(p)
        if 'retention' in audit:
            files.append(checked(audit['retention']))
            entries = read(audit['retention']['path'])['files']
        else:
            entries = audit['files']
        for name in names:
            item = next(x for x in entries if Path(x['path']).name == name)
            files.append(checked(item))
    for item in read(LEAD / 'frame-identities.json'):
        files.append(checked(item))
    return files


def plan():
    OUT.mkdir(exist_ok=True)
    require(not (OUT / 'plan.json').exists(), 'new plan')
    files = parents()
    p = dict(schema='low-snr-association-v1', files=files, script_sha256=digest(__file__),
             scope='all2496 original validation records joined; primary576 at sourceZ -10..0; no new inference',
             expected_primary=dict(rows=576, regressed=106, corrected=36, retained_correct=79, both_wrong=355),
             metrics=list(METRICS),
             comparison='all four correctness states; regressions vs retained-correct additionally within same class and sourceZ; equal cell weight, disclose unmatched rows; no p-values or causal claim',
             analysis='posthoc, repeated diagnostic validation set; no parameter selection or deployable rule',
             limitations='guard metrics cover context rather than exact payload; LO band contains source/noise; class and sourceZ correlated with time; shared ADC and same model; no independent generalization',
             budget=dict(seconds=300, host_bytes=1024**3, output_bytes=32*1024**2,
                         free_bytes=shutil.disk_usage(OUT).free),
             rf=0, predictions=0, training=0, adc_reads=0, production_changes=False)
    require(p['budget']['free_bytes'] > 128*1024**2, 'space')
    save(OUT / 'plan.json', p)


def csvwrite(path, rows):
    with Path(path).open('w') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def run():
    start = time.monotonic()
    p = read(OUT / 'plan.json')
    require(digest(__file__) == p['script_sha256'], 'sealed script')
    require(not (OUT / 'started.json').exists(), 'one run')
    save(OUT / 'started.json', dict(time_ns=time.time_ns()))
    signal.alarm(p['budget']['seconds'])
    for f in p['files']:
        checked(f)
    base = index_unique(read(BASE / 'baseline-rows.json'))
    lead = index_unique(read(LEAD / 'rows.json'))
    temporal = index_unique(read(TIME / 'rows.json'))
    with np.load(BASE / 'predictions.npz', allow_pickle=False) as f:
        old = {k: f[k] for k in ('source_row', 'truth', 'validation_rank', 'source_snr_db',
               'source_logits', 'source_rms_logits', 'raw_logits', 'guard_logits')}
    with np.load(SHARED / 'predictions.npz', allow_pickle=False) as f:
        shared = f['logits'].argmax(1)
        for k in ('source_row', 'truth', 'validation_rank', 'source_snr_db'):
            require(np.array_equal(f[k], old[k]), 'shared order ' + k)
    ids = old['source_row']
    require(len(ids) == len(set(ids)) == 2496, 'unique expected members')
    require(set(ids) == set(base) == set(lead) == set(temporal), 'exact member join')
    labels = read(BASE / 'plan.json')['model']['class_order']
    predictions = {k: old[k+'_logits'].argmax(1) for k in ('source', 'source_rms', 'raw', 'guard')}
    records = []
    frame_cache = {}
    for i, sid in enumerate(ids):
        require(not (OUT / 'STOP').exists(), 'STOP requested')
        b, l, t = base[int(sid)], lead[int(sid)], temporal[int(sid)]
        require(all(b[k] == l[k] == t[k] for k in ('index', 'raw_path', 'frame')), 'frame join')
        require(b['index'] == i and b['sync']['context_sha256'] == l['sync']['context_sha256'], 'context join')
        require(t['context_sha256'] == l['context_with_leading_sha256'], 'temporal context')
        require(all(b['planes'][k]['strict_quality_pass'] and b['planes'][k]['usable'] for k in ('raw', 'guard')), 'historical quality')
        path = str(Path(b['frames']) / f"{b['frame']//64:03d}.json")
        if path not in frame_cache:
            frame_cache.clear()
            frame_cache[path] = read(path)
        fr = frame_cache[path][b['frame'] % 64]
        g = fr['guard']
        require(g['status'] == 'applied' and b['guard_status'] == 'applied', 'guard applied')
        require(t['frequency_hz'] == g['v1']['frequency_hz'] and t['marker_offset'] == fr['marker_offset'], 'frequency/position')
        truth = int(old['truth'][i])
        rc, gc = predictions['raw'][i] == truth, predictions['guard'][i] == truth
        state = ('retained_correct' if gc else 'regressed') if rc else ('corrected' if gc else 'both_wrong')
        power = g['v1']['amplitude_real']**2 + g['v1']['amplitude_imag']**2
        raw_rms = b['planes']['raw']['received_rms']
        require(power > 0 and raw_rms > 0, 'positive power')
        sinrs = [b['planes'][k]['conditional_effective_sinr_db'] for k in ('raw', 'guard')]
        require(all(v is not None for v in sinrs), 'conditional SINR available')
        r = dict(source_row=int(sid), validation_rank=int(old['validation_rank'][i]), truth=truth,
                 label=labels[truth], source_snr_db=int(old['source_snr_db'][i]), state=state,
                 **{k+'_prediction': int(v[i]) for k, v in predictions.items()}, shared_prediction=int(shared[i]),
                 raw_path=b['raw_path'], frame=b['frame'], window_in_frame=b['window_in_frame'],
                 context_sha256=b['sync']['context_sha256'],
                 phase_curvature_abs_rad=float(np.mean(np.abs(t['metrics']['future_phase_curvature_rad']))),
                 curvature_screen_all_blocks=all(t['metrics']['curvature_both_halves_4se']),
                 guard_error_margin=g['maximum_relative_error_margin'],
                 guard_holdout_counts2=g['v1']['heldout_error_power_counts2'],
                 guard_holdout_over_tone_power=g['v1']['heldout_error_power_counts2']/power,
                 payload_lo_counts2=l['payload_lo_region_baseline_counts2'],
                 payload_lo_over_raw_power=l['payload_lo_region_baseline_counts2']/raw_rms**2,
                 guard_to_raw_rms=b['planes']['guard']['received_rms']/raw_rms,
                 raw_conditional_sinr_db=sinrs[0], guard_conditional_sinr_db=sinrs[1],
                 conditional_sinr_delta_db=sinrs[1]-sinrs[0])
        require(all(np.isfinite(r[k]) for k in METRICS), 'finite metrics')
        records.append(r)
    low = [r for r in records if -10 <= r['source_snr_db'] <= 0]
    states = dict(Counter(r['state'] for r in low))
    require(dict(rows=len(low), **states) == p['expected_primary'], 'fixed primary counts')
    def summary(group):
        return dict(rows=len(group), states=dict(Counter(r['state'] for r in group)),
                    correct={k: sum(r[k+'_prediction'] == r['truth'] for r in group)
                             for k in ('source', 'source_rms', 'raw', 'guard', 'shared')},
                    conditional_sinr_improved=sum(r['conditional_sinr_delta_db'] > 0 for r in group),
                    curvature_screen_all_blocks=sum(r['curvature_screen_all_blocks'] for r in group),
                    metrics={k: np.percentile([r[k] for r in group], [5,50,95]).tolist() if group else None for k in METRICS})
    result = dict(primary=summary(low), per_state={k: summary([r for r in low if r['state']==k]) for k in sorted(states)},
                  per_class=[dict(class_id=k,label=labels[k],**summary([r for r in low if r['truth']==k])) for k in range(24)],
                  per_source_snr=[dict(source_snr_db=k,**summary([r for r in records if r['source_snr_db']==k])) for k in range(-20,31,2)],
                  matched=[stratified_comparison(low,k) for k in METRICS],
                  new_rf=0,new_predictions=0,causal=False,elapsed_seconds=time.monotonic()-start,
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    transitions = Counter((r['truth'],r['guard_prediction']) for r in low if r['state']=='regressed')
    csvwrite(OUT/'regression-confusions.csv', [dict(truth=k[0],label=labels[k[0]],guard_prediction=k[1],predicted_label=labels[k[1]],rows=v) for k,v in sorted(transitions.items(),key=lambda x:(-x[1],x[0]))])
    csvwrite(OUT/'rows.csv',records)
    csvwrite(OUT/'low-snr-regressions.csv',[r for r in low if r['state']=='regressed'])
    save(OUT/'results.json',result)
    require(result['peak_rss_bytes'] < p['budget']['host_bytes'], 'memory budget')
    require(sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file()) < p['budget']['output_bytes'], 'output budget')
    signal.alarm(0)
    print(json.dumps(result['primary']))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('plan','run'))
    args=parser.parse_args()
    {'plan':plan,'run':run}[args.command]()
