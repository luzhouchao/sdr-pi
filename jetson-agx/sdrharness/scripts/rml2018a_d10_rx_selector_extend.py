#!/usr/bin/env python3
"""Read-only extension of frozen primary receiver-RMS rule, no threshold tuning."""
import json,hashlib
from pathlib import Path
import numpy as np
import h5py
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-rx-selector-20260926-a2')
COMMON=Path('/var/tmp/sdrharness-dev/rml2018a-d10-alpha25-common-20260926')
BASE=Path('/var/tmp/sdrharness-dev/rml2018a-d10-common-20260922')
REPO=Path(__file__).resolve().parents[3]

def save(n,x):(ROOT/n).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def pin(path,audit):
 a=json.loads((REPO/'docs/evidence'/audit).read_text());r=next(r for r in a['files'] if r['path']==str(path));assert hashlib.sha256(path.read_bytes()).hexdigest()==r['sha256'];return r

def main():
 rules=json.loads((ROOT/'rules.json').read_text());rule=rules['guard_to_raw_rms'];plan=json.loads((ROOT/'plan.json').read_text())
 parents=[pin(COMMON/'members.npz','RML2018A_D10_ALPHA25_COMMON_2026-09-26.json'),pin(COMMON/'alpha25-predictions.npz','RML2018A_D10_ALPHA25_COMMON_2026-09-26.json')]
 parents += [pin(BASE/(p+'-predictions.npz'),'RML2018A_D10_COMMON_2026-09-22.json') for p in ['raw','guard']]
 rec=next(r for r in json.loads((COMMON/'plan.json').read_text())['input_identities'] if '_raw_' in r['path']);st=Path(rec['path']).stat();assert (st.st_size,st.st_mtime_ns)==(rec['bytes'],rec['mtime_ns'])
 save('extension-plan.json',dict(rule=rule,rule_file_sha256=hashlib.sha256((ROOT/'rules.json').read_bytes()).hexdigest(),parents=parents,metadata=rec,primary='remaining members in the six evaluation capture files; exclude all prior2496',secondary='all remaining members and design-capture remaining members',no_threshold_changes=True,no_feature_selection=True,no_new_inference=True,no_rf=True,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
 with np.load(COMMON/'members.npz') as f:m={k:f[k] for k in f.files}
 ids=m['source_row'];y=m['truth'];n=len(ids);remaining=np.ones(n,bool);remaining[m['subset_indices']]=False
 with h5py.File(rec['path']) as f:
  allids=f['source_row'][:];order=np.argsort(allids);rows=order[np.searchsorted(allids[order],ids)];assert np.array_equal(allids[rows],ids)
  filenames=[str(Path('/var/tmp/sdrharness-dev')/Path(v).relative_to('corpus')) for v in f['raw_iq_paths'].asstr()[:]];fileids=f['raw_file_id'][:][rows]
  capture=np.array([filenames[i] for i in fileids]);assert set(capture)==set(plan['design_capture_paths']+plan['evaluation_capture_paths'])
 pred={}
 for name in ['raw','alpha25','guard']:
  with np.load((COMMON if name=='alpha25' else BASE)/(name+'-predictions.npz')) as f:
   assert np.array_equal(ids,f['source_row']) and np.array_equal(y,f['truth']);pred[name]=f['predicted_class']
 ratio=m['guard_rms']/m['raw_rms'];assert np.isfinite(ratio).all() and (ratio>0).all()
 bins=np.searchsorted(rule['cuts'],ratio,side='right');actions=np.array(rule['actions'])[bins]
 chosen=np.array([pred[a][i] for i,a in enumerate(actions)])
 # Equivalent compact rule expected from the sealed design decisions.
 assert rule['actions']==['alpha25','alpha25','guard','guard']
 assert np.array_equal(chosen,np.where(ratio<rule['cuts'][1],pred['alpha25'],pred['guard']))
 pred['rms_selector']=chosen
 design=np.isin(capture,plan['design_capture_paths']);evaluation=np.isin(capture,plan['evaluation_capture_paths']);assert not (design&evaluation).any() and (design|evaluation).all()
 groups={'remaining_evaluation_captures':remaining&evaluation,'remaining_design_captures':remaining&design,'remaining_all':remaining}
 edges=[-np.inf,-20,-15,-10,-5,0,5,10,15,20,np.inf];labels=['<-20','[-20,-15)','[-15,-10)','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20']
 results=[];sinr=m['raw_sinr_db']
 for pop,selected in groups.items():
  masks={'overall':selected,'raw_sinr_below0':selected&np.isfinite(sinr)&(sinr<0)}
  masks.update({lab:selected&np.isfinite(sinr)&(sinr>=edges[i])&(sinr<edges[i+1]) for i,lab in enumerate(labels)});masks['invalid']=selected&~np.isfinite(sinr)
  for label,take in masks.items():
   count=int(take.sum());good={k:v[take]==y[take] for k,v in pred.items()};r=dict(population=pop,raw_reference_sinr_bin=label,rows=count,correct={k:int(v.sum()) for k,v in good.items()},accuracy={k:100*int(v.sum())/count if count else None for k,v in good.items()},alpha25_selected=int((take&(actions=='alpha25')).sum()),guard_selected=int((take&(actions=='guard')).sum()))
   r['corrected_vs_guard']=int((good['rms_selector']&~good['guard']).sum());r['regressed_vs_guard']=int((~good['rms_selector']&good['guard']).sum());assert r['correct']['rms_selector']-r['correct']['guard']==r['corrected_vs_guard']-r['regressed_vs_guard'];assert r['alpha25_selected']+r['guard_selected']==count
   results.append(r)
 captures=[]
 for path in sorted(set(capture)):
  take=remaining&(capture==path);captures.append(dict(path=path,split='evaluation' if path in plan['evaluation_capture_paths'] else 'design',rows=int(take.sum()),correct={k:int((v[take]==y[take]).sum()) for k,v in pred.items()}))
 save('extension-results.json',dict(groups=results,captures=captures,rule=rule,independent_test=False))
 np.savez_compressed(ROOT/'extension-joined.npz',source_row=ids,truth=y,raw_sinr_db=sinr,remaining=remaining,evaluation_capture=evaluation,ratio=ratio,**{'prediction_'+k:v for k,v in pred.items()})
 # Scalar reference over every row, independent of vectorized selection.
 for i,value in enumerate(ratio):
  bin_number=sum(float(value)>=cut for cut in rule['cuts']);assert chosen[i]==pred[rule['actions'][bin_number]][i]
 save('extension-verification.json',dict(passed=True,scalar_rule_rows=n,primary_rows=int(groups['remaining_evaluation_captures'].sum()),remaining_rows=int(remaining.sum()),groups=len(results),old_diagnostic_members_excluded=True,threshold_unchanged=True))
 print(json.dumps([r for r in results if r['raw_reference_sinr_bin'] in ['overall','raw_sinr_below0']]))

if __name__=='__main__':main()
