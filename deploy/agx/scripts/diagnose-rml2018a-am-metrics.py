#!/usr/bin/env python3
"""Fixed four-batch offline AM metric audit; never opens radio or model backends."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import subprocess
import h5py
import numpy as np
import rml2018a_campaign as c
import rml2018a_guard_tone as guard
import rml2018a_lo_cancellation as lo

S=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('am_archive_reader',S/'rml2018a-rf-campaign.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
PARENT=c.REPO/'docs/evidence/RML2018A_REMAINING16_2026-09-12.json'
ROOT=Path('/var/tmp/sdrharness-dev/b210-rml2018a-remaining-20260912')
DERIVED=Path('/var/tmp/sdrharness-dev/rml-timing-multiclass-remaining-20260912')
BATCHES=(17664,79787,84224,88662)
CLASSES=(3,17,18,19)


def structure(z):
    z=np.asarray(z,dtype=np.complex128)
    c.require(z.shape==(1024,) and np.isfinite(z).all(),'finite diagnostic window')
    powers=[float(np.mean(abs(v)**2)) for v in (z,z[:512],z[512:])]
    c.require(min(powers)>0,'nonzero diagnostic halves')
    centered=[float(np.mean(abs(v-v.mean())**2))/p for v,p in zip((z,z[:512],z[512:]),powers)]
    return dict(power=powers[0],window_mean_power_fraction=float(abs(z.mean())**2/powers[0]),
        centered_fraction=centered[0],half_centered_fractions=centered[1:],
        half_power_ratio=max(powers[1:])/min(powers[1:]))


def stats(values):
    return dict(min=float(min(values)),median=float(np.median(values)),max=float(max(values))) if values else None


def software():
    return {str(S/n):c.file_hash(S/n) for n in (Path(__file__).name,'rml2018a_campaign.py',
        'rml2018a_guard_tone.py','rml2018a_lo_cancellation.py','rml2018a-rf-campaign.py')}


def check_root(root):
    c.require(root.is_absolute() and root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev') and
        root.name.startswith('rml-am-metrics-') and root.name.replace('-','').isalnum(),'offline feature root')


def plan(root):
    check_root(root);c.require(not root.exists(),'new offline audit');root.mkdir(mode=0o700)
    p=dict(schema='rml2018a-am-metric-audit-plan-v1',parent=str(PARENT),parent_sha256=c.file_hash(PARENT),
        base_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=c.REPO,text=True).strip(),software=software(),
        batches=list(BATCHES),classes=list(CLASSES),source_rows=96,source_iq_bytes=96*1024*2*4,
        native_captures=4,native_iq_bytes=4*65535*4,new_iq_files=0,new_rf_operations=0,new_model_windows=0,
        ideal_reference_controls=96,deadline_seconds=180,maximum_output_bytes=2*1024*1024,
        reserve_bytes=16*1024*1024,free_bytes=shutil.disk_usage(root).free,
        metrics=['original native/sync/guard/quality and288 model-input/logit associations replay',
            'source/full-window mean and centered-power fractions; two512 half centered fractions/power ratio',
            'identity-link y=X control with unchanged nominal Z and unchanged SINR gates',
            'source/raw/guard confusion and transitions; estimator validity vs recognition cross-tab'],
        restrictions='Descriptive offline audit only; no new filtering, refitting or inference. Window mean is not independently identified carrier power. Invalid SINR remains null. Existing logs/failed rows immutable.')
    c.require(p['free_bytes']>p['reserve_bytes'],'offline disk reserve');c.save(root/'plan.json',p);return p


def analyze(root):
    check_root(root);p=m.document(root/'plan.json')
    c.require(p['software']==software() and p['parent_sha256']==c.file_hash(PARENT) and p['batches']==list(BATCHES),'sealed audit plan')
    parent=m.document(PARENT);files=[v for group in parent['retained_roots'] for v in group['files']]
    for f in files:
        path=Path(f['path']);c.require(path.stat().st_size==f['bytes'] and c.file_hash(path)==f['sha256'],'immutable parent '+str(path))
    archive=m.document(DERIVED/'prepared.json');inference=m.document(DERIVED/'inference.json');run=m.document(ROOT/'run-plan.json')
    c.require(inference['prepared_sha256']==c.file_hash(DERIVED/'prepared.json') and
        archive['parent_plan_sha256']==c.file_hash(ROOT/'run-plan.json') and inference['status']=='completed','parent associations')
    ds=Path(run['source']['path']);stat=ds.stat()
    c.require(stat.st_size==run['source']['bytes'] and stat.st_mtime_ns==run['source']['mtime_ns'],'source stat pin')
    results=[]
    for batch,cid in zip(BATCHES,CLASSES):
        d=ROOT/f'batch-{batch:07d}';a=m.document(d/'audit.json');done=m.document(d/'capture-complete.json');src=m.document(d/'source.json')
        b=next(v for v in archive['results'] if v['batch']==batch)
        c.require(c.file_hash(d/'audit.json')==done['audit_sha256']==b['parent_audit_sha256'] and
            a['restored'] and a['status']==done['status']=='synchronized','captured parent')
        raw,seal=m.native_check(d,m.document(d/'rx-plan.json'));c.require(seal==a['seal']==b['seal'],'native seal')
        received,sync=c.synchronize(raw,run['run_id'],batch,24);c.require(sync==a['sync']==b['sync'],'sync replay')
        corrected,info=guard.cancel(raw,sync);c.require(info==b['guard_correction'] and info['status']=='applied','guard replay')
        guarded=lo.payload(corrected,sync)
        with h5py.File(ds,'r') as h:
            iq=h['X'][src['rows']];labels=h['Y'][src['rows']].argmax(axis=1);zs=h['Z'][src['rows']].ravel()
        c.require(src['rows']==done['rows']==c.batch_rows(2555904,batch) and c.digest(iq.tobytes())==src['original_iq_sha256'] and
            labels.tolist()==src['class_ids'] and np.all(labels==cid) and zs.tolist()==src['source_snr_db'] and np.all(zs==30),'source X/Y/Z')
        frame,scales=c.packet(iq,run['run_id'],batch,level_profile='remaining-high-snr-pilot')
        tx=c.tx_plan(frame,run['run_id'],batch,src['rows'],60,level_profile='remaining-high-snr-pilot')
        c.require(tx==m.document(d/'tx-plan.json') and scales.tolist()==src['scales'],'source packet replay');c.validate_tx(tx,frame.tobytes())
        source=iq[:,:,0]+1j*iq[:,:,1];rows=[]
        for k,row in enumerate(src['rows']):
            old=b['rows'][k];pred=next(v for v in inference['rows'] if v['batch']==batch and v['row']==row)
            c.require(old['row']==row and old['true_id']==pred['true_id']==cid,'prediction row association')
            qualities=dict(raw=c.receive_quality('synchronized',source[k],received[k],30.),guard=guard.quality(source[k],guarded[k],30.,info))
            c.require(qualities==old['quality'],'exact quality replay')
            predictions={}
            for tag,value in dict(source=source[k],raw=received[k],guard=guarded[k]).items():
                sha=c.digest(c.normalize_window(value).tobytes());q=pred['predictions'][tag]
                c.require(sha==old['inputs'][tag]==q['input_sha256'] and len(q['logits'])==24 and
                    np.isfinite(q['logits']).all() and int(np.argmax(q['logits']))==q['id'],'input/logit replay')
                predictions[tag]=q['id']
            ideal=c.receive_quality('synchronized',source[k],source[k],30.)
            c.validate_receive_quality(ideal,30.)
            rows.append(dict(row=row,true_id=cid,source_snr_db=30.,source_structure=structure(source[k]),
                quality=qualities,ideal_link_quality=ideal,predictions=predictions,inputs=old['inputs']))
        summaries={}
        for tag in ('raw','guard'):
            valid=[r for r in rows if r['quality'][tag]['rx_sinr_status']=='estimated'];invalid=[r for r in rows if r not in valid]
            summaries[tag]=dict(total=24,estimated=len(valid),sinr_db=stats([r['quality'][tag]['rx_sinr_db'] for r in valid]),
                invalid_reasons=dict(Counter(r['quality'][tag]['rx_sinr_reason'] for r in invalid)),
                correct_when_estimated=sum(r['predictions'][tag]==cid for r in valid),correct_when_invalid=sum(r['predictions'][tag]==cid for r in invalid),
                minimum_half_centered_fraction_valid=stats([min(r['source_structure']['half_centered_fractions']) for r in valid]),
                minimum_half_centered_fraction_invalid=stats([min(r['source_structure']['half_centered_fractions']) for r in invalid]))
        classification={tag:dict(total=24,correct=sum(r['predictions'][tag]==cid for r in rows),
            prediction_counts=dict(Counter(str(r['predictions'][tag]) for r in rows))) for tag in ('source','raw','guard')}
        result=dict(batch=batch,class_id=cid,class_name=b['class_name'],seal=seal,source_sha256=src['original_iq_sha256'],rows=rows,
            quality=summaries,classification=classification,
            source_mean_power_fraction=stats([r['source_structure']['window_mean_power_fraction'] for r in rows]),
            minimum_half_centered_fraction=stats([min(r['source_structure']['half_centered_fractions']) for r in rows]),
            source_half_power_ratio=stats([r['source_structure']['half_power_ratio'] for r in rows]),
            ideal_link_valid=sum(r['ideal_link_quality']['rx_sinr_status']=='estimated' for r in rows),
            ideal_link_invalid_reasons=dict(Counter(r['ideal_link_quality']['rx_sinr_reason'] for r in rows if r['ideal_link_quality']['rx_sinr_status']!='estimated')),
            source_guard_prediction_agreement=sum(r['predictions']['source']==r['predictions']['guard'] for r in rows),
            both_source_guard_wrong=sum(r['predictions']['source']!=cid and r['predictions']['guard']!=cid for r in rows),
            raw_to_guard=dict(corrected=sum(r['predictions']['raw']!=cid and r['predictions']['guard']==cid for r in rows),
                regressed=sum(r['predictions']['raw']==cid and r['predictions']['guard']!=cid for r in rows)))
        results.append(result)
    report=dict(schema='rml2018a-am-metric-audit-v1',plan_sha256=c.file_hash(root/'plan.json'),parent_sha256=c.file_hash(PARENT),
        parent_files_verified=len(files),source=run['source'],run_id=run['run_id'],rf=run['rf'],
        profile_sha256=archive['profile_sha256'],label_map_sha256=archive['label_map_sha256'],model_identity=inference['model_identity'],
        actual_inference='Archived single1024 source/raw/guard windows;288 hashes checked, no new model calls',results=results,
        source_rows=96,native_captures=4,native_iq_bytes=1048560,model_input_hashes_verified=288,new_model_windows=0,new_rf_operations=0,
        recognizer_available=False,original_records_modified=False,software=software(),contract=c.sinr_contract())
    target=root/'analysis.json'
    if target.exists():c.require(report==m.document(target),'deterministic audit replay')
    else:
        c.require(len(json.dumps(report).encode())<p['maximum_output_bytes']//2,'output size budget');c.save(target,report)
    return {r['class_name']:{k:v for k,v in r.items() if k not in ('rows','seal','source_sha256')} for r in results}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['plan','analyze']);parser.add_argument('--root',type=Path,required=True);a=parser.parse_args()
    def abort(sig,frame):raise RuntimeError('offline audit deadline/cancel')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
    signal.alarm(180)
    print(json.dumps((plan if a.command=='plan' else analyze)(a.root),indent=2))
