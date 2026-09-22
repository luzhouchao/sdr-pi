#!/usr/bin/env python3
"""Independent count/interval and same-member verification of the D10 report."""
import json
from pathlib import Path
import numpy as np
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-common-20260922')
PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-sinr-stratification-20260922')

def main():
    report=json.loads((ROOT/'results.json').read_text())
    with np.load(PARENT/'joined-predictions.npz') as f:data={k:f[k] for k in f.files}
    y=data['truth'];pred={};edges=[-np.inf,-20,-15,-10,-5,0,5,10,15,20,np.inf]
    labels=['<-20','[-20,-15)','[-15,-10)','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20','invalid']
    def mask(plane,label):
        x=data[plane+'_sinr_db'];i=labels.index(label)
        return ~np.isfinite(x) if i==10 else np.isfinite(x)&(x>=edges[i])&(x<edges[i+1])
    for model in report['models']:
        pred[model]={}
        for plane in ('raw','guard'):
            if model.startswith('amc_mamba_d10'):
                with np.load(ROOT/(plane+'-predictions.npz')) as f:
                    for key in ('source_row','truth','validation_rank'):assert np.array_equal(f[key],data[key])
                    assert np.isfinite(f['logits']).all();pred[model][plane]=f['logits'].argmax(1)
                    assert np.array_equal(pred[model][plane],f['predicted_class'])
            else:pred[model][plane]=data[model+'_'+plane]
    for r in report['paired']:
        m=mask('raw',r['raw_reference_sinr_bin']);a=pred[r['model']]['raw'][m]==y[m];b=pred[r['model']]['guard'][m]==y[m]
        assert r['rows']==int(m.sum()) and r['raw_correct']==int(a.sum()) and r['guard_correct']==int(b.sum())
        assert r['corrected']==int((~a&b).sum()) and r['regressed']==int((a&~b).sum())
        if m.any():assert abs(r['change_pp']-100*(b.mean()-a.mean()))<1e-10
    for r in report['own']:
        m=mask(r['plane'],r['sinr_bin']);assert r['rows']==int(m.sum()) and r['correct']==int((pred[r['model']][r['plane']][m]==y[m]).sum())
    for r in report['overall']:
        for plane in ('raw','guard'):assert r[plane+'_correct']==int((pred[r['model']][plane]==y).sum())
    assert len(report['models'])==8 and 'amc_mamba_d8-seed42' not in report['models']
    result=dict(passed=True,rows=len(y),paired_rows=len(report['paired']),own_rows=len(report['own']),method='independent interval masks, joined IDs/ranks/truth and logits argmax',no_source=True)
    (ROOT/'independent-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(result)

if __name__=='__main__':main()
