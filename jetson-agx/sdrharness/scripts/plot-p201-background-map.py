#!/usr/bin/env python3
"""Plot sealed background-map numbers; no RF, model, or IQ copy."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main(root, output):
    source = root/'audit.json'
    audit = json.loads(source.read_text())
    wifi5 = audit.get('band') == '5g'
    assert audit['status'] == 'completed' and len(audit['sweeps']) == (90 if wifi5 else 18)
    surveys = [dict(rows=[r for s in audit['sweeps'] if s['phase']=='survey' and s['round']==i for r in s['rows']]) for i in range(3)]
    focused = [s for s in audit['sweeps'] if s['phase']=='focus']
    centers = np.array(audit['centers_hz'])/1e6
    x = np.arange(len(centers)) if wifi5 else centers
    limits = (-.5,len(centers)-.5) if wifi5 else (2400,2483.5)
    colors = ['#0072B2', '#D55E00', '#009E73']
    fig, ax = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    for i, s in enumerate(surveys):
        stats = [r['statistics'] for r in s['rows']]
        ax[0,0].plot(x, [v['raw_rms']['p95'] for v in stats], color=colors[i], label=f'Round {i+1}', lw=1.2, marker='o' if wifi5 else None, linestyle='None' if wifi5 else '-')
        ax[0,1].plot(x, [v['raw_rms']['p50'] for v in stats], color=colors[i], label=f'Round {i+1}', lw=1.2, marker='o' if wifi5 else None, linestyle='None' if wifi5 else '-')
    for panel, title in zip(ax[0], ['High-activity tail: 128-sample RMS p95', 'Typical background: 128-sample RMS median']):
        panel.set(xlabel='RX center frequency (MHz)', ylabel='ADC RMS (log scale)', yscale='log', xlim=limits, title=title)
        if wifi5: panel.set_xticks(x, [f'{c:g}' for c in centers], rotation=60, fontsize=7)
        panel.grid(alpha=.2); panel.legend()
    matrix = [[r['statistics']['observed_fraction_above_10x_median_power']*100 for r in s['rows']] for s in surveys]
    im = ax[1,0].imshow(matrix, aspect='auto', extent=(*limits,3.5,.5), cmap='magma', vmin=0)
    ax[1,0].set(xlabel='RX center frequency (MHz)', ylabel='Sequential survey round', yticks=[1,2,3], title='Observed blocks >10x each capture median power')
    if wifi5: ax[1,0].set_xticks(x, [f'{c:g}' for c in centers], rotation=60, fontsize=7)
    fig.colorbar(im, ax=ax[1,0], label='Observed block fraction (%)')
    focus_centers = audit['selection']['centers_hz']
    for i in range(3):
        rows = [s['rows'][0] for s in focused if s['round']==i]
        assert [r['center_hz'] for r in rows] == focus_centers
        ax[1,1].plot(range(5), [r['statistics']['raw_rms']['p95'] for r in rows], 'o-', color=colors[i], label=f'Retest {i+1}')
    ax[1,1].set(xticks=range(5), xticklabels=[f'{c/1e6:.3f}' for c in focus_centers], xlabel='RX center (MHz)', ylabel='ADC RMS p95 (log scale)', yscale='log', title='Independent repeats at fixed selected centers')
    ax[1,1].grid(alpha=.2); ax[1,1].legend()
    fig.suptitle(('5 GHz Wi-Fi channel-center samples (1.5 MHz RX, gaps unmeasured)' if wifi5 else '2.4 GHz antenna background') + ' | gain 20 dB\n31.2 ms per point; sequential, no protocol/source labels', fontsize=13)
    fig.savefig(str(output)+'-overview.png', dpi=150); plt.close(fig)
    fig, axes = plt.subplots(5, 3, figsize=(13, 10), sharex=True, sharey=True, constrained_layout=True)
    for i,c in enumerate(focus_centers):
        for j in range(3):
            s = next(s for s in focused if s['round']==j and s['rows'][0]['center_hz']==c)
            v = s['rows'][0]['statistics']; y = np.array(v['rms_128']); t=np.arange(len(y))*128/2100000*1000
            axes[i,j].plot(t,y,color=colors[j],lw=.8)
            axes[i,j].set(yscale='log', title=f'{c/1e6:.3f} MHz | retest {j+1}')
            axes[i,j].grid(alpha=.2)
            if j==0: axes[i,j].set_ylabel('ADC RMS')
            if i==4: axes[i,j].set_xlabel('Time within this capture (ms)')
    fig.suptitle('All 15 focused captures | separate 31.2 ms windows, not simultaneous\n128-sample segments (60.95 us); fixed 20 dB gain', fontsize=13)
    fig.savefig(str(output)+'-time.png',dpi=150);plt.close(fig)
    summary=dict(schema_id='p201_background_map_summary_v1',parent_audit=str(source),parent_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        selection=audit['selection'],survey=[],focus=[])
    for center in audit['centers_hz']:
        rows=[next(r for r in s['rows'] if r['center_hz']==center) for s in surveys]
        summary['survey'].append(dict(center_hz=center,raw_rms=[r['statistics']['raw_rms'] for r in rows],
            observed_relative_burst_fraction=[r['statistics']['observed_fraction_above_10x_median_power'] for r in rows]))
    for s in focused:
        r=s['rows'][0];summary['focus'].append(dict(center_hz=r['center_hz'],round=s['round'],started_unix=s['started_unix'],
            raw_rms=r['statistics']['raw_rms'],relative_burst_fraction=r['statistics']['observed_fraction_above_10x_median_power'],strongest_non_dc_hz=r['statistics']['strongest_non_dc_hz']))
    Path(str(output)+'-summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output-prefix',type=Path,required=True)
    a=p.parse_args();main(a.root,a.output_prefix)
