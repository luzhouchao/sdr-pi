#!/usr/bin/env python3
"""Compare sealed historical/current frequency patterns on separate amplitude axes."""
import hashlib
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

REPO=Path(__file__).resolve().parents[3]
ROOT=Path('/var/tmp/sdrharness-dev/historical-background-20260909f')
source=ROOT/'summary.json'
history=json.loads(source.read_text())
current_paths=[REPO/'docs/evidence/P201_BACKGROUND_MAP_2026-09-09-summary.json',
               REPO/'docs/evidence/P201_WIFI5_BACKGROUND_2026-09-09-summary.json']
current=[json.loads(p.read_text()) for p in current_paths]
freq=np.array(history['frequencies_hz'])/1e6
old=np.array(history['groups']['all']['p95'])[:,0]
recent=np.array(history['groups']['2026-09-06']['p95'])[:,0]
median=np.array(history['groups']['all']['p50'])[:,0]
fig,axes=plt.subplots(2,2,figsize=(13,8),constrained_layout=True)
for col,(limits,label) in enumerate([((2400,2484),'2.4 GHz'),((5150,5850),'5 GHz')]):
    mask=(freq>=limits[0])&(freq<=limits[1])
    axes[0,col].plot(freq[mask],median[mask],color='#999999',lw=1,label='Historical median (1,586 sweeps)')
    axes[0,col].plot(freq[mask],old[mask],color='#0072B2',lw=1,label='Historical p95 (1,586 sweeps)')
    axes[0,col].plot(freq[mask],recent[mask],color='#D55E00',lw=1,label='Sep 6 p95 (9 sweeps)')
    axes[0,col].set(title=label+' historical 1-MHz subbands',ylabel='Mean of PSD dB bins\nthen quantile across sweeps (gain 60 dB)',xlim=limits)
    rows=current[col]['survey'];x=np.array([r['center_hz']/1e6 for r in rows])
    for i,color in enumerate(['#0072B2','#D55E00','#009E73']):
        y=[r['raw_rms'][i]['p95'] for r in rows]
        axes[1,col].plot(x,y,marker='o' if col else None,linestyle='None' if col else '-',color=color,lw=1,label=f'Sep 9 round {i+1}')
    axes[1,col].set(title=label+' current short captures',ylabel='128-sample RMS p95, ADC\n(gain 20 dB; log scale)',yscale='log',xlim=limits)
    for ax in axes[:,col]:
        ax.set_xlabel('Frequency (MHz)');ax.grid(alpha=.2);ax.legend(fontsize=8)
    spans=[(2410,2424),(2460,2465)] if col==0 else [(5235,5245),(5775,5815)]
    for lo,hi in spans:
        for ax in axes[:,col]:ax.axvspan(lo,hi,color='#e0a000',alpha=.12)
fig.suptitle('Historical vs current ambient activity: compare frequency patterns, not absolute amplitudes\nDifferent gain, bandwidth, antenna/session and statistics; sequential observations',fontsize=12)
prefix=REPO/'docs/evidence/HISTORICAL_BACKGROUND_COMPARISON_2026-09-09'
fig.savefig(str(prefix)+'-overview.png',dpi=150);plt.close(fig)
days=[d for d in history['groups'] if d!='all']
fig,axes=plt.subplots(1,2,figsize=(13,6),constrained_layout=True)
for col,limits in enumerate([(2400,2484),(5150,5850)]):
    mask=(freq>=limits[0])&(freq<=limits[1])
    values=np.array([history['groups'][d]['p95'] for d in days])[:,:,0][:,mask]
    im=axes[col].imshow(values,aspect='auto',extent=(*limits,len(days)-.5,-.5),cmap='magma',vmin=-115,vmax=-70)
    axes[col].set(yticks=range(len(days)),yticklabels=[f'{d} ({history["groups"][d]["sweeps"]})' for d in days],
        xlabel='Subband center (MHz)',ylabel='UTC date (number of sweeps)',title='Daily p95 of historical mean PSD dB')
    fig.colorbar(im,ax=axes[col],label='Historical PSD-bin mean (dB)')
fig.suptitle('Historical days shown categorically; missing dates are not interpolated',fontsize=12)
fig.savefig(str(prefix)+'-days.png',dpi=150);plt.close(fig)
summary=dict(schema_id='historical_background_compact_v1',parents=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in [source,*current_paths]],
    run_count=history['run_count'],date_range=[history['first_started_utc'],history['last_started_utc']],
    day_counts={d:history['groups'][d]['sweeps'] for d in days},target_comparison=[])
for c in [2410,2418.491304,2424.455072,2433.997101,2455,2464,5180,5240,5560,5704,5745,5785,5805,5825]:
    # At integer MHz, use both adjacent 1MHz bins; otherwise nearest center.
    distance=abs(freq-c);ids=np.flatnonzero(np.isclose(distance,distance.min(),rtol=0,atol=1e-6))
    summary['target_comparison'].append(dict(target_mhz=c,historical_subband_centers_mhz=freq[ids].tolist(),
        historical_median_db=float(median[ids].mean()),historical_p95_db=float(old[ids].mean()),sep6_p95_db=float(recent[ids].mean())))
Path(str(prefix)+'-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print('comparison and daily figures generated from sealed summaries')
