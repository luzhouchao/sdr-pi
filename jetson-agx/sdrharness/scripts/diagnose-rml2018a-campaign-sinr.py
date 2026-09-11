#!/usr/bin/env python3
"""Versioned offline quality recheck of two retained2455MHz batches; no RF/model."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np

import rml2018a_campaign as c


def analyze(root):
    read=lambda p:json.loads(p.read_text())
    plan=read(root/'run-plan.json')
    c.require(plan['rf']['center_hz']==c.CENTER and plan['rf']['rate_sps']==c.RATE and
              plan['rf']['bandwidth_hz']==c.BW,'archive RF identity')
    dataset=Path(plan['source']['path']);stat=dataset.stat()
    c.require(stat.st_size==plan['source']['bytes'] and stat.st_mtime_ns==plan['source']['mtime_ns'],'source identity')
    results=[]
    for index in (4267,22016):
        batch=root/f'batch-{index:07d}'
        audit=read(batch/'audit.json');done=read(batch/'capture-complete.json');source=read(batch/'source.json')
        c.require(c.file_hash(batch/'audit.json')==done['audit_sha256'],'audit seal')
        c.require(source['rows']==done['rows']==c.batch_rows(2555904,index),'row membership')
        path=Path(audit['seal']['iq_path']);data=path.read_bytes()
        c.require(len(data)==c.RX_SAMPLES*4 and c.digest(data)==audit['seal']['iq_sha256'],'IQ seal')
        v=np.frombuffer(data,dtype='<i2').reshape(-1,2);raw=v[:,0].astype(float)+1j*v[:,1]
        with h5py.File(dataset,'r') as h5:
            iq=h5['X'][source['rows']];z=h5['Z'][source['rows']].ravel()
        c.require(c.digest(iq.tobytes())==source['original_iq_sha256'] and
                  z.tolist()==source['source_snr_db'],'source rows/Z')
        frame,_=c.packet(iq,plan['run_id'],index)
        c.require(c.digest(frame.tobytes())==audit['tx_plan']['payload_sha256'],'TX frame')
        status='sync_failed';received=None;sync=None;error=None
        try:
            received,sync=c.synchronize(raw,plan['run_id'],index,len(iq));status='synchronized'
        except ValueError as e:error=str(e)
        quality=[dict(row=row,source_snr_db=int(z[k]),**c.receive_quality(status,
            iq[k,:,0]+1j*iq[k,:,1],None if received is None else received[k],float(z[k])))
            for k,row in enumerate(source['rows'])]
        for q in quality:c.validate_receive_quality(q,q['source_snr_db'])
        results.append(dict(batch=index,parent_audit_sha256=done['audit_sha256'],iq_sha256=c.digest(data),
            source_iq_sha256=source['original_iq_sha256'],request_id=audit['seal']['request_id'],
            session_generation=audit['seal']['session_generation'],original_status=audit['status'],
            original_sync_error=audit.get('sync_error'),status=status,sync=sync,sync_error=error,rows=quality))
    return dict(schema='rml2018a-sinr-recheck-v1',root=str(root),run_id=plan['run_id'],
        parent_plan_sha256=c.file_hash(root/'run-plan.json'),script_sha256=c.file_hash(__file__),
        estimator_script_sha256=c.file_hash(c.__file__),contract=c.sinr_contract(),
        new_rf_captures=0,model_inferences=0,recognizer_available=False,
        semantics='post-hoc fixed carrier-scaled CFO search; original failures preserved; conditional effective SINR only',results=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(analyze(args.root),indent=2,allow_nan=False))
