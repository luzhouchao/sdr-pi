#!/usr/bin/env python3
"""Exploratory capture-disjoint receiver-feature routing; no RF/model inference."""
import csv,hashlib,json,os,resource,shutil,time
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[3]
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-rx-selector-20260926-a2')
ASSOC=Path('/var/tmp/sdrharness-dev/rml2018a-low-snr-association-20260917/rows.csv')
PARTIAL=Path('/var/tmp/sdrharness-dev/rml2018a-d10-partial-20260926/predictions.npz')
FEATURES=['guard_to_raw_rms','phase_curvature_abs_rad','guard_error_margin','guard_holdout_over_tone_power','payload_lo_over_raw_power']
VARIANTS=['raw','alpha25','guard']
EDGES=[-20,-15,-10,-5,0,5,10,15,20]
LABELS=['<-20','[-20,-15)','[-15,-10)','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20','invalid']

def save(name,value): (ROOT/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def seal(path,audit):
    a=json.loads((REPO/'docs/evidence'/audit).read_text());r=next(r for r in a['files'] if r['path']==str(path))
    assert hashlib.sha256(path.read_bytes()).hexdigest()==r['sha256'];return r

def main():
    start=time.monotonic();ROOT.mkdir(exist_ok=False)
    inputs=[seal(ASSOC,'RML2018A_LOW_SNR_ASSOCIATION_2026-09-17.json'),seal(PARTIAL,'RML2018A_D10_PARTIAL_2026-09-26.json')]
    with ASSOC.open() as f:rows=list(csv.DictReader(f))
    rows.sort(key=lambda r:int(r['source_row']));paths=sorted({r['raw_path'] for r in rows});assert len(paths)==13 and len(rows)==2496
    design_paths=paths[::2];evaluation_paths=paths[1::2]
    save('plan.json',dict(inputs=inputs,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),features=FEATURES,primary_feature=FEATURES[0],variants=VARIANTS,design_capture_paths=design_paths,evaluation_capture_paths=evaluation_paths,method='Four feature bins from design-only quartiles (linear quantile); each bin chooses largest design correct count; ties prefer raw, then alpha25, then guard; all five rules reported, primary fixed to guard_to_raw_rms; no outcome-based feature selection',limitations='All members previously analyzed; same campaign, capture/SNR/time confounding; exploratory capture-disjoint reanalysis, not new independent test or trained recognizer',sinr='raw conditional estimated SINR used only for posthoc stratification, never a selector input',budget=dict(seconds=120,host_bytes=512*1024**2,output_bytes=16*1024**2,free_bytes=shutil.disk_usage(ROOT).free),model_inference=False,rf=False,production_changes=False))
    assert shutil.disk_usage(ROOT).free>64*1024**2
    with np.load(PARTIAL) as f:p={k:f[k] for k in f.files}
    ids=np.array([int(r['source_row']) for r in rows]);truth=p['truth'];assert np.array_equal(ids,p['source_row'])
    assert np.array_equal([int(r['truth']) for r in rows],truth) and np.array_equal([int(r['validation_rank']) for r in rows],p['validation_rank'])
    design=np.array([r['raw_path'] in design_paths for r in rows]);evaluation=~design;assert design.sum()==1344 and evaluation.sum()==1152
    pred=np.stack([p[k+'_logits'].argmax(1) for k in VARIANTS],axis=1);good=pred==truth[:,None]
    sinr=np.array([float(r['raw_conditional_sinr_db']) for r in rows]);sb=np.where(np.isfinite(sinr),np.searchsorted(EDGES,sinr,side='right'),10)
    values={k:np.array([float(r[k]) for r in rows]) for k in FEATURES};assert all(np.isfinite(v).all() for v in values.values())
    rules={};routing={};bin_tables=[]
    # Only design indices participate in the boundary and action computation.
    for name,v in values.items():
        cuts=np.quantile(v[design],[.25,.5,.75],interpolation='linear');assert np.all(np.diff(cuts)>0)
        b=np.searchsorted(cuts,v,side='right');counts=np.array([good[design&(b==i)].sum(0) for i in range(4)])
        actions=counts.argmax(1);chosen=actions[b];routing[name]=chosen
        rules[name]=dict(cuts=cuts.tolist(),actions=[VARIANTS[a] for a in actions],design_correct_counts=counts.tolist())
        for split,m in [('design',design),('evaluation',evaluation)]:
            for i in range(4):
                take=m&(b==i);n=int(take.sum());bin_tables.append(dict(feature=name,split=split,feature_bin=i,rows=n,correct={k:int(good[take,j].sum()) for j,k in enumerate(VARIANTS)},selected_action=VARIANTS[actions[i]],guard_minus_raw_pp=100*int((good[take,2].astype(int)-good[take,0]).sum())/n if n else None))
    # Seal choices before producing evaluation summaries.
    save('rules.json',rules)
    allpred={k:pred[:,i] for i,k in enumerate(VARIANTS)}
    allpred.update({k:pred[np.arange(len(ids)),v] for k,v in routing.items()})
    results=[]
    for split,m in [('design',design),('evaluation',evaluation)]:
        masks={'overall':m,'raw_sinr_below0':m&np.isfinite(sinr)&(sinr<0)}
        masks.update({label:m&(sb==i) for i,label in enumerate(LABELS)})
        for label,take in masks.items():
            n=int(take.sum());r=dict(split=split,raw_reference_sinr_bin=label,rows=n,correct={},accuracy={})
            for name,pr in allpred.items():
                c=int((pr[take]==truth[take]).sum());r['correct'][name]=c;r['accuracy'][name]=100*c/n if n else None
            results.append(r)
    capture=[]
    for path in paths:
        take=np.array([r['raw_path']==path for r in rows]);capture.append(dict(path=path,split='design' if path in design_paths else 'evaluation',rows=int(take.sum()),correct={k:int((pr[take]==truth[take]).sum()) for k,pr in allpred.items()}))
    save('results.json',dict(primary_feature=FEATURES[0],groups=results,feature_bins=bin_tables,captures=capture,elapsed_seconds=time.monotonic()-start))
    np.savez(ROOT/'joined.npz',source_row=ids,truth=truth,validation_rank=p['validation_rank'],design=design,raw_sinr_db=sinr,capture_index=np.array([paths.index(r['raw_path']) for r in rows]),**{'feature_'+k:v for k,v in values.items()},**{'prediction_'+k:v for k,v in allpred.items()},**{'action_'+k:v for k,v in routing.items()})
    with (ROOT/'sinr-table.csv').open('w') as f:
        fields=['split','raw_reference_sinr_bin','rows',*allpred.keys()];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in results:w.writerow({k:r[k] for k in fields[:3]}|r['accuracy'])
    # Independent scalar application: design-only counts, rules, then evaluation predictions.
    for name,v in values.items():
        rule=rules[name];cuts=rule['cuts'];scalar_bins=[sum(float(value)>=cut for cut in cuts) for value in v]
        for i,action in enumerate(rule['actions']):
            selected=[j for j,b in enumerate(scalar_bins) if b==i and design[j]]
            cs=[sum(int(pred[j,k])==int(truth[j]) for j in selected) for k in range(3)]
            assert cs==rule['design_correct_counts'][i] and VARIANTS[cs.index(max(cs))]==action
        scalar=[int(pred[j,VARIANTS.index(rule['actions'][b])]) for j,b in enumerate(scalar_bins)]
        assert np.array_equal(scalar,allpred[name])
    for r in results:
        bounds=[-np.inf,*EDGES,np.inf];splitmask=design if r['split']=='design' else evaluation;label=r['raw_reference_sinr_bin']
        if label=='overall':mask=splitmask
        elif label=='raw_sinr_below0':mask=splitmask&np.isfinite(sinr)&(sinr<0)
        elif label=='invalid':mask=splitmask&~np.isfinite(sinr)
        else:i=LABELS.index(label);mask=splitmask&np.isfinite(sinr)&(sinr>=bounds[i])&(sinr<bounds[i+1])
        assert r['rows']==int(mask.sum())
        for name,pr in allpred.items():assert r['correct'][name]==sum(int(pr[j])==int(truth[j]) for j in np.flatnonzero(mask))
    save('verification.json',dict(passed=True,design_rows=int(design.sum()),evaluation_rows=int(evaluation.sum()),capture_disjoint=not(set(design_paths)&set(evaluation_paths)),rules_verified=len(rules),groups_verified=len(results),method='scalar bin/rule reproduction with design-only labels, independent interval masks',independent_test=False))
    os.environ['MPLCONFIGDIR']=str(ROOT/'cache/matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(13,5));names=['raw','alpha25','guard',FEATURES[0]]
    for ax,split in zip(axes,['design','evaluation']):
        q=[r for r in results if r['split']==split and r['raw_reference_sinr_bin'] in LABELS[:8]]
        for name in names:ax.plot(np.arange(-22.5,15,5),[r['accuracy'][name] if r['rows'] else np.nan for r in q],marker='.',label=name)
        ax.set(title=split+' capture files',xlabel='Raw-reference conditional estimated SINR bin center (dB)',ylabel='Accuracy (%)');ax.legend(fontsize=8);ax.grid(alpha=.2)
    fig.suptitle('D10 receiver-feature routing: exploratory reanalysis of prior diagnostic members\nPrimary: guard/raw RMS ratio; lower open bin at -22.5 dB; not an independent test')
    fig.tight_layout();fig.savefig(ROOT/'receiver-routing.png',dpi=160);plt.close(fig)
    assert time.monotonic()-start<120 and resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024<512*1024**2
    assert sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())<16*1024**2
    print(json.dumps([r for r in results if r['raw_reference_sinr_bin'] in ['overall','raw_sinr_below0']]))
    print(json.dumps(rules))

if __name__=='__main__':main()
