#!/usr/bin/env python3
"""Publication-friendly plots from derived paired SINR counts; no IQ/model access."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TAGS=('source','raw','guard')
COLORS={'source':'#3566aa','raw':'#9c5c37','guard':'#18856d'}
DATASETS=('rml2016a','rml2016b','rml2018a','hisarmod2019')

def panel(ax,bins,title):
    known=bins[:-1];x=np.arange(len(known));n=np.array([b['rows'] for b in known]);invalid=bins[-1]['rows']
    for tag in TAGS:
        y=np.divide([100*b[tag+'_correct'] for b in known],n,out=np.full(len(n),np.nan),where=n>0)
        ax.plot(x,y,'o-',label=tag,linewidth=1.5,markersize=3,color=COLORS[tag])
    ax.set_title(title+f' | invalid={invalid:,}',fontsize=10);ax.set_ylim(0,102);ax.grid(alpha=.2)
    ax.set_xticks(x);ax.set_xticklabels([b['bin'] for b in known],rotation=35,ha='right',fontsize=7)
    ax.set_ylabel('Accuracy (%)');ax.set_xlabel('Raw-reference conditional SINR bin (dB)',fontsize=8)

def finish(fig,root,name):
    fig.suptitle('Same validation members per bin; conditional estimate, not calibrated SINR',fontsize=11)
    fig.tight_layout(rect=(0,0,1,.96))
    fig.savefig(root/(name+'.png'),dpi=180);fig.savefig(root/(name+'.svg'));plt.close(fig)

def run(root):
    reports={d:json.loads((root/d/'report.json').read_text()) for d in DATASETS}
    fig,axes=plt.subplots(2,2,figsize=(13,8))
    for ax,(name,r) in zip(axes.flat,reports.items()):
        model=next(m for m in r['models'] if m['model']=='amc_mamba_d10');panel(ax,model['bins'],name+' / D10')
    axes.flat[0].legend(fontsize=8);finish(fig,root,'d10-paired-sinr')
    fig,ax=plt.subplots(figsize=(10,5));x=np.arange(4)
    invalid=[next(m for m in r['models'] if m['model']=='amc_mamba_d10')['bins'][-1] for r in reports.values()]
    for j,tag in enumerate(TAGS):
        heights=[100*b[tag+'_correct']/b['rows'] if b['rows'] else np.nan for b in invalid]
        ax.bar(x+(j-1)*.24,heights,.24,label=tag,color=COLORS[tag])
    ax.set_xticks(x);ax.set_xticklabels([name+f"\nn={b['rows']:,}" for name,b in zip(DATASETS,invalid)])
    ax.set_ylabel('Accuracy (%)');ax.set_ylim(0,105);ax.legend();ax.grid(axis='y',alpha=.2)
    ax.set_title('D10: unestimated SINR members, kept separate from low/high bins')
    finish(fig,root,'d10-invalid-sinr')
    for name,r in reports.items():
        fig,axes=plt.subplots(2,4,figsize=(19,8))
        for ax,model in zip(axes.flat,r['models']):panel(ax,model['bins'],model['model'].replace('baseline_',''))
        axes.flat[0].legend(fontsize=8);finish(fig,root,name+'-all-models')
    fig,axes=plt.subplots(2,2,figsize=(13,8));r=reports['rml2018a']
    for row,variant in enumerate(('amc_mamba_d10','baseline_mcformer')):
        model=next(m for m in r['models'] if m['model']==variant)
        for col,cid in enumerate((1,18)):
            cls=next(c for c in model['classes'] if c['class_id']==cid)
            panel(axes[row,col],cls['bins'],variant.replace('baseline_','')+' / '+cls['class_name'])
    axes.flat[0].legend(fontsize=8);finish(fig,root,'rml2018a-focus-classes')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
