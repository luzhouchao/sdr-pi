#!/usr/bin/env python3
"""Read-only, finite error attribution for the two sealed post-LO captures."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import time

import h5py
import numpy as np

import rml2018a_campaign as c
import rml2018a_lo_cancellation as lo
import rml2018a_link_diagnostics as diagnostics

BATCHES=(4267,22016)


def read(path):
    return json.loads(Path(path).read_text())


def analyze(parent, cancellation):
    started=time.monotonic()
    spec=importlib.util.spec_from_file_location('residual_runner',Path(__file__).with_name('rml2018a-rf-campaign.py'))
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    p=runner.load_plan(parent);previous=read(cancellation/'prepared.json')
    inventory=read(c.REPO/'docs/evidence/RML2018A_GUARD_LO_CANCELLATION_2026-09-12.json')
    sealed=[f for r in inventory['retained_roots'] for f in r['files'] if f['path']==str(cancellation/'prepared.json')]
    c.require(len(sealed)==1 and c.file_hash(cancellation/'prepared.json')==sealed[0]['sha256'],'sealed cancellation parent')
    c.require(previous['parent']==str(parent) and previous['parent_plan_sha256']==c.file_hash(parent/'run-plan.json'), 'parent association')
    for name,sha in previous['software'].items():c.require(c.file_hash(Path(__file__).with_name(name))==sha,'frozen cancellation software')
    results=[]
    for batch in BATCHES:
        c.require(time.monotonic()-started<180,'diagnostic time budget')
        old=next(v for v in previous['results'] if v['batch']==batch)
        d=parent/f'batch-{batch:07d}';a=read(d/'audit.json');s=read(d/'source.json');done=read(d/'capture-complete.json')
        c.require(a['restored'] and a['status']==done['status']=='synchronized' and
            c.file_hash(d/'audit.json')==done['audit_sha256']==old['parent_audit_sha256'],'sealed restored audit')
        c.require(c.file_hash(d/'source.json')==old['parent_source_sha256'] and
            s['rows']==done['rows']==c.batch_rows(2555904,batch), 'source association')
        raw,seal=runner.native_check(d,read(d/'rx-plan.json'))
        c.require(seal==a['seal']==old['seal'],'native source seal')
        baseline,sync=c.synchronize(raw,p['run_id'],batch,24)
        c.require(sync==a['sync']==old['fixed_sync'],'frozen synchronization')
        corrected,info=lo.cancel(raw,sync)
        c.require(info==old['cancellation'] and info['status']=='applied','exact original cancellation')
        y=lo.payload(corrected,sync)
        with h5py.File(p['source']['path'],'r') as h:
            iq=h['X'][s['rows']];labels=h['Y'][s['rows']].argmax(axis=1);zs=h['Z'][s['rows']].ravel()
        c.require(c.digest(iq.tobytes())==s['original_iq_sha256'] and labels.tolist()==s['class_ids'] and
            zs.tolist()==s['source_snr_db'] and np.all(zs==30),'source X/Y/Z identity')
        frame,scales=c.packet(iq,p['run_id'],batch,level_profile=p['tx_level_profile'])
        c.require(c.digest(frame.tobytes())==read(d/'tx-plan.json')['payload_sha256'] and scales.tolist()==s['scales'],'original transmitted packet')
        # Match the existing SINR reference exactly: original X with one scale.
        # The FC32 transport cast is verified above, but must not silently change
        # the diagnostic baseline relative to the sealed source-X accounting.
        source=iq[...,0].astype(float)+1j*iq[...,1]
        diagnostic_frame=np.concatenate((np.zeros(c.GUARD),
            c.marker(p['run_id'],batch)*(c.packet_peak(p['tx_level_profile'])/.2),
            (source*scales[:,None]).ravel(),np.zeros(c.GUARD)))
        source_indices=c.GUARD+c.MARKER+np.arange(24*1024)
        source_shifts=np.stack([np.roll(diagnostic_frame,k)[source_indices] for k in range(-2,3)],axis=-1).reshape(24,1024,5)
        derivative=np.fft.ifft(np.fft.fft(diagnostic_frame)*(2j*np.pi*np.fft.fftfreq(len(frame))))[source_indices].reshape(24,1024)
        coordinates=(sync['payload_marker_offset']+c.MARKER+np.arange(24*1024)).reshape(24,1024)
        pilot=diagnostics.pilot_timing(corrected,sync,p['run_id'],batch)
        rows=[]
        freq=np.fft.fftfreq(1024,1/c.RATE)
        for k,row_id in enumerate(s['rows']):
            c.require(c.digest(c.normalize_window(y[k]).tobytes())==old['rows'][k]['corrected_input_sha256'],'post-LO input seal')
            reference=iq[k,:,0].astype(float)+1j*iq[k,:,1]
            raw_quality=c.receive_quality('synchronized',reference,baseline[k],30.)
            c.require(raw_quality==old['rows'][k]['raw_quality'],'original quality')
            q=lo.quality(reference,y[k],30.,info)
            c.require(q==old['rows'][k]['post_cancel_quality'],'original post-LO quality')
            record=diagnostics.evaluate(source_shifts[k],derivative[k],y[k],coordinates[k],sync['estimated_cfo_hz'])
            # The scalar diagnostic must reproduce the original cross-fit error.
            accounting=q['rx_sinr_diagnostics'];error=accounting['received_power_adc_squared']*accounting['link_error_power_relative']
            c.require(abs(record['variants']['scalar']['error_power_counts2']-error)<1e-7,'baseline error accounting')
            x=source_shifts[k,:,2];xc=x-x.mean();gain=np.vdot(xc,y[k]-y[k].mean())/np.vdot(xc,xc)
            spectrum=abs(np.fft.fft(y[k]-gain*x))**2
            source_spectrum=abs(np.fft.fft(x))**2
            record.update(row=row_id,source_snr_db=30.,post_lo_rx_sinr_db=q['rx_sinr_db'],
                post_lo_sinr_plane=q['rx_sinr_reference_plane'],
                post_lo_input_sha256=old['rows'][k]['corrected_input_sha256'],
                source_power_within_175khz_fraction=float(source_spectrum[abs(freq)<=175000].sum()/source_spectrum.sum()),
                residual_power_outside_175khz_fraction=float(spectrum[abs(freq)>175000].sum()/spectrum.sum()))
            rows.append(record)
        trend=diagnostics.trends(rows)
        if pilot['status']=='estimated':
            observed=np.array([v['delay_samples'] for v in rows]);predicted=np.array(pilot['predicted_payload_delays_samples'])
            pilot['versus_source_diagnostic_rms_samples']=float(np.sqrt(np.mean((observed-predicted)**2)))
            pilot['versus_source_diagnostic_median_bias_samples']=float(np.median(predicted-observed))
        summaries={}
        for tag in diagnostics.TAGS:
            values=[v['variants'][tag]['error_reduction_db'] for v in rows if v['variants'][tag]['error_reduction_db'] is not None]
            summaries[tag]=dict(total_rows=24,estimated_rows=len(values),invalid_rows=24-len(values),
                error_reduction_median_db=float(np.median(values)) if values else None,
                error_reduction_min_db=min(values) if values else None,error_reduction_max_db=max(values) if values else None,
                at_least3db_rows=sum(v>=3 for v in values),worse_than_scalar_rows=sum(v<0 for v in values),
                error_power_median_counts2=float(np.median([v['variants'][tag]['error_power_counts2'] for v in rows
                    if v['variants'][tag]['error_power_counts2'] is not None])) if values else None)
        results.append(dict(batch=batch,seal=seal,source_iq_sha256=s['original_iq_sha256'],fixed_sync=sync,
            summaries=summaries,timing_trend=trend,pilot_timing=pilot,
            guard_heldout_residual_counts2=info['heldout_error_power_counts2'],
            guard_residual_is_calibrated_noise=False,
            source_175khz_power_fraction_median=float(np.median([v['source_power_within_175khz_fraction'] for v in rows])),
            residual_outside175khz_fraction_median=float(np.median([v['residual_power_outside_175khz_fraction'] for v in rows])),rows=rows))
    return dict(schema=diagnostics.METHOD,contract=diagnostics.contract(),parent=str(parent),
        parent_run_id=p['run_id'],parent_plan_sha256=c.file_hash(parent/'run-plan.json'),
        cancellation_parent=str(cancellation),cancellation_report_sha256=sealed[0]['sha256'],
        source_profile_sha256=p['profile_sha256'],label_map_sha256=p['label_map_sha256'],
        software={name:c.file_hash(Path(__file__).with_name(name)) for name in
            ('diagnose-rml2018a-link-residual.py','rml2018a_link_diagnostics.py','rml2018a_lo_cancellation.py','rml2018a_campaign.py')},
        new_rf_captures=0,new_model_windows=0,new_iq_copies=0,recognizer_available=False,
        source_assisted=True,receiver_correction=False,results=results)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('analyze','verify'))
    p.add_argument('--parent',type=Path,required=True);p.add_argument('--cancellation',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    c.require(a.output.is_absolute() and a.output.resolve()==a.output and
        a.output.parent==Path('/var/tmp/sdrharness-dev') and a.output.name.startswith('rml-link-residual-'),'derived output root')
    if a.command=='analyze':
        c.require(not a.output.exists(),'new derived root required')
        free=shutil.disk_usage(a.output.parent).free;c.require(free>64*1024*1024,'finite output reserve')
        a.output.mkdir(mode=0o700)
        c.save(a.output/'plan.json',dict(parent=str(a.parent),cancellation=str(a.cancellation),
            batches=list(BATCHES),maximum_source_rows=48,maximum_rf_captures=0,maximum_model_windows=0,
            maximum_seconds=180,maximum_result_bytes=16*1024*1024,free_bytes=free,contract=diagnostics.contract()))
        result=analyze(a.parent,a.cancellation)
        c.require(len(json.dumps(result,allow_nan=False).encode())<16*1024*1024,'result byte budget')
        c.save(a.output/'result.json',result)
        print(json.dumps([dict(batch=b['batch'],summaries=b['summaries'],timing_trend=b['timing_trend'],
            pilot_timing=b['pilot_timing'],guard_residual=b['guard_heldout_residual_counts2'],
            source_175khz_fraction=b['source_175khz_power_fraction_median'],
            residual_outside175khz_fraction=b['residual_outside175khz_fraction_median']) for b in result['results']],indent=2))
    else:
        result=analyze(a.parent,a.cancellation)
        c.require(result==read(a.output/'result.json'),'exact deterministic diagnostic replay')
        print(json.dumps(dict(status='verified',source_rows=48,native_iq_seals=2,post_lo_input_hashes=48,
            forward_models=48*len(diagnostics.TAGS),folds=48*len(diagnostics.TAGS)*2,
            new_rf_captures=0,new_model_windows=0,receiver_correction=False)))


if __name__=='__main__':main()
