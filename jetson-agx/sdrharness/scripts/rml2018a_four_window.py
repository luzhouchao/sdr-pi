"""Four-window replay from immutable RX IQ and original correction parameters.

Grouping is positional (four adjacent payloads inside a16-payload TX frame).
Class/Z are checked for experimental attribution, never used to select rows.
"""
import json
from pathlib import Path
import h5py
import numpy as np
import rml2018a_campaign as c

METHOD='four-window-capture-rms-replay-v1'
DATA=c.REPO/'local-assets/amc-eval/datasets/rml2018a/RML2018a.hdf5'
DATA_SHA='e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38'
TAGS=('source','raw','guard')


def shared_rms(z):
    c.require(z.ndim==2 and z.shape[1]==1024 and len(z)%4==0 and np.isfinite(z).all(),'four finite windows')
    raw=np.ascontiguousarray(np.stack((z.real,z.imag),axis=1),dtype=np.float32).reshape(-1,4,2,1024)
    rms=np.sqrt(np.mean(np.square(raw,dtype=np.float64),axis=(1,2,3))*2)
    c.require(np.isfinite(rms).all() and (rms>0).all(),'positive group RMS')
    value=np.ascontiguousarray((raw/rms[:,None,None,None]).reshape(-1,2,1024),dtype=np.float32)
    power=np.mean(np.square(value.reshape(-1,4,2,1024),dtype=np.float64),axis=(1,2,3))*2
    c.require(np.all(abs(np.sqrt(power)-1)<1e-6),'shared four-window RMS')
    return value


def raw_path(group):
    root=Path(group['root']);config=json.loads((root/'configuration.json').read_text())
    return Path(config.get('raw_parent',{}).get('root',str(root)))/'raw.sigmf-data'


def restore(group,number,data):
    rows,ids,old_inputs,masks,quality=data
    c.require(all(v.all() for v in masks.values()),'this full replay requires the sealed fully received corpus')
    c.require(len(rows)==1024 and np.all(np.diff(rows.reshape(-1,4),axis=1)==1) and
              np.all(ids.reshape(-1,4)==ids.reshape(-1,4)[:,:1]),'adjacent same-class four-row groups')
    root=Path(group['root']);config=json.loads((root/'configuration.json').read_text())
    parent=root.parent;frame_block=number+96*config['campaign_snrs'].index(group['snr'])
    frames=json.loads((parent/'frames'/f'{frame_block:03d}.json').read_text())
    c.require(len(frames)==64,'64 saved frame records')
    with h5py.File(root/'processed.h5','r') as f:
        b=f['blocks'][f'{number:03d}'];starts=b['raw_sample_start'][:];counts=b['raw_sample_count'][:]
    c.require(np.all(counts==1024) and np.all(np.diff(starts.reshape(-1,4),axis=1)==1024),
              'four adjacent RX windows; no guard/frame crossing')
    received=np.empty((1024,1024),np.complex128);guarded=np.empty_like(received)
    with raw_path(group).open('rb') as f:
        for k,frame in enumerate(frames):
            begin=k*16;info=frame['guard'];start=int(starts[begin])
            c.require(start==frame['marker_offset']+1024 and
                      np.array_equal(starts[begin:begin+16],start+np.arange(16)*1024),'frame payload offsets')
            digest=c.digest(json.dumps(info,sort_keys=True).encode())
            for q in quality[begin:begin+16]:
                sync=q['sync']
                c.require(q['guard_diagnostics_sha256']==digest and sync['frame']==frame['frame'] and
                          sync['cfo_hz']==frame['cfo_hz'] and sync['phase_rotation_rad']==frame['phase_rotation_rad'],
                          'saved correction/synchronization identity')
            f.seek(start*4);payload=f.read(16*1024*4);c.require(len(payload)==16*1024*4,'complete saved raw payload')
            iq=np.frombuffer(payload,dtype='<i2').reshape(-1,2);z=iq[:,0].astype(np.float64)+1j*iq[:,1]
            positions=start+np.arange(len(z));rotation=np.exp(-2j*np.pi*frame['cfo_hz']*positions/c.RATE+1j*frame['phase_rotation_rad'])
            received[begin:begin+16]=(z*rotation).reshape(16,1024)
            c.require(info['status'] in ('applied','skipped'),'saved correction status')
            if info['status']=='applied':
                v=info['v1'];amplitude=complex(v['amplitude_real'],v['amplitude_imag'])
                local_positions=positions-(frame['marker_offset']-256)
                z=z-amplitude*np.exp(2j*np.pi*v['frequency_hz']*local_positions/c.RATE)
            guarded[begin:begin+16]=(z*rotation).reshape(16,1024)
    with h5py.File(DATA,'r') as f:
        x=f['X'][int(rows[0]):int(rows[-1])+1]
        c.require(x.shape==(1024,1024,2) and np.array_equal(f['Y'][int(rows[0]):int(rows[-1])+1].argmax(1),ids)
                  and np.all(f['Z'][int(rows[0]):int(rows[-1])+1]==group['snr']),'original source X/Y/Z')
    source=x[:,:,0].astype(np.float64)+1j*x[:,:,1]
    restored=dict(source=source,raw=received,guard=guarded);max_errors={}
    for tag,z in restored.items():
        norm=np.stack((z.real,z.imag),axis=1)/np.sqrt(np.mean(abs(z)**2,axis=1))[:,None,None]
        delta=float(np.max(abs(norm.astype(np.float32)-old_inputs[tag])))
        c.require(delta<=1e-5,'reconstructed single-window parity before shared RMS')
        max_errors[tag]=delta
    inputs={tag:shared_rms(z) for tag,z in restored.items()}
    return inputs,dict(method=METHOD,frame_file=str(parent/'frames'/f'{frame_block:03d}.json'),
                       max_single_window_input_error=max_errors,
                       shared_input_sha256=c.digest(b''.join(inputs[t].tobytes() for t in TAGS)))


def reduce(rows,ids,logits,masks):
    c.require(len(rows)%4==0 and np.all(np.diff(rows.reshape(-1,4),axis=1)==1) and
              np.all(ids.reshape(-1,4)==ids.reshape(-1,4)[:,:1]),'fixed adjacent group identity')
    valid={t:masks[t].reshape(-1,4).all(1) for t in TAGS}
    means={t:logits[t].reshape(-1,4,24).mean(axis=1,dtype=np.float64) for t in TAGS}
    for t in TAGS:means[t][~valid[t]]=np.nan
    return ids[::4],means,valid


def statistics(rows,ids,logits,masks,quality):
    import rml2018a_snr_infer as m
    group_ids,means,valid=reduce(rows,ids,logits,masks)
    # Keep per-window estimates at their original reference plane. No averaging dB.
    grouped_quality=[{t:dict(rx_sinr_status='not_measured',rx_sinr_reason='four_window_SINR_not_estimated_members_retained')
                      for t in ('raw','guard')} for _ in group_ids]
    result=m.statistics(group_ids,means,valid,grouped_quality)
    for tag in ('raw','guard'):
        counts={}
        for q in quality:
            status=q[tag]['rx_sinr_status'];counts[status]=counts.get(status,0)+1
        result[tag]['member_window_sinr_status']=counts
    return result


def identity(groups):
    raw={}
    for g in groups:
        path=raw_path(g)
        owner=json.loads((path.parent/'index.json').read_text())
        c.require(owner['complete'] and path.is_file(),'sealed raw owner')
        sha=owner['raw_sha256'];c.require(raw.get(str(path),sha)==sha,'shared raw identity')
        raw[str(path)]=sha
    return dict(method=METHOD,source_path=str(DATA),source_sha256=DATA_SHA,raw_sha256=raw,
                grouping='fixed payload positions 0:4,4:8,8:12,12:16; never label-selected',
                normalize='shared RMS over 4096 complex samples; float32 planar before float64 RMS',
                aggregate='float64 arithmetic mean of four logits',group_sinr='not estimated; member estimates in parent HDF5')


def validation(path,campaign):
    import rml2018a_snr_infer as m
    c.require(path is not None,'four-window GPU proof required')
    p=m.read(path/'plan.json');r=m.read(path/'benchmark.json')
    c.require(p['method']==METHOD and p['samples']==864 and p['batch_size']==1024 and
              p['acquisition_sha256']==c.file_hash(campaign/'acquisition-complete.json') and
              p['profile_sha256']==c.file_hash(m.PROFILE),'four-window validation source/scope')
    for name in ('rml2018a_four_window.py','rml2018a_snr_infer.py','rml2018a_infer_batch.py','amc-mamba-worker.py',
                 'amc-rf-v1-runtime.py','validate-rf-aligned-checkpoint.py','validate-rml2018a-four-window.py'):
        c.require(p['software'][str(m.SCRIPTS/name)]==c.file_hash(m.SCRIPTS/name),'four-window proof implementation pin')
    c.require(r['complete'] and r['passed'] and r['joint_top1_mismatches']==0 and
              r['max_abs_logit']<=0.0625 and r['max_abs_softmax']<=0.005 and
              r['peak_reserved_bytes']<=40*1024**3,'four-window GPU compatibility gate')
    return dict(root=str(path),plan_sha256=c.file_hash(path/'plan.json'),benchmark_sha256=c.file_hash(path/'benchmark.json'))
