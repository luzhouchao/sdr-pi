#!/usr/bin/env python3
"""Bounded RX-only background discovery and independent frequency confirmation."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import time
import numpy as np

if not __debug__:raise RuntimeError('validation assertions required')
SCRIPTS=Path(__file__).parent
spec=importlib.util.spec_from_file_location('bg_repair',SCRIPTS/'repair-b210-lo-leakage.py')
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)
live,point=repair.live,repair.point
rf=live.link_tool.rf
ROOT=Path('/var/tmp/sdrharness-dev/b210-background-907n')
CENTERS=(2405000000,2415000000,2425000000,2435000000,2440000000,2455000000,2465000000,2478000000)
SAVE=repair.lo.save


def stats(z):
    z=np.asarray(z,dtype=np.complex128)
    if z.shape!=(65535,) or not np.isfinite(z).all():raise ValueError('complete finite 65535 IQ required')
    filtered=repair.reject(z)
    def segments(v,offset):
        return [dict(raw_start=offset+n,count=min(128,len(v)-n),rms=point.rms(v[n:n+128])) for n in range(0,len(v),128)]
    raw_rows=segments(z,0);filtered_rows=segments(filtered,128)
    def distribution(rows):
        values=np.array([r['rms'] for r in rows]);p=np.percentile(values,[50,95,99])
        return dict(p50=float(p[0]),p95=float(p[1]),p99=float(p[2]),maximum=float(max(values)))
    events=[]
    for row in raw_rows:
        if row['rms']<=20:continue
        end=row['raw_start']+row['count']
        if events and events[-1]['stop']==row['raw_start']:events[-1]['stop']=end
        else:events.append(dict(start=row['raw_start'],stop=end))
    peak=max(raw_rows,key=lambda r:r['rms']);x=z[peak['raw_start']:peak['raw_start']+peak['count']]
    xc=x-x.mean();centered=float(np.mean(abs(xc)**2));total=float(np.mean(abs(x)**2))
    power=abs(np.fft.fft(x*np.hanning(len(x))))**2;frequencies=np.fft.fftfreq(len(x),1/point.RATE)
    return dict(raw_segments=raw_rows,filtered_segments=filtered_rows,raw=distribution(raw_rows),filtered=distribution(filtered_rows),
                events=events,event_line_adc_rms=20.,event_resolution_us=128/point.RATE*1e6,
                peak_segment=dict(start=peak['raw_start'],dc_power_fraction=float(abs(x.mean())**2/max(total,1e-30)),
                   centered_non_circularity=float(abs(np.mean(xc**2))/max(centered,1e-30)),
                   in_175khz_power_fraction=float(power[abs(frequencies)<=175000].sum()/max(power.sum(),1e-30))))


def select_candidate(rows):
    if len(rows)!=24:raise ValueError('three complete discovery rounds required')
    ranking=[]
    for center in CENTERS:
        group=[r for r in rows if r['center_hz']==center]
        if len(group)!=3 or {r['round'] for r in group}!={0,1,2}:raise ValueError('discovery grouping conflict')
        if center==2440000000:continue
        ranking.append(dict(center_hz=center,maximum=max(r['statistics']['filtered']['maximum'] for r in group),
                            p95=max(r['statistics']['filtered']['p95'] for r in group)))
    ranking.sort(key=lambda r:(r['maximum'],r['p95'],r['center_hz']))
    return dict(candidate_hz=ranking[0]['center_hz'],ranking=ranking,selected_from='discovery_only')


def confirmation(rows,candidate):
    if candidate not in CENTERS or candidate==2440000000 or len(rows)!=6:raise ValueError('fixed candidate/six confirmations required')
    selected=[r for r in rows if r['center_hz']==candidate];baseline=[r for r in rows if r['center_hz']==2440000000]
    if len(selected)!=3 or len(baseline)!=3 or any({r['round'] for r in group}!={0,1,2} for group in (selected,baseline)):raise ValueError('confirmation group conflict')
    return dict(candidate_hz=candidate,passed=all(r['statistics']['filtered']['p95']<=5 and r['statistics']['filtered']['maximum']<=8 for r in selected),
                candidate_p95=[r['statistics']['filtered']['p95'] for r in selected],
                candidate_maximum=[r['statistics']['filtered']['maximum'] for r in selected],
                reference_p95=[r['statistics']['filtered']['p95'] for r in baseline],
                reference_maximum=[r['statistics']['filtered']['maximum'] for r in baseline],
                criterion='all three candidate p95<=5 and maxima<=8 ADC; does not replace fresh TX-off controls')


def native(root,plan):
    assert live.document(root/'plan.json')==plan, 'saved plan mismatch'
    report=live.document(root/'report.json');dataset=report['dataset'];center=plan['frequencies']['centers_hz'][0]
    assert center in CENTERS
    assert report['backend']=='agx_iq_software_aggregate' and report['sweep_id']==plan['sweep_id']
    assert report['session_generation']==plan['session_generation'] and len(report['points'])==1
    p=report['points'][0];assert p['rx_input']==live.RX_IDENTITY
    for k,v in dict(point_index=0,requested_center_hz=center,sample_rate_hz=2100000,rf_bandwidth_hz=1500000,
                    captured_samples=65535,dropped_samples=0,overflow=False,clipped_samples=0,status_flags=0,
                    session_generation=plan['session_generation']).items():assert p[k]==v,k
    assert abs(p['actual_center_hz']-center)<=2
    assert p['health']==dict(healthy=True,flags=0,source='iio_adapter')
    assert p['timeout']['timed_out'] is False and p['timeout']['limit_ms']==1000
    assert type(p['request_id']) is int and p['request_id']>0 and type(p['sequence']) is int and p['sequence']>0
    for k,v in dict(sample_rate_hz=2100000,rf_bandwidth_hz=1500000,gain_db=40,settle_ms=500,frame_samples=65535,aggregate_frames=1,point_timeout_ms=1000).items():assert plan[k]==v
    assert dataset['bytes']==262140 and dataset['format']=='sigmf' and dataset['datatype']=='ci16_le'
    data,meta=Path(dataset['data_path']),Path(dataset['metadata_path'])
    assert data.parent==meta.parent==root and list(root.glob('*.sigmf-data'))==[data] and list(root.glob('*.sigmf-meta'))==[meta]
    raw=live.read(data);metadata=live.document(meta);assert len(raw)==262140
    assert metadata['global']['core:sample_rate']==2100000 and metadata['global']['core:datatype']=='ci16_le'
    assert metadata['global']['sdrharness:sample_layout']=='interleaved_iq'
    assert metadata['captures']==[{'core:sample_start':0,'core:frequency':p['actual_center_hz'],'sdrharness:point_index':0,'sdrharness:rf_bandwidth_hz':1500000,'sdrharness:gain_db':40}]
    hashes={str(path):repair.lo.hashlib.sha256(live.read(path)).hexdigest() for path in (data,meta,root/'report.json',root/'plan.json')}
    v=np.frombuffer(raw,dtype='<i2').reshape(-1,2)
    return dict(hashes=hashes,request_id=p['request_id'],sequence=p['sequence'],session_generation=p['session_generation']),v[:,0].astype(float)+1j*v[:,1].astype(float)


async def run(binary):
    assert ROOT.resolve()==ROOT and ROOT.is_dir()
    assert not any(ROOT.glob('capture-*')), 'refusing to reuse existing capture evidence'
    SAVE(ROOT/'started.json',dict(max_rx_bytes=7864200,max_points=30,tx_operations=0,free_bytes=shutil.disk_usage(ROOT).free))
    assert shutil.disk_usage(ROOT).free>=64*1024*1024
    async def command(args,timeout=10,payload=None):
        process=await asyncio.create_subprocess_exec(*map(str,args),stdin=asyncio.subprocess.PIPE if payload is not None else None,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:out,err=await asyncio.wait_for(process.communicate(payload),timeout)
        finally:
            if process.returncode is None:process.kill();await process.wait()
        assert process.returncode==0,err.decode()[-2000:]
        return out.decode()
    before=await command([*rf.SSH,rf.STATE_COMMAND]);state=dict(zip(before.splitlines()[::2],before.splitlines()[1::2]))
    assert all(v=='0' for p,v in state.items() if p.endswith('/enable') or p.endswith('_en'))
    daemon=(await command([*rf.SSH,'pidof sdrd'])).strip();assert len(daemon.split())==1
    connections=await command([*rf.SSH,'netstat -nt 2>/dev/null; true']);assert not any(':30431 ' in l and 'ESTABLISHED' in l for l in connections.splitlines())
    audit=dict(schema_id='b210_background_frequency_v1',radio_before=before,sdrd_pid=daemon,rows=[],status='running',
               controller_sha256=repair.lo.hashlib.sha256(binary.read_bytes()).hexdigest(),recognizer_available=False,model_windows=0,tx_operations=0,independent_labels=0)
    generation=int(time.time()*1000)
    async def capture(phase,round_index,center):
        index=len(audit['rows']);gen=generation+index;root=ROOT/f'capture-{index:02d}';root.mkdir(mode=0o700)
        plan=dict(sweep_id=f'background-{gen}',session_generation=gen,frequencies=dict(kind='centers',centers_hz=[center]),
                  sample_rate_hz=2100000,rf_bandwidth_hz=1500000,gain_db=40,settle_ms=500,frame_samples=65535,aggregate_frames=1,point_timeout_ms=1000,detection_threshold_db=12.)
        SAVE(root/'plan.json',plan)
        sdr_path=f'/tmp/sdr-agent-dev/agx-sweep-{gen}-0'
        print(json.dumps(dict(index=index,phase=phase,plan=plan,max_bytes=262140,estimated_duration_ms=1500,free_bytes=shutil.disk_usage(ROOT).free,agx_directory=str(root),sdr_directory=sdr_path,stop=f'Controller --mode cancel --session-generation {gen}')),flush=True)
        assert shutil.disk_usage(ROOT).free>=262140+8*1024*1024
        process=await asyncio.create_subprocess_exec(str(binary),'--mode','sweep','--sdrd','192.168.1.10:43110','--sigmf-directory',str(root),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            out,err=await asyncio.wait_for(process.communicate(json.dumps(plan).encode()),15)
            (root/'stderr.log').write_bytes(err);assert process.returncode==0,err.decode()[-2000:]
            SAVE(root/'report.json',json.loads(out))
            sealed,raw=native(root,plan)
            row=dict(index=index,phase=phase,round=round_index,center_hz=center,seal=sealed,plan=plan,statistics=stats(raw))
            audit['rows'].append(row)
        except BaseException:
            try:await command([binary,'--mode','cancel','--sdrd','192.168.1.10:43110','--session-generation',gen],timeout=6)
            finally:
                if process.returncode is None:
                    process.terminate()
                    try:await asyncio.wait_for(process.wait(),3)
                    except asyncio.TimeoutError:process.kill();await process.wait()
            raise
        finally:
            after=await command([*rf.SSH,rf.STATE_COMMAND]);assert rf.restored_state(before,after),'radio restoration mismatch'
            await command([*rf.SSH,f'test ! -e {sdr_path}'])
            audit.setdefault('restored_generations',[]).append(gen)
            (ROOT/'progress.json').write_text(json.dumps(audit,indent=2)+'\n')
    try:
        for round_index,centers in enumerate((CENTERS,tuple(reversed(CENTERS)),CENTERS)):
            for center in centers:await capture('discovery',round_index,center)
        selection=select_candidate(audit['rows']);audit['selection']=selection;SAVE(ROOT/'selection.json',selection)
        candidate=selection['candidate_hz']
        for round_index,centers in enumerate(((2440000000,candidate),(candidate,2440000000),(2440000000,candidate))):
            for center in centers:await capture('confirmation',round_index,center)
        audit['confirmation']=confirmation(audit['rows'][24:],candidate)
        audit['status']='completed'
    except BaseException as error:audit['failure']=f'{type(error).__name__}: {error}';audit['status']='failed';raise
    finally:
        audit['radio_after']=await command([*rf.SSH,rf.STATE_COMMAND])
        audit['restored']=rf.restored_state(before,audit['radio_after']) and (await command([*rf.SSH,'pidof sdrd'])).strip()==daemon
        SAVE(ROOT/'audit.json',audit)
        assert audit['restored']

def verify_retained():
    inventory=live.document(live.affine.ROOT/'docs/evidence/B210_BACKGROUND_EVIDENCE_2026-09-07.json')
    audit=live.document(live.affine.ROOT/'docs/evidence/B210_BACKGROUND_AUDIT_2026-09-07.json')
    expected={row['path'] for row in inventory['files']}
    assert {str(p) for p in ROOT.rglob('*') if p.is_file()}==expected
    for row in inventory['files']:
        data=live.read(Path(row['path']))
        assert len(data)==row['bytes'] and repair.lo.hashlib.sha256(data).hexdigest()==row['sha256']
    for row in audit['rows'][24:]:
        sealed,z=native(ROOT/f"capture-{row['index']:02d}",row['plan'])
        assert sealed==row['seal'] and stats(z)==row['statistics']
    assert select_candidate(audit['rows'][:24])==audit['selection']
    assert confirmation(audit['rows'][24:],audit['selection']['candidate_hz'])==audit['confirmation']
    print(json.dumps(dict(confirmation_captures_reproduced=6,discovery_raw_retained=False,
                         candidate_hz=audit['selection']['candidate_hz'],confirmation_passed=audit['confirmation']['passed'],
                         tx_operations=0,model_windows=0)))

def plot(audit,destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    fig,axes=plt.subplots(2,2,figsize=(12,9),constrained_layout=True)
    discovery=audit['rows'][:24]
    matrix=np.array([[next(r['statistics']['filtered']['maximum'] for r in discovery if r['center_hz']==f and r['round']==i) for i in range(3)] for f in CENTERS])
    im=axes[0,0].imshow(matrix,aspect='auto',norm=LogNorm(vmin=max(.1,float(matrix.min())),vmax=max(1.,float(matrix.max()))),cmap='magma')
    axes[0,0].set(xticks=range(3),xticklabels=['ascending','descending','ascending'],yticks=range(8),yticklabels=[f/1e6 for f in CENTERS],ylabel='RX frequency (MHz)',title='Discovery: maximum filtered 128-sample RMS')
    fig.colorbar(im,ax=axes[0,0],label='ADC RMS')
    confirm=audit['rows'][24:];candidate=audit['selection']['candidate_hz']
    for f,label,color in ((2440000000,'2440 MHz','#b2182b'),(candidate,str(candidate/1e6)+' MHz','#2166ac')):
        rows=[r for r in confirm if r['center_hz']==f]
        axes[0,1].plot([r['round']+1 for r in rows],[r['statistics']['filtered']['maximum'] for r in rows],'o-',label=label+' max',color=color)
        axes[0,1].plot([r['round']+1 for r in rows],[r['statistics']['filtered']['p95'] for r in rows],'x--',label=label+' p95',color=color)
    axes[0,1].axhline(8,color='gray',ls=':',label='max limit 8')
    axes[0,1].axhline(5,color='black',ls=':',label='p95 limit 5')
    axes[0,1].set(xlabel='Independent confirmation round',ylabel='Filtered ADC RMS',xticks=[1,2,3],title='Fixed candidate; no reselection')
    axes[0,1].legend(fontsize=8);axes[0,1].grid(alpha=.2)
    for col,row in enumerate(confirm[:2]):
        root=ROOT/f"capture-{row['index']:02d}";sealed,z=native(root,row['plan']);assert sealed==row['seal']
        blocks=np.lib.stride_tricks.sliding_window_view(z,256)[::128]*np.hanning(256)
        power=abs(np.fft.fftshift(np.fft.fft(blocks,axis=1),axes=1))**2/np.hanning(256).sum()**2
        im=axes[1,col].imshow(10*np.log10(np.maximum(power.T,1e-20)),origin='lower',aspect='auto',extent=[0,len(z)/point.RATE*1000,-1050,1050],vmin=-40,vmax=40,cmap='magma')
        axes[1,col].set(xlabel='Capture time (ms)',ylabel='RX baseband (kHz)',title=f"First confirmation at {row['center_hz']/1e6:g} MHz")
    fig.colorbar(im,ax=axes[1,:],label='Hann spectrum (dB ADC²)')
    fig.suptitle('RX-only background comparison; no protocol or hardware-cause attribution')
    fig.savefig(destination,dpi=150);plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--controller',type=Path);g.add_argument('--verify-retained',action='store_true');a=p.parse_args()
    async def main():
        task=asyncio.current_task()
        for sig in (signal.SIGINT,signal.SIGTERM):asyncio.get_running_loop().add_signal_handler(sig,task.cancel)
        await run(a.controller)
    if a.verify_retained:verify_retained()
    else:asyncio.run(main())
