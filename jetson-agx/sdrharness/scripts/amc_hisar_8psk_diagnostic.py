#!/usr/bin/env python3
"""Bounded post-hoc Hisar source/ADC audit and diagnostic-only D10 interventions."""
import argparse,asyncio,csv,gc,hashlib,json,os,time
from pathlib import Path
import h5py
import numpy as np
import amc_validation_eval as e
import amc_rrc_transport as r
from gpu_lease import GpuLease

BASE=Path('/home/jetson/sdrharness/local-assets/amc-eval')
PARENT=BASE/'results/matched-source-baseline-20260928'
SINR=BASE/'results/validation-seed42-conditional-sinr-20260928/hisarmod2019/sinr.npz'
RX=BASE/'rf/validation-seed42-20260927/hisarmod2019'
OLD=BASE/'results/validation-seed42-20260927-inference-a2/hisarmod2019'
MID=slice(32,-32)

def unit(z):return z/np.sqrt(np.mean(abs(z)**2,axis=-1,keepdims=True))
def iq(z):return np.stack((z.real,z.imag),axis=1).astype(np.float32)
def quant(x):return np.quantile(np.asarray(x),[0,.05,.5,.95,1]).tolist()
def digest(p):return e.backend.digest(p)
def save(p,j):e.atomic(p,j)
def read(p):return e.read(p)
def power_fraction(z):return np.sum(abs(z[:,MID])**2,axis=1)/np.sum(abs(z)**2,axis=1)
def complex_values(x):return x[:,0].astype(float)+1j*x[:,1].astype(float)

def run(root,scratch):
    assert not root.exists() and root.is_absolute() and root.resolve()==root
    assert e.resource_gate()['available_kib']*1024>12*1024**3
    root.mkdir(mode=0o700);started=time.monotonic()
    parent=read(PARENT/'plan.json');d=next(a for a in parent['datasets'] if a['dataset']=='hisarmod2019')
    spec=next(a for a in parent['models'] if a['dataset']==d['dataset'] and a['variant']=='amc_mamba_d10')
    with np.load(SINR) as f:meta={k:f[k] for k in f.files}
    bad=(meta['class_id']==2)&(meta['reference_bin']==8);assert bad.sum()==411
    targets=np.flatnonzero(bad);batches=np.unique(targets//1024);controls=[]
    for b in batches:
        candidates=np.flatnonzero((meta['class_id']==2)&~bad&(np.arange(len(bad))//1024==b))
        center=np.median(targets[targets//1024==b]);controls.extend(sorted(candidates,key=lambda x:(abs(x-center),x))[:2])
    selected=np.sort(np.r_[targets,controls]);assert len(selected)<=491
    plan=dict(schema='hisar-8psk-diagnostic-v1',posthoc=True,source=str(PARENT/'plan.json'),source_sha256=digest(PARENT/'plan.json'),sinr_sha256=digest(SINR),dataset=d['dataset'],source_file=d['source_path'],source_file_sha256=d['source_sha256'],validation_rows=117000,all_8psk_rows=4488,target_ranks=targets.tolist(),control_ranks=list(map(int,controls)),control_rule='two nearest validation-rank 8PSK non-target members per target batch; no prediction selection',source_audit='all original Hisar seed42 validation rows only',adc_replay_rows=len(selected),maximum_model_forward_rows=8000,deadline_seconds=1800,roi='native samples [32,992), fixed by combined RRC finite support; no performance tuning',views=['matched','raw','guard','ideal_rrc','ideal_no_pilot','guard_middle_zero','source_middle_from_guard','source_plus_dc','guard_minus_dc'],diagnostic_only='Source-assisted interventions localize sensitivity; never deploy, exclude members, modify frozen results or claim independent accuracy gains',new_rf=False,training=False,software={str(Path(__file__).resolve()):digest(__file__),str(Path(r.__file__)):digest(r.__file__),str(Path(e.__file__)):digest(e.__file__)})
    save(root/'plan.json',plan);parents={str(PARENT/'plan.json'):digest(PARENT/'plan.json'),str(SINR):digest(SINR)}
    assert digest(d['source_path'])==d['source_sha256']
    # Direct source-file reading is independent of the production source_values adapter.
    ids=meta['source_row'];x=np.empty((len(ids),2,1024),np.float32)
    with h5py.File(d['source_path']) as f:
        for start in range(0,len(ids),2048):
            end=min(start+2048,len(ids));x[start:end]=f['X'][ids[start:end]]
            assert np.array_equal(np.searchsorted(d['raw_label_values'],f['Y'][ids[start:end]]),meta['class_id'][start:end])
            assert np.array_equal(f['Z'][ids[start:end]],meta['source_snr_db'][start:end])
    probe=e.source_values(d,ids[selected],meta['class_id'][selected],meta['source_snr_db'][selected]);assert np.array_equal(probe,x[selected]);del probe
    fraction=np.empty(len(ids));edge_peak=np.empty(len(ids))
    for start in range(0,len(ids),2048):
        z=complex_values(x[start:start+2048]);fraction[start:start+len(z)]=power_fraction(z);edge_peak[start:start+len(z)]=(abs(z)**2).max(1)/(abs(z)**2).sum(1)
    classes=[]
    for cl,name in enumerate(d['class_names']):
        mask=meta['class_id']==cl;classes.append(dict(class_id=cl,name=name,rows=int(mask.sum()),near_zero_middle_counts={str(t):int((fraction[mask]<t).sum()) for t in (1e-18,1e-12,1e-6)}))
    save(root/'source-audit.json',dict(source_sha256=d['source_sha256'],direct_reader_equal=True,classes=classes,target_middle_fraction=quant(fraction[bad]),other_8psk_middle_fraction=quant(fraction[(meta['class_id']==2)&~bad]),target_peak_energy_fraction=quant(edge_peak[bad]),near_zero_target_overlap=int(((fraction<1e-12)&bad).sum()),near_zero_total=int((fraction<1e-12).sum()),pilot_constellation='QPSK, four phases; marker modulus .2, multiplied by sqrt(10)',target_batches=len(batches),target_frame_position_counts=np.bincount(targets%2,minlength=2).tolist(),source_z_counts={str(k):int(v) for k,v in zip(*np.unique(meta['source_snr_db'][bad],return_counts=True))}))
    # All 8PSK processed members supply waveform controls; ADC replays are bounded above.
    all8=np.flatnonzero(meta['class_id']==2);loc={int(v):i for i,v in enumerate(all8)};picked={int(v):i for i,v in enumerate(selected)}
    src=complex_values(x[all8]);raw=np.empty_like(src);guard=np.empty_like(src);raw_rms=np.empty(len(all8));guard_rms=np.empty(len(all8));cfo=np.empty(len(all8));tonefreq=np.empty(len(all8));margin=np.empty(len(all8));phase=np.empty(len(all8));marker_score=np.empty(len(all8));applied=np.empty(len(all8),bool)
    views={k:np.empty((len(selected),1024),complex) for k in plan['views']};views['matched'][:]=unit(complex_values(x[selected]));replay=[];pilot_energy=[]
    seal=read(RX/'dataset-complete.json');assert digest(RX/'dataset-complete.json')==d['seal_sha256']
    for receipt in seal['batch_receipts']:
        b=receipt['batch'];ranks=all8[all8//1024==b]
        if not len(ranks):continue
        batch=RX/f'batch-{b:05d}';br=read(batch/'batch-complete.json');assert digest(batch/'batch-complete.json')==receipt['sha256']
        for name in ['plan.json','frames.json','corpus/processed.h5']+(['corpus/raw.sigmf-data'] if b in batches else []):
            expected=next(v['sha256'] for v in br['files'] if v['path']==name);assert digest(batch/name)==expected;parents[str(batch/name)]=expected
        bp=read(batch/'plan.json');frames=read(batch/'frames.json')
        adc=np.memmap(batch/'corpus/raw.sigmf-data',dtype='<i2',mode='r').reshape(-1,2) if b in batches else None
        with h5py.File(batch/'corpus/processed.h5') as f:
            group=f['blocks/000']
            for rank in ranks:
                row=int(rank%1024);i=loc[int(rank)];q=json.loads(group['quality_json'][row]);fr=frames[q['sync']['frame']]
                assert int(group['source_row'][row])==int(ids[rank]);assert group['valid/raw'][row] and group['valid/guard'][row]
                raw[i]=complex_values(group['inputs/raw'][row:row+1])[0];guard[i]=complex_values(group['inputs/guard'][row:row+1])[0]
                raw_rms[i]=q['raw']['normalization_rms'];guard_rms[i]=q['guard']['normalization_rms'];cfo[i]=fr['cfo_hz'];phase[i]=fr['phase_rotation_rad'];marker_score[i]=fr['marker_score'];applied[i]=fr['guard']['status']=='applied';tonefreq[i]=fr['guard'].get('frequency_hz',np.nan);margin[i]=fr['guard'].get('maximum_relative_error_margin',np.nan)
                if int(rank) not in picked:continue
                j=picked[int(rank)];start=int(group['raw_sample_start'][row]);count=int(group['raw_sample_count'][row]);assert count==4221 and start==q['first_native_center_rf_sample']-64
                n=np.arange(start,start+count);a=adc[start:start+count].astype(float);a=a[:,0]+1j*a[:,1];rot=np.exp(-2j*np.pi*fr['cfo_hz']*n/r.c.RATE+1j*fr['phase_rotation_rad']);gg=fr['guard'];assert gg['status']=='applied';amp=complex(*gg['amplitude']);removed=amp*np.exp(2j*np.pi*gg['frequency_hz']*n/r.c.RATE)
                rebuilt={t:np.convolve(v*rot,r.taps(),mode='valid')[::4] for t,v in [('raw',a),('guard',a-removed)]}
                errors={t:float(np.max(abs(iq(unit(rebuilt[t][None]))[0]-group['inputs/'+t][row]))) for t in rebuilt};assert max(errors.values())<2e-6
                views['raw'][j]=raw[i];views['guard'][j]=guard[i]
                # ADC DC estimate uses only the fixed interior after subtracting recorded LO.
                adc_dc=np.mean((a-removed)[64+4*32:64+4*992]);dc=np.convolve(adc_dc*rot,r.taps(),mode='valid')[::4]
                views['guard_minus_dc'][j]=unit(rebuilt['guard']-dc)
                corrected=guard[i].copy();corrected[MID]=0;views['guard_middle_zero'][j]=unit(corrected)
                s=views['matched'][j];g=guard[i];gain=np.vdot(g,s)/np.vdot(g,g);mixed=s.copy();mixed[MID]=(g*gain)[MID];views['source_middle_from_guard'][j]=unit(mixed)
                views['source_plus_dc'][j]=unit(s+dc/guard_rms[i]*gain)
                # Whole local frame and its exact QPSK marker; linear ideal RRC, no RF.
                first=int(rank-rank%2);z=complex_values(x[first:first+2]);scales=.2*np.sqrt(10)/np.max(abs(z),axis=1)
                mark=r.c.marker(bp['run_id'],q['sync']['frame'])*np.sqrt(10);native=np.r_[np.zeros(256),mark,(z*scales[:,None]).ravel(),np.zeros(256)]
                no_pilot=native.copy();no_pilot[256:1280]=0
                outputs=[]
                for wave in [native,no_pilot]:
                    y=np.convolve(r.interpolate(wave),r.taps())[128::4];outputs.append(y[1280+int(rank%2)*1024:1280+(int(rank%2)+1)*1024])
                views['ideal_rrc'][j]=unit(outputs[0]);views['ideal_no_pilot'][j]=unit(outputs[1]);delta=outputs[0]-outputs[1];pilot_energy.append(float(np.sum(abs(delta)**2)/np.sum(abs(outputs[0])**2)))
                replay.append(dict(validation_rank=int(rank),batch=int(b),position=int(rank%2),rebuild_max_error=errors,adc_dc_real=float(adc_dc.real),adc_dc_imag=float(adc_dc.imag),dc_fraction=float(np.mean(abs(dc)**2)/np.mean(abs(rebuilt['guard'])**2)),middle_dc_explained_fraction=float(1-np.sum(abs((rebuilt['guard']-dc)[MID])**2)/np.sum(abs(rebuilt['guard'][MID])**2)),pilot_relative_energy=pilot_energy[-1],pilot_middle_max=float(np.max(abs(delta[MID])))))
        if adc is not None:del adc
        save(root/'progress.json',dict(status='waveform_audit',batch=b,of=seal['batches']))
        assert time.monotonic()-started<plan['deadline_seconds']
    del x;gc.collect()
    source_unit=unit(src);fullgain=np.sum(guard.conj()*source_unit,axis=1)/np.sum(abs(guard)**2,axis=1);aligned=guard*fullgain[:,None]
    quantities=dict(validation_rank=all8,source_row=ids[all8],is_target=bad[all8],source_z=meta['source_snr_db'][all8],source_middle_fraction=power_fraction(src),raw_middle_fraction=power_fraction(raw),guard_middle_fraction=power_fraction(guard),raw_rms=raw_rms,guard_rms=guard_rms,cfo_hz=cfo,tone_frequency_hz=tonefreq,guard_error_margin=margin,phase_rotation=phase,marker_score=marker_score,guard_applied=applied,guard_aligned_relative_error=np.sqrt(np.mean(abs(aligned-source_unit)**2,axis=1)),source_guard_coherence=abs(np.sum(source_unit.conj()*guard,axis=1))/1024)
    for tag,z in [('source',source_unit),('raw',raw),('guard',guard)]:
        spectrum=abs(np.fft.fft(z,axis=1))**2;peak=spectrum.argmax(1);quantities[tag+'_peak_frequency_hz']=np.fft.fftfreq(1024,d=4/r.c.RATE)[peak];quantities[tag+'_peak_power_fraction']=spectrum[np.arange(len(z)),peak]/spectrum.sum(1)
        tone=np.exp(-2j*np.pi*cfo[:,None]*np.arange(1024)/(r.c.RATE/4));coeff=np.mean(z[:,MID]*tone[:,MID].conj(),axis=1);quantities[tag+'_middle_dc_tone_fraction']=abs(coeff)**2/np.mean(abs(z[:,MID])**2,axis=1)
    with (root/'waveform-metrics.npz').open('wb') as f:np.savez_compressed(f,**quantities)
    save(root/'adc-replay.json',dict(rows=len(replay),records=replay,parents=parents))
    groups={}
    for name,mask in [('target',bad[all8]),('other_8psk',~bad[all8])]:
        groups[name]={k:quant(v[mask]) for k,v in quantities.items() if v.dtype.kind=='f' and np.isfinite(v[mask]).all()}
    save(root/'waveform-summary.json',groups)
    # Only selected controls/targets reach new inference; all original members remain untouched.
    for path,sha in spec['files'].items():assert digest(path)==sha
    for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR'):
        path=scratch/key;path.mkdir(parents=True,exist_ok=True);os.environ[key]=str(path)
    lease=GpuLease(scratch/'gpu-gate','mamba');token=asyncio.run(lease.acquire(time.monotonic()+10,request='hisar-8psk-diagnostic'));results={};predictions=dict(validation_rank=selected,source_row=ids[selected],class_id=meta['class_id'][selected],is_target=bad[selected]);forward=0
    try:
        e.resource_gate();package=Path(spec['package']);model,torch=e.backend.load_frozen_model(package,read(package/'config.json'),True,d['class_names'])
        for tag,values in views.items():
            pieces=[]
            for start in range(0,len(values),128):
                with torch.inference_mode():logits=model(torch.from_numpy(iq(values[start:start+128])).cuda()).float().cpu().numpy()
                assert np.isfinite(logits).all();pieces.append(logits);forward+=len(logits)
            logits=np.concatenate(pieces);pred=logits.argmax(1);predictions[tag+'_logits']=logits;predictions[tag+'_prediction']=pred
            results[tag]={name:dict(rows=int(mask.sum()),correct=int((pred[mask]==2).sum()),prediction_counts={d['class_names'][int(k)]:int(v) for k,v in zip(*np.unique(pred[mask],return_counts=True))}) for name,mask in [('target',bad[selected]),('control',~bad[selected])]}
            save(root/'progress.json',dict(status='inference',view=tag,forward_rows=forward));e.resource_gate()
        # Full baseline replay against sealed per-row logits, not merely accuracy.
        gates={}
        for tag in ('matched','raw','guard'):
            baseline=[]
            for rank in selected:
                folder=PARENT/'hisarmod2019/amc_mamba_d10' if tag=='matched' else OLD/'amc_mamba_d10';path=folder/f'rows-{int(rank//2048*2048):07d}.npz'
                # cache one shard per view
                if not baseline or previous!=path:
                    assert digest(path)==read(path.with_suffix('.json'))['sha256']
                    with np.load(path) as f:cache=f[tag+'_logits']
                    previous=path
                baseline.append(cache[int(rank%2048)])
            baseline=np.asarray(baseline);got=predictions[tag+'_logits'];assert np.allclose(got,baseline,atol=2e-4,rtol=2e-4) and np.array_equal(got.argmax(1),baseline.argmax(1));gates[tag]=float(np.max(abs(got-baseline)))
        assert forward<=plan['maximum_model_forward_rows']
    finally:lease.release(token);lease.close()
    with (root/'interventions.npz').open('wb') as f:np.savez_compressed(f,**predictions)
    save(root/'complete.json',dict(status='complete',results=results,baseline_max_errors=gates,forward_rows=forward,checkpoint_sha256=spec['files'][str(Path(spec['package'])/'best.pt')],plan_sha256=digest(root/'plan.json'),posthoc=True,diagnostic_only=True,elapsed_seconds=time.monotonic()-started))
    save(root/'progress.json',dict(status='complete'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--scratch',type=Path,required=True);a=p.parse_args();run(a.root,a.scratch)
