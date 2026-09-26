#!/usr/bin/env python3
"""One frozen CNN2 reference on byte-identical D10 synthetic inputs."""
import argparse,json,hashlib,signal,shutil
from pathlib import Path
import numpy as np
import rml2018a_d10_synthetic_randomized as generator

ev=generator.ev
PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-synthetic-randomized-20260926')


def main(out):
    ev.require(out.resolve()==out and out.parent==Path('/var/tmp/sdrharness-dev'),'canonical output');out.mkdir(exist_ok=False)
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('600s budget')));signal.alarm(600)
    audit=json.loads((ev.REPO/'docs/evidence/RML2018A_SYNTHETIC_RANDOMIZED_2026-09-26.json').read_text())
    for rec in audit['files']:ev.identity(rec['path'],rec['sha256'])
    parentplan=json.loads((PARENT/'plan.json').read_text())
    for rec in parentplan['identities']:ev.identity(rec['path'],rec['sha256'])
    manifest=json.loads((ev.COLLECTION/'manifest.json').read_text())
    spec=next(v for v in manifest['models'] if v['variant']=='baseline_cnn2_stable' and v['seed']==42)
    identities=[ev.identity(__file__),ev.identity(generator.__file__),ev.identity(ev.__file__),ev.identity(ev.COLLECTION/'manifest.json')]
    for rec in manifest['transferred_files']:
        if rec['relative'].startswith(('source/','baseline_cnn2_stable/seed42/')):
            identities.append(ev.identity(ev.COLLECTION/rec['relative'],rec['sha256']))
    labels=json.loads((ev.REPO/'jetson-agx/sdrharness/config/amc/rml2018a-labels.server-v1.json').read_text())['classes']
    ev.require(spec['class_order']==labels,'reference class order')
    ev.require(shutil.disk_usage(out).free>1024**3,'disk budget')
    ev.atomic(out/'plan.json',dict(schema='synthetic-cnn2-reference-v1',identities=identities,spec=spec,parent=str(PARENT),parent_predictions=ev.identity(PARENT/'predictions.npz'),
        rows=3200,seconds=600,gpu_bytes=4*1024**3,cache=str(ev.cache_root(out)),precision='FP32 TF32 off',
        selection='CNN2-stable seed42 selected before outcomes; conventional architecture contrast, no model sweep',
        preprocessing='Exact regenerated D10 unit-RMS tensors; no additional normalization or tuning',no_rf=True,no_training=True,no_production=True))
    x,rows=generator.inputs();oldinput=json.loads((PARENT/'inputs.json').read_text())
    ev.require(rows==oldinput['rows'] and hashlib.sha256(x.tobytes()).hexdigest()==oldinput['sha256'],'exact D10 input hash')
    truth=np.array([r['truth'] for r in rows]);old=np.load(PARENT/'predictions.npz',allow_pickle=False)
    ev.require(np.array_equal(truth,old['truth']),'paired labels');d10=old['logits'].argmax(1)
    ev.atomic(out/'inputs.json',dict(sha256=oldinput['sha256'],shape=list(x.shape),rows_parent=ev.identity(PARENT/'inputs.json')))
    torch=ev.setup(out);model=ev.load_model(spec,torch);probe=np.arange(0,3200,64)
    batch=ev.predict(model,x[probe],torch,'fp32');single=np.concatenate([ev.predict(model,x[i:i+1],torch,'fp32') for i in probe])
    ev.require(np.allclose(batch,single,atol=2e-4,rtol=2e-4) and np.array_equal(batch.argmax(1),single.argmax(1)),'reference numerical gate')
    outputs=[]
    for a in range(0,3200,128):
        ev.require(not (out/'STOP').exists(),'STOP');outputs.append(ev.predict(model,x[a:a+128],torch,'fp32'))
    logits=np.concatenate(outputs);pred=logits.argmax(1)
    ev.require(np.allclose(logits[probe],single,atol=2e-4,rtol=2e-4) and np.array_equal(pred[probe],single.argmax(1)),'actual batch gate')
    np.savez(out/'predictions.npz',truth=truth,logits=logits)
    def summary(mask):
        a=d10[mask]==truth[mask];b=pred[mask]==truth[mask]
        return dict(rows=int(mask.sum()),d10_correct=int(a.sum()),cnn2_correct=int(b.sum()),both_correct=int((a&b).sum()),both_wrong=int((~a&~b).sum()),cnn2_only=int((~a&b).sum()),d10_only=int((a&~b).sum()),prediction_agreement=int((d10[mask]==pred[mask]).sum()))
    groups=[]
    for a in range(0,3200,64):
        r=rows[a];mask=np.zeros(3200,bool);mask[a:a+64]=True
        groups.append(dict(label=r['label'],sps=r['sps'],variant=r['variant'],**summary(mask),cnn2_counts=np.bincount(pred[mask],minlength=24).tolist()))
    ev.require(torch.cuda.max_memory_allocated()<4*1024**3,'GPU budget')
    for rec in identities:ev.unchanged(rec)
    result=dict(overall=summary(np.ones(3200,bool)),by_class={label:summary(truth==cls) for label,cls in generator.s.LABELS.items()},groups=groups,
        strict_load=True,backend=model.encoder.backend,parameters=sum(p.numel() for p in model.parameters()),numerical_rows=len(probe),numerical_max_abs=float(abs(batch-single).max()),gpu_bytes=torch.cuda.max_memory_allocated())
    ev.atomic(out/'results.json',result);signal.alarm(0)
    print(json.dumps(result['by_class']),flush=True)
    print(json.dumps(result['overall']),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);main(ap.parse_args().out)
