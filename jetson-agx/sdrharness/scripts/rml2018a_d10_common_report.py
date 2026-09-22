#!/usr/bin/env python3
"""Plot eight current models on the same full validation receive population."""
import json,csv,os
from pathlib import Path
import numpy as np
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-common-20260922')
PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-sinr-stratification-20260922')

def main():
    assert (ROOT/'complete.json').exists()
    old=json.loads((PARENT/'results.json').read_text())
    models={k:v for k,v in old['models'].items() if k!='amc_mamba_d8-seed42'};models['amc_mamba_d10-seed42']='D10'
    with np.load(PARENT/'joined-predictions.npz') as f:data={k:f[k] for k in f.files}
    y=data['truth'];pred={}
    for name in models:
        pred[name]={}
        for plane in ('raw','guard'):
            if name=='amc_mamba_d10-seed42':
                with np.load(ROOT/(plane+'-predictions.npz')) as f:
                    assert np.array_equal(f['source_row'],data['source_row']) and np.array_equal(f['truth'],y)
                    assert np.isfinite(f['logits']).all() and np.array_equal(f['logits'].argmax(1),f['predicted_class'])
                    pred[name][plane]=f['predicted_class']
            else:pred[name][plane]=data[name+'_'+plane]
    edges=np.array([-20,-15,-10,-5,0,5,10,15,20]);labels=['<-20','[-20,-15)','[-15,-10)','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20','invalid']
    bins={p:np.where(np.isfinite(data[p+'_sinr_db']),np.searchsorted(edges,data[p+'_sinr_db'],side='right'),10) for p in ('raw','guard')}
    paired=[];own=[];overall=[]
    for name,display in models.items():
        a=pred[name]['raw']==y;b=pred[name]['guard']==y
        overall.append(dict(model=name,display=display,rows=len(y),raw_correct=int(a.sum()),guard_correct=int(b.sum()),raw_accuracy=100*a.mean(),guard_accuracy=100*b.mean(),change_pp=100*(b.mean()-a.mean())))
        for i,lab in enumerate(labels):
            m=bins['raw']==i;n=int(m.sum());ca=int(a[m].sum());cb=int(b[m].sum())
            paired.append(dict(population='common369497',model=name,display=display,raw_reference_sinr_bin=lab,rows=n,raw_correct=ca,guard_correct=cb,raw_acc_percent=100*ca/n if n else None,guard_acc_percent=100*cb/n if n else None,change_pp=100*(cb-ca)/n if n else None,corrected=int((~a[m]&b[m]).sum()),regressed=int((a[m]&~b[m]).sum())))
            for plane,c in [('raw',a),('guard',b)]:
                m=bins[plane]==i;n=int(m.sum());correct=int(c[m].sum());own.append(dict(population='common369497',model=name,plane=plane,sinr_bin=lab,rows=n,correct=correct,accuracy=100*correct/n if n else None))
    for rows,key in [(paired,'paired'),(own,'own')]:
        assert [r for r in rows if r['model']!='amc_mamba_d10-seed42']==[r for r in old[key] if r['population']=='common369497' and r['model']!='amc_mamba_d8-seed42']
    result=dict(models=models,overall=overall,paired=paired,own=own,conditional_estimated_sinr=True,source_curve=False)
    (ROOT/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    for name,rows in [('paired-bins',paired),('own-sinr-bins',own),('overall',overall)]:
        with (ROOT/(name+'.csv')).open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    os.environ['MPLCONFIGDIR']=str(ROOT/'cache/matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    centers=np.arange(-22.5,23,5)
    for reference in ('own','raw-reference'):
        fig,axes=plt.subplots(2,4,figsize=(16,8))
        for ax,(name,display) in zip(axes.flat,models.items()):
            for plane in ('raw','guard'):
                rows=[r for r in own if r['model']==name and r['plane']==plane] if reference=='own' else [r for r in paired if r['model']==name]
                key='accuracy' if reference=='own' else plane+'_acc_percent'
                ax.plot(centers,[r[key] if r['rows'] else np.nan for r in rows[:10]],marker='.',label=plane)
            ax.set(title=display,xlabel='SINR bin center (dB)',ylabel='Accuracy (%)',ylim=(0,100));ax.grid(alpha=.2);ax.legend(fontsize=8)
        subtitle='Each plane uses own bins; different members per bin' if reference=='own' else 'Paired members in raw-before-cancellation SINR bins'
        fig.suptitle('8 current models, common 369,497 validation samples: raw / guard\nConditional estimated SINR; '+subtitle+'\nOpen-ended bins plotted at +/-22.5 dB', fontsize=13)
        fig.tight_layout(rect=(0,0,1,.93));fig.savefig(ROOT/(reference+'-sinr-curves.png'),dpi=150);plt.close(fig)
    values=np.array([[r['change_pp'] for r in paired if r['model']==name][:8] for name in models])
    counts=[int((bins['raw']==i).sum()) for i in range(8)]
    fig,ax=plt.subplots(figsize=(11,5));im=ax.imshow(values,cmap='RdBu',vmin=-75,vmax=75,aspect='auto')
    for i in range(8):
        for j in range(8):ax.text(j,i,f'{values[i,j]:+.1f}',ha='center',va='center',fontsize=9)
    ax.set(yticks=range(8),yticklabels=list(models.values()),xticks=range(8),xticklabels=[f'{a}\nn={b}' for a,b in zip(labels,counts)],xlabel='Raw-reference conditional estimated SINR (dB)',title='8 current models, 369,497 paired members: guard minus raw')
    fig.colorbar(im,ax=ax,label='Percentage points');fig.tight_layout();fig.savefig(ROOT/'paired-gain.png',dpi=160);plt.close(fig)
    print(json.dumps(overall[-1]))

if __name__=='__main__':main()
