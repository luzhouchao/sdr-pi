#!/usr/bin/env python3
"""Eight-class finite source/raw/LO/timing comparison; RF remains in campaign CLI."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import signal
import time
import h5py
import numpy as np
import rml2018a_campaign as c
import rml2018a_lo_cancellation as lo
import rml2018a_pilot_timing as timing
import rml2018a_guard_tone as guard

TAGS=('source','raw','lo','timing')


def runner():
    spec=importlib.util.spec_from_file_location('timing_compare_runner',Path(__file__).with_name('rml2018a-rf-campaign.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def software():
    return {name:c.file_hash(Path(__file__).with_name(name)) for name in
        ('compare-rml2018a-pilot-timing.py','rml2018a_pilot_timing.py','rml2018a_lo_cancellation.py','rml2018a_guard_tone.py','compare-rml2018a-wideband.py')}


def prepare(root):
    m=runner();p=m.load_plan(root)
    c.require(p['tx_level_profile'] in ('timing-multiclass-pilot','qam-guard-pilot','qam-rx-gain-pilot'),'registered comparison parent')
    rxgain=p['tx_level_profile']=='qam-rx-gain-pilot'
    qam=p['tx_level_profile'] in ('qam-guard-pilot','qam-rx-gain-pilot')
    batches,classes=(c.RML_GUARD_BATCHES,c.RML_GUARD_CLASSES) if qam else (c.RML_TIMING_BATCHES,c.RML_TIMING_CLASSES)
    tags=('source','raw','lo','guard','timing') if qam else TAGS
    if rxgain:
        batches,classes=c.RML_RXGAIN_BATCHES,c.RML_RXGAIN_CLASSES
        tags=(*tags,'wide_timing')
        wide=m.module('rxgain_wide','compare-rml2018a-wideband.py');fir=wide.taps()
    total=len(batches)*24
    results=[];tensors={}
    for batch,class_id in zip(batches,classes):
        d=root/f'batch-{batch:07d}';a=m.document(d/'audit.json');done=m.document(d/'capture-complete.json');s=m.document(d/'source.json')
        c.require(a['restored'] and c.file_hash(d/'audit.json')==done['audit_sha256'] and a['status']==done['status'],'restored audit')
        c.require(s['rows']==done['rows']==c.batch_rows(2555904,batch),'source association')
        raw,seal=m.native_check(d,m.document(d/'rx-plan.json'));c.require(seal==a['seal'],'native IQ seal')
        peak=float(max(abs(raw.real).max(),abs(raw.imag).max()));c.require(peak<=512,'registered RX headroom')
        try:
            received,sync=c.synchronize(raw,p['run_id'],batch,24)
        except ValueError as e:
            c.require(a['status']=='sync_failed' and str(e)==a['sync_error'],'sync failure replay')
            received=None;sync=None
        else:c.require(a['status']=='synchronized' and sync==a['sync'],'original synchronization')
        cancelled=adjusted=guarded=wide_timing=None
        wide_info=dict(status='skipped',reason='not_synchronized')
        guard_info=dict(status='skipped',reason='not_synchronized')
        lo_info=dict(status='skipped',reason='not_synchronized');timing_info=dict(status='skipped',reason='not_synchronized')
        if received is not None:
            raw_lo,lo_info=lo.cancel(raw,sync)
            cancelled=lo.payload(raw_lo,sync)
            timing_raw,timing_lo_info=raw_lo,lo_info
            if qam:
                timing_raw,guard_info=guard.cancel(raw,sync)
                guarded=lo.payload(timing_raw,sync)
                timing_lo_info=guard_info
            if timing_lo_info['status']=='applied':adjusted,timing_info=timing.correct(timing_raw,sync,p['run_id'],batch)
            else:
                adjusted=(guarded if qam else cancelled).copy();timing_info=dict(status='skipped',reason='LO_not_validated')
            if rxgain:
                wide_timing=adjusted.copy()
                if guard_info['status']=='applied' and timing_info['status']=='applied':
                    n=np.arange(len(raw));rotated=timing_raw*np.exp(-2j*np.pi*sync['estimated_cfo_hz']*n/c.RATE+1j*sync['phase_rotation_rad'])
                    target=sync['payload_marker_offset']+1024+np.arange(24576);slope=timing_info['drift_ppm']/1e6
                    coords=target+(timing_info['offset_samples']+slope*target)/(1-slope)
                    nearest=np.floor(coords+.5).astype(int)
                    if np.all(nearest>=128) and np.all(nearest+128<len(raw)):
                        wide_timing=timing.sample(np.convolve(rotated,fir,mode='same'),coords).reshape(24,1024)
                        wide_info=dict(status='applied',reason=None,filter_sha256=c.digest(fir.astype('<f8').tobytes()))
                    else:wide_info=dict(status='skipped',reason='missing_combined_filter_halo')
                else:wide_info=dict(status='skipped',reason='guard_or_timing_not_validated')
        # Source X/Z and true classes are accessed only after receiver DSP.
        with h5py.File(m.DATASET,'r') as h:
            iq=h['X'][s['rows']];labels=h['Y'][s['rows']].argmax(axis=1);zs=h['Z'][s['rows']].ravel()
        c.require(c.digest(iq.tobytes())==s['original_iq_sha256'] and labels.tolist()==s['class_ids'] and
            zs.tolist()==s['source_snr_db'] and np.all(zs==30) and np.all(labels==class_id),'source X/Y/Z')
        frame,scales=c.packet(iq,p['run_id'],batch,level_profile=p['tx_level_profile'])
        txp=c.tx_plan(frame,p['run_id'],batch,s['rows'],60,level_profile=p['tx_level_profile'])
        c.require(txp==m.document(d/'tx-plan.json') and scales.tolist()==s['scales'],'transmitted source')
        c.validate_tx(txp,frame.tobytes())
        tx=m.document(d/'tx-summary.json')
        c.require(tx['status']=='fed_complete' and tx['bytes_written']==txp['tx_samples']*8 and tx['child_stopped'] and
            tx['payload_sha256']==txp['payload_sha256'] and tx['uhd_log_sha256']==c.file_hash(d/'tx-uhd.log'),'TX receipt')
        source=iq[:,:,0]+1j*iq[:,:,1];parts=dict(source=source,raw=received,lo=cancelled,timing=adjusted)
        if qam: parts=dict(source=source,raw=received,lo=cancelled,guard=guarded,timing=adjusted)
        if rxgain:
            source_filtered=np.convolve(np.tile(frame,3),fir,mode='same')
            offset=len(frame)+c.GUARD+c.MARKER
            control=source_filtered[offset:offset+24576].reshape(24,1024)/scales[:,None]
            errors=np.mean(abs(control-source)**2,axis=1)/np.mean(abs(source)**2,axis=1)
            ratios=np.mean(abs(control)**2,axis=1)/np.mean(abs(source)**2,axis=1)
            c.require(np.all(errors<=.003) and np.all((ratios>=.995)&(ratios<=1.005)),'fixed wideband source fidelity')
            wide_info.update(source_relative_error_max=float(max(errors)),source_power_ratio_min=float(min(ratios)),source_power_ratio_max=float(max(ratios)))
            parts['wide_timing']=wide_timing
        tensors[batch]=parts;rows=[]
        for k,row in enumerate(s['rows']):
            q=c.receive_quality(a['status'],source[k],None if received is None else received[k],30.)
            c.require(all(a['receive_quality'][k][key]==value for key,value in q.items()),'raw quality replay')
            qualities={'raw':q}
            if received is not None:
                qualities['lo']=lo.quality(source[k],cancelled[k],30.,lo_info)
                qualities['timing']=timing.quality(source[k],adjusted[k],30.,timing_info)
                if qam: qualities['guard']=guard.quality(source[k],guarded[k],30.,guard_info)
            else:
                qualities['lo']={**q,'rx_sinr_reference_plane':lo.PLANE}
                qualities['timing']={**q,'rx_sinr_reference_plane':timing.PLANE}
                if qam: qualities['guard']={**q,'rx_sinr_reference_plane':guard.PLANE}
            if qam:
                qualities['timing']['rx_sinr_reference_plane']='received_payload_after_guard_tone_block_margin_and_pilot_timing_before_rms'
            if rxgain:
                wq=c.receive_quality(a['status'],source[k],None if wide_timing is None else wide_timing[k],30.)
                c.validate_receive_quality(wq,30.)
                wq.update(rx_sinr_reference_plane='received_payload_after_guard_wide_timing_before_rms',
                    rx_payload_filter='129-tap Kaiser8 500kHz low-pass plus frozen timing' if wide_info['status']=='applied' else 'none_skipped',
                    rx_wideband_correction=wide_info)
                qualities['wide_timing']=wq
            rows.append(dict(row=row,true_id=class_id,source_snr_db=30.,quality=qualities,
                inputs={tag:None if values is None else c.digest(c.normalize_window(values[k]).tobytes()) for tag,values in parts.items()},
                correlations={tag:None if values is None else float(abs(np.vdot(source[k],values[k]))/
                    max(np.linalg.norm(source[k])*np.linalg.norm(values[k]),1e-30)) for tag,values in parts.items() if tag!='source'}))
        summary={}
        for tag in tags[1:]:
            valid=[v['quality'][tag]['rx_sinr_db'] for v in rows if v['quality'][tag]['rx_sinr_status']=='estimated']
            summary[tag]=dict(total_rows=24,estimated_rows=len(valid),invalid_or_unmeasured_rows=24-len(valid),
                median_db=float(np.median(valid)) if valid else None,min_db=min(valid) if valid else None,
                max_db=max(valid) if valid else None,at_least20db=sum(v>=20 for v in valid))
        results.append(dict(batch=batch,class_id=class_id,class_name=m.document(m.LABELS)['classes'][class_id],
            seal=seal,parent_audit_sha256=done['audit_sha256'],status=a['status'],sync=sync,component_peak_counts=peak,
            lo_cancellation=lo_info,timing_correction=timing_info,quality_summary=summary,
            uhd_tail_markers=a['uhd_tail_markers'],rows=rows))
        if qam: results[-1]['guard_correction']=guard_info
        if rxgain:results[-1]['wideband_correction']=wide_info
    report=dict(schema='rml2018a-eight-class-pilot-timing-comparison-v1',parent=str(root),
        parent_plan_sha256=c.file_hash(root/'run-plan.json'),run_id=p['run_id'],software=software(),
        timing_contract=timing.contract(),lo_contract=lo.contract(),results=results,
        source_rows=total,maximum_model_windows=total*len(tags),maximum_warmups=2,
        profile_sha256=p['profile_sha256'],label_map_sha256=p['label_map_sha256'],recognizer_available=False,
        semantics='Same192 engineering rows in four variants; no model-guided parameter choice or independent accuracy. Raw and post-DSP conditional SINR kept separate.')
    if qam:
        report.update(schema='rml2018a-qam-guard-comparison-v1',guard_contract=guard.contract(),tags=list(tags),
            semantics='Same96 new QAM engineering rows in five variants; v1 failures retained; empirical guard-tone margin and pilot timing are separate post-DSP planes; not independent accuracy.')
    if rxgain:
        report.update(schema='rml2018a-qam-rx-gain-comparison-v1',rx_gain_db=p['rf']['rx_gain_db'],
            semantics='96 unique matched QAM sources per RX gain; six variants; fixed DSP and all failures retained; not independent accuracy.')
    return report,tensors


def infer(root,output):
    m=runner();report,tensors=prepare(root)
    tags=report.get('tags',TAGS);total=report['source_rows'];maximum=report['maximum_model_windows']
    c.require(report==m.document(output/'prepared.json'),'prepared source/software changed')
    c.require(not (output/'inference.json').exists(),'inference already recorded')
    scratch=output/'scratch';scratch.mkdir(mode=0o700,exist_ok=True)
    os.environ.update(TMPDIR=str(scratch),XDG_CACHE_HOME=str(scratch),TRITON_CACHE_DIR=str(scratch/'triton'),
        CUDA_CACHE_PATH=str(scratch/'cuda'),PYTHONDONTWRITEBYTECODE='1')
    multi=m.module('timing_compare_multi','validate-b210-multiclass.py')
    from gpu_lease import GpuLease
    lease=GpuLease(scratch/'gpu-gate','mamba');token=None
    receipt=dict(status='failed',prepared_sha256=c.file_hash(output/'prepared.json'),rows=[],model_windows=0,warmup_windows=0,
        maximum_model_windows=maximum,recognizer_available=False,name_status='provisional',profile_sha256=report['profile_sha256'],
        label_map_sha256=report['label_map_sha256'],semantics=report['semantics'])
    try:
        token=asyncio.run(lease.acquire(time.monotonic()+10,request='eight-class-pilot-timing'))
        with multi.idle_spark_pause(evidence_root=output):
            w=m.module('timing_compare_worker','amc-mamba-worker.py');backend=w.RfV1Backend(m.PROFILE)
            c.require(all(v.dtype==w.torch.float32 for v in backend.model.parameters()),'FP32 weights')
            receipt.update(model_identity=backend.admission_identity,warmup_windows=2)
            end=time.monotonic()+580
            for result in report['results']:
                batch=result['batch'];parts=tensors[batch]
                for k,row in enumerate(result['rows']):
                    entry=dict(batch=batch,row=row['row'],true_id=row['true_id'],predictions={})
                    for tag,values in parts.items():
                        if values is None:entry['predictions'][tag]=None;continue
                        c.require(time.monotonic()<end and receipt['model_windows']<maximum,'inference budget')
                        tensor=c.normalize_window(values[k]);sha=c.digest(tensor.tobytes())
                        c.require(sha==row['inputs'][tag],'actual model input')
                        logits,us=backend.classify_logits(tensor)
                        c.require(np.asarray(logits).shape==(24,) and np.isfinite(logits).all(),'finite logits')
                        entry['predictions'][tag]=dict(id=int(np.argmax(logits)),logits=logits,input_sha256=sha,inference_us=us)
                        receipt['model_windows']+=1
                    receipt['rows'].append(entry)
                print(json.dumps(dict(event='inferred',batch=batch,rows=24)),flush=True)
            del backend
        receipt.update(status='completed',summary={tag:dict(total=total,predicted=sum(v['predictions'][tag] is not None for v in receipt['rows']),
            correct=sum(v['predictions'][tag] is not None and v['predictions'][tag]['id']==v['true_id'] for v in receipt['rows'])) for tag in tags})
    except BaseException as e:receipt['error']=f'{type(e).__name__}: {e}';raise
    finally:
        if token is not None:lease.release(token)
        receipt['lease']=lease.metrics.copy();lease.close();c.save(output/'inference.json',receipt)
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','infer','verify'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    c.require(a.output.is_absolute() and a.output.resolve()==a.output and a.output.parent==Path('/var/tmp/sdrharness-dev') and
        a.output.name.startswith('rml-timing-multiclass-'),'derived output root')
    def abort(sig,frame):raise RuntimeError(f'comparison signal{sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
    signal.alarm(650)
    if a.command=='prepare':
        c.require(not (a.output/'prepared.json').exists(),'new prepared record required')
        a.output.mkdir(mode=0o700,exist_ok=True);report,_=prepare(a.root);c.save(a.output/'prepared.json',report)
        print(json.dumps([dict(batch=v['batch'],name=v['class_name'],lo=v['lo_cancellation']['status'],
            timing=v['timing_correction']['status'],quality=v['quality_summary']) for v in report['results']],indent=2))
    elif a.command=='infer':
        with runner().lock(a.output):
            result=infer(a.root,a.output);print(json.dumps(result['summary']))
    else:
        report,_=prepare(a.root);m=runner();c.require(report==m.document(a.output/'prepared.json'),'deterministic report replay')
        tags=report.get('tags',TAGS);total=report['source_rows']
        receipt=m.document(a.output/'inference.json');c.require(receipt['status']=='completed' and
            receipt['prepared_sha256']==c.file_hash(a.output/'prepared.json') and len(receipt['rows'])==total,'inference receipt')
        count=0;expected=[(b['batch'],r) for b in report['results'] for r in b['rows']]
        for (batch,row),pred in zip(expected,receipt['rows']):
            c.require((batch,row['row'],row['true_id'])==(pred['batch'],pred['row'],pred['true_id']),'prediction association')
            for tag in tags:
                q=pred['predictions'][tag]
                if row['inputs'][tag] is None:c.require(q is None,'missing input');continue
                c.require(q['input_sha256']==row['inputs'][tag] and len(q['logits'])==24 and
                    np.isfinite(q['logits']).all() and int(np.argmax(q['logits']))==q['id'],'prediction/input replay');count+=1
        c.require(count==receipt['model_windows'],'window count')
        for tag in tags:
            c.require(receipt['summary'][tag]==dict(total=total,predicted=sum(v['predictions'][tag] is not None for v in receipt['rows']),
                correct=sum(v['predictions'][tag] is not None and v['predictions'][tag]['id']==v['true_id'] for v in receipt['rows'])),'summary count')
        print(json.dumps(dict(status='verified',source_rows=total,native_captures=len(report['results']),model_input_hashes=count,model_reexecuted=False)))


if __name__=='__main__':main()
