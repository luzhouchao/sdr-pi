#!/usr/bin/env python3
"""Current receive-SINR charts: D10 replaces D8; sealed parents stay intact."""
import csv
import hashlib
import json
import os
from pathlib import Path
import numpy as np

REPO=Path(__file__).resolve().parents[3]
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-current-model-plots-20260922')
PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-sinr-stratification-20260922')
REMOVED='amc_mamba_d8-seed42'
D10='amc_mamba_d10-seed42'


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def main():
    ROOT.mkdir(exist_ok=False)
    seal=json.loads((REPO/'docs/evidence/RML2018A_SINR_STRATIFICATION_2026-09-22.json').read_text())
    for name in ['results.json','plan.json']:
        rec=next(r for r in seal['files'] if r['path']==str(PARENT/name));assert digest(PARENT/name)==rec['sha256']
    original=json.loads((PARENT/'results.json').read_text());labels=json.loads((PARENT/'plan.json').read_text())['labels']
    models={k:v for k,v in original['models'].items() if k!=REMOVED};models[D10]='D10'
    result=dict(models=models,paired=[x for x in original['paired'] if x['model']!=REMOVED],own=[x for x in original['own'] if x['model']!=REMOVED],
                scope='Current 8 models shared2496; only7 have common369497 predictions, no D10 extrapolation; raw/guard only')
    save(ROOT/'plan.json',dict(parent=str(PARENT),parent_results_sha256=digest(PARENT/'results.json'),parent_plan_sha256=digest(PARENT/'plan.json'),script_sha256=digest(__file__),removed_model=REMOVED,current_models=models,labels=labels,output_budget_bytes=16*1024**2,rf=False,inference=False))
    save(ROOT/'results.json',result)
    for name,key in [('paired-bins.csv','paired'),('own-sinr-bins.csv','own')]:
        with (ROOT/name).open('w') as f:w=csv.DictWriter(f,fieldnames=list(result[key][0]));w.writeheader();w.writerows(result[key])
    os.environ['MPLCONFIGDIR']=str(ROOT/'cache/matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for population,names in [('shared2496',list(models)),('common369497',[k for k in models if k!=D10])]:
        selected=[x for x in result['paired'] if x['population']==population]
        counts=[next(x['rows'] for x in selected if x['raw_reference_sinr_bin']==lab) for lab in labels[:8]]
        values=np.array([[next(x['change_pp'] for x in selected if x['model']==name and x['raw_reference_sinr_bin']==lab) for lab in labels[:8]] for name in names])
        fig,ax=plt.subplots(figsize=(11,5));im=ax.imshow(values,cmap='RdBu',vmin=-75,vmax=75,aspect='auto')
        for i in range(len(names)):
            for j in range(8):ax.text(j,i,f'{values[i,j]:+.1f}',ha='center',va='center',fontsize=9)
        ax.set(yticks=range(len(names)),yticklabels=[models[k] for k in names],xticks=range(8),xticklabels=[f'{a}\nn={b}' for a,b in zip(labels,counts)],xlabel='Raw-reference conditional estimated SINR (dB)',title=f'{len(names)} current models, {population}: guard minus raw (paired members)')
        fig.colorbar(im,ax=ax,label='Percentage points');fig.tight_layout();fig.savefig(ROOT/(population+'-paired.png'),dpi=160);plt.close(fig)
    fig,axes=plt.subplots(2,4,figsize=(16,8));centers=[-22.5,-17.5,-12.5,-7.5,-2.5,2.5,7.5,12.5,17.5,22.5]
    for ax,name in zip(axes.flat,models):
        for plane in ['raw','guard']:
            q=[next(x for x in result['own'] if x['population']=='shared2496' and x['model']==name and x['plane']==plane and x['sinr_bin']==lab) for lab in labels[:10]]
            ax.plot(centers,[v['accuracy'] if v['rows'] else np.nan for v in q],marker='.',label=plane)
        ax.set_title(models[name]);ax.set_xlabel('SINR bin center (dB)',fontsize=9);ax.set_ylabel('Accuracy (%)');ax.legend(fontsize=8)
    fig.suptitle('8 current models, shared 2,496 samples: raw and guard\nConditional estimated SINR; each curve uses own bins (different members); tails plotted at +/-22.5 dB')
    fig.tight_layout();fig.savefig(ROOT/'own-sinr-curves.png',dpi=150);plt.close(fig)
    for key in ('paired','own'):
        assert result[key]==[x for x in original[key] if x['model']!=REMOVED]
        assert all(x['model']!=REMOVED for x in result[key])
    assert len(models)==8 and D10 in models and REMOVED not in models
    assert all(x['model']!=D10 for x in result['paired'] if x['population']=='common369497')
    save(ROOT/'verification.json',dict(passed=True,only_removed_D8=True,all_retained_statistics_exact=True,current_models=8,full_population_models=7,raw_guard_only=True,source_curve=False))
    assert sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())<16*1024**2
    print('8-model current figures and filtered statistics verified')

if __name__=='__main__':main()
