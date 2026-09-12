#!/usr/bin/env python3
"""AGX all-row RadioML2018A campaign: plan, bounded acquire, infer and summarize."""
import argparse
import asyncio
import contextlib
import fcntl
import importlib.util
import json
import math
import multiprocessing
import os
import re
from pathlib import Path
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:sys.path.insert(0,str(SCRIPTS))

import h5py
import numpy as np
from rml2018a_campaign import (REPO, SCHEMA, RATE, CENTER, BW, RX_SAMPLES, CFO_SEARCH_MAX_HZ, CFO_LIMIT_HZ,
    ROWS_PER_BATCH, batch_rows, budget, digest, file_hash, marker, normalize_window,
    packet, packet_peak, level_batches, RML_GAIN_PAIR_BATCHES, RML_TIMING_BATCHES, RML_TIMING_CLASSES,
    RML_GUARD_BATCHES, RML_GUARD_CLASSES,
    receive_quality, registered_tx_gain, require, save, sinr_contract, synchronize, tx_plan, validate_receive_quality)

DATASET = REPO/'local-assets/amc-eval/datasets/rml2018a/RML2018a.hdf5'
LABELS = REPO/'jetson-agx/sdrharness/config/amc/rml2018a-labels.server-v1.json'
PROFILE = REPO/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def document(path):
    return json.loads(Path(path).read_text())


def registered_rx_gain(value):
    require(type(value) is int and value in (20,40,50), 'registered RX gain:20,40 or50 dB')
    return value


def transport_module():
    spec=importlib.util.spec_from_file_location('campaign_b210_transport',REPO/'devices/b210/transport.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def campaign_software():
    return {name:file_hash(SCRIPTS/name) for name in (
        Path(__file__).resolve().name,'rml2018a_campaign.py','rml2018a-nx-tx.py',
        'amc-mamba-worker.py','amc-rf-v1-runtime.py','gpu_lease.py',
        'validate-b210-multiclass.py','validate-p201-termination-background.py','validate-b210-p201-link.py')}


def level_limits(profile='gain-pair-pilot'):
    batches=level_batches(profile)
    return dict(allowed_batch_indices=list(batches), maximum_tx_seconds=len(batches)*4,
        maximum_rx_iq_bytes=len(batches)*RX_SAMPLES*4, maximum_source_rows=len(batches)*24)


def campaign_level(campaign, indices=()):
    profile=campaign.get('tx_level_profile','standard')
    peak=packet_peak(profile)
    if profile != 'standard':
        require(campaign['tx_host']=='agx' and campaign['rf']['tx_gain_db']==60 and
            campaign['rf']['rx_gain_db']==40 and campaign['rf']['peak']==peak and
            campaign.get('execution_limits')==level_limits(profile), 'registered finite pilot campaign')
        require(all(type(i) is int and i in level_batches(profile) for i in indices), 'finite pilot batch selection')
    return profile


def create_plan(root, rx_gain_db=20, tx_gain_db=0, tx_host='agx', tx_level_profile='standard'):
    rx_gain_db=registered_rx_gain(rx_gain_db)
    tx_gain_db=registered_tx_gain(tx_gain_db)
    peak=packet_peak(tx_level_profile)
    if tx_level_profile != 'standard':
        require((rx_gain_db,tx_gain_db,tx_host)==(40,60,'agx'), 'gain-pair pilot requires AGX TX60/RX40')
    host_identity=transport_module().identity(tx_host)
    require(not root.exists(), 'run root already exists; use its existing plan')
    require(root.resolve() == root and root.parent == Path('/var/tmp/sdrharness-dev') and
            root.name.startswith('b210-rml2018a-') and root.name.replace('-', '').isalnum(), 'run root')
    pins = document(REPO/'jetson-agx/sdrharness/config/amc/rf-preprocess-v1-selection-plan.json')['pinned_inputs']
    require(DATASET.stat().st_size == pins['dataset']['bytes'], 'dataset size')
    print('Checking full dataset SHA-256 (read-only)...', flush=True)
    sha = file_hash(DATASET)
    require(sha == pins['dataset']['sha256'], 'dataset hash')
    with h5py.File(DATASET, 'r') as f:
        require(f['X'].shape == (2555904, 1024, 2) and f['X'].dtype == np.dtype('float32'), 'X layout')
        require(f['Y'].shape == (2555904, 24) and f['Z'].shape == (2555904, 1), 'labels layout')
        total = len(f['X'])
    b = budget(total)
    require(shutil.disk_usage(root.parent).free > b['maximum_rx_iq_bytes'] +
            b['metadata_and_predictions_reserve_bytes'] + 64*1024*1024, 'full campaign disk budget')
    root.mkdir(mode=0o700)
    plan = dict(schema=SCHEMA, run_id=uuid.uuid4().hex, source=dict(path=str(DATASET), sha256=sha,
        bytes=DATASET.stat().st_size, mtime_ns=DATASET.stat().st_mtime_ns), budget=b,
        scope='all original X/Y/Z rows, including historical train/validation/test membership',
        tx_host=tx_host,tx_host_identity=host_identity,tx_level_profile=tx_level_profile,
        semantics='all-row over-air engineering comparison, not independent locked-test admission',
        train=False, recognizer_available=False, name_status='provisional',
        label_map_sha256=file_hash(LABELS), profile_sha256=file_hash(PROFILE),
        software=campaign_software(),
        rf=dict(center_hz=CENTER, rate_sps=RATE, bandwidth_hz=BW, tx_gain_db=tx_gain_db,
                rx_gain_db=rx_gain_db, peak=peak, tx_lo_offset_hz=250000, settle_ms=500,
                point_deadline_ms=1000, rx_samples=RX_SAMPLES),
        framing='24 independent1024 rows with per-row peak normalization, batch-specific pilot and guards',
        synchronization=dict(cfo_search_max_hz=CFO_SEARCH_MAX_HZ,cfo_step_hz=500,
            cfo_limit_hz=CFO_LIMIT_HZ,initial_marker_threshold=.55,final_marker_threshold=.65),
        quality_contract=dict(source_snr_db='original dataset Z; never relabeled as received SINR',
            rx_sinr='conditional effective SINR including additional link distortion; not independently measured RF SINR',
            source_reference='X already contains source impairments; not a clean signal reference',
            estimator=sinr_contract(), source_rx_correlation='waveform fidelity only, not SINR'),
        preprocessing='pilot timing/CFO/phase correction then per-row complex RMS; no label-guided alignment',
        created_unix_ns=time.time_ns(), base_head=subprocess.check_output(['git','-C',str(REPO),
            'rev-parse','HEAD'], text=True).strip())
    if tx_level_profile != 'standard':
        plan['execution_limits']=level_limits(tx_level_profile)
        plan['scope']='Only registered Z30 batches'+str(list(level_batches(tx_level_profile)))+'; full budget describes dataset indexing, not permitted execution'
        plan['semantics']='Finite cable gain-pair engineering pilot, not a full campaign or independent admission'
        campaign_level(plan)
    save(root/'run-plan.json', plan)
    print(json.dumps(plan, indent=2), flush=True)


def load_plan(root):
    require(root.resolve() == root and root.parent == Path('/var/tmp/sdrharness-dev') and
            root.name.startswith('b210-rml2018a-') and root.name.replace('-', '').isalnum(), 'run root')
    p = document(root/'run-plan.json')
    require(p['schema'] == SCHEMA and p['budget'] == budget(2555904), 'plan identity')
    require(p['rf']['center_hz'] == CENTER, 'RF center changed; new campaign required')
    registered_rx_gain(p['rf']['rx_gain_db'])
    registered_tx_gain(p['rf']['tx_gain_db'])
    profile=campaign_level(p)
    require(p['rf']['peak']==packet_peak(profile), 'TX peak changed; new plan required')
    require(p['tx_host_identity']==transport_module().identity(p['tx_host']), 'TX host/runtime changed; new campaign required')
    for name, sha in p['software'].items():
        require(file_hash(SCRIPTS/name) == sha, 'software changed; new campaign required: '+name)
    require(file_hash(LABELS) == p['label_map_sha256'] and file_hash(PROFILE) == p['profile_sha256'],
            'label/profile changed')
    stat = DATASET.stat()
    require(p['source']['path'] == str(DATASET) and stat.st_size == p['source']['bytes'] and
            stat.st_mtime_ns == p['source']['mtime_ns'], 'source identity changed; new plan required')
    return p


@contextlib.contextmanager
def lock(root):
    with (root/'owner.lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def read_line(process, timeout):
    require(select.select([process.stdout], [], [], timeout)[0], 'remote response timeout')
    line = process.stdout.readline()
    require(line and len(line) < 16384, 'remote response EOF/size')
    return line


def native_check(root, plan):
    gain=registered_rx_gain(plan['gain_db'])
    report = document(root/'report.json')
    require(report['sweep_id'] == plan['sweep_id'] and
            report['session_generation'] == plan['session_generation'] and len(report['points']) == 1,
            'capture association')
    p = report['points'][0]
    for k, v in dict(requested_center_hz=CENTER, sample_rate_hz=RATE, rf_bandwidth_hz=BW,
                    captured_samples=RX_SAMPLES, dropped_samples=0, clipped_samples=0,
                    overflow=False, status_flags=0, point_index=0,
                    session_generation=plan['session_generation']).items():
        require(p[k] == v, 'capture '+k)
    require(abs(p['actual_center_hz']-CENTER) <= 2 and p['request_id'] > 0 and p['sequence'] > 0, 'RF identity')
    require(p['health'] == dict(healthy=True, flags=0, source='iio_adapter') and
            not p['timeout']['timed_out'] and p['timeout']['limit_ms'] == 1000, 'capture health')
    rx = p['rx_input']
    require(rx['verified'] and rx['front_panel_port'] == 'RX1' and rx['logical_channel'] == 'RX0'
            and rx['rf_port_select'] == 'A_BALANCED', 'RX identity')
    d = report['dataset']; data = Path(d['data_path']); meta = Path(d['metadata_path'])
    require(data.resolve().parent == meta.resolve().parent == root/'rx' and d['bytes'] == RX_SAMPLES*4
            and d['datatype'] == 'ci16_le' and d['format'] == 'sigmf', 'dataset identity')
    raw = data.read_bytes(); require(len(raw) == RX_SAMPLES*4, 'IQ bytes')
    metadata = document(meta)
    require(metadata['global']['core:sample_rate'] == RATE and
            metadata['global']['core:datatype'] == 'ci16_le', 'metadata layout')
    require(metadata['captures'] == [{'core:sample_start':0, 'core:frequency':p['actual_center_hz'],
            'sdrharness:point_index':0, 'sdrharness:rf_bandwidth_hz':BW, 'sdrharness:gain_db':gain}], 'metadata RF')
    v = np.frombuffer(raw, dtype='<i2').reshape(-1, 2)
    return v[:,0].astype(float)+1j*v[:,1], dict(iq_path=str(data), iq_sha256=digest(raw),
        metadata_sha256=file_hash(meta), request_id=p['request_id'], sequence=p['sequence'],
        session_generation=p['session_generation'])


def remote_cleanup(transport, remote):
    allowed = ['rml2018a_campaign.py','rml2018a-nx-tx.py','packet.fc32','tx-plan.json',
               'tx-started.json','tx-summary.json','tx-uhd.log']
    code = ('import json,stat,subprocess;from pathlib import Path; p=Path('+repr(str(remote))+'); '
            'rows=list(p.iterdir()); fifos=[x for x in rows if stat.S_ISFIFO(x.lstat().st_mode)]; '
            'assert all(not x.is_symlink() and ((x.is_file() and x.name in '+repr(allowed)+') or '
            '(x in fifos and x.name=="packet.fifo")) for x in rows); '
            'assert all(subprocess.run(["fuser",str(x)],capture_output=True,timeout=5).returncode==1 for x in fifos); '
            'print(json.dumps([dict(name=x.name,bytes=x.stat().st_size,kind="fifo" if x in fifos else "file") for x in rows])); '
            '[x.unlink() for x in rows];p.rmdir();assert not p.exists()')
    return json.loads(transport.run('python3 -c '+shlex.quote(code)))


def stop_tx(transport, tx, owner, remote):
    if tx is None or tx.poll() is not None:return
    if owner is not None:
        transport.run(f'if test -d /proc/{owner}; then test "$(readlink /proc/{owner}/cwd)" = "{remote}" && kill -INT {owner}; fi')
    else:tx.terminate()
    # Allow the helper to close its FIFO, stop UHD and save its receipt before escalation.
    try:tx.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        tx.terminate()
        try:tx.communicate(timeout=3)
        except subprocess.TimeoutExpired:tx.kill();tx.communicate(timeout=3)


def acquire_batch(root, campaign, index, retry_failed=False):
    level=campaign_level(campaign,[index])
    rx_gain=registered_rx_gain(campaign['rf']['rx_gain_db'])
    tx_gain=registered_tx_gain(campaign['rf']['tx_gain_db'])
    bg = module('campaign_bg', 'validate-p201-termination-background.py')
    link = module('campaign_link', 'validate-b210-p201-link.py')
    transport=transport_module().Transport(campaign.get('tx_host','nx'),bg)
    dest = root/f'batch-{index:07d}'
    if retry_failed and dest.exists():
        audit = document(dest/'audit.json')
        if audit['status'] != 'synchronized':
            require(audit.get('restored') is True, 'retry requires verified restoration; inspect failed audit')
            transport.preflight(); bg.idle()
            bg.ssh('test ! -e '+shlex.quote(audit['p201_path']))
            transport.run('test ! -e '+shlex.quote(audit['remote']))
            attempts=root/'attempts'; attempts.mkdir(mode=0o700,exist_ok=True)
            dest.rename(attempts/f'{dest.name}-{time.time_ns()}')
    if (dest/'capture-complete.json').exists():
        done=document(dest/'capture-complete.json')
        require(done['audit_sha256']==file_hash(dest/'audit.json') and
                done['rows']==batch_rows(campaign['budget']['rows'],index), 'completed batch changed')
        _, seal = native_check(dest,document(dest/'rx-plan.json'))
        require(seal==document(dest/'audit.json')['seal'], 'completed IQ changed')
        return done
    require(not dest.exists(), 'incomplete batch preserved; inspect before resuming or create new campaign')
    rows = batch_rows(campaign['budget']['rows'], index)
    with h5py.File(DATASET, 'r') as h5:
        iq = h5['X'][rows]; labels = h5['Y'][rows]; snrs = h5['Z'][rows].ravel()
    require(np.array_equal(labels, np.eye(24)[labels.argmax(axis=1)]), 'one-hot label')
    require(np.isfinite(snrs).all(), 'source SNR')
    frame, scales = packet(iq, campaign['run_id'], index,level_profile=level)
    txp = tx_plan(frame, campaign['run_id'], index, rows, tx_gain,level_profile=level)
    if level != 'standard':require(np.all(snrs==30), 'registered gain-pair source Z30')
    if level=='timing-multiclass-pilot':
        require(np.all(labels.argmax(axis=1)==RML_TIMING_CLASSES[RML_TIMING_BATCHES.index(index)]), 'registered multiclass source identity')
    if level=='qam-guard-pilot':
        require(np.all(labels.argmax(axis=1)==RML_GUARD_CLASSES[RML_GUARD_BATCHES.index(index)]), 'registered QAM source identity')
    require(shutil.disk_usage(root).free > RX_SAMPLES*4 + frame.nbytes + 32*1024*1024, 'batch disk budget')
    password=Path('/home/jetson/.config/sdrharness/p201-root.password')
    require(password.is_file() and not password.is_symlink() and password.stat().st_mode & 0o777 == 0o600,
            'protected password file required')
    transport.preflight(); bg.idle()
    before = bg.ssh(bg.STATE); pid = bg.ssh('pidof sdrd').split()
    require(len(pid) == 1, 'single sdrd required')
    state = dict(zip(before.splitlines()[::2], before.splitlines()[1::2]))
    require(all(v == '0' for k,v in state.items() if k.endswith(('_en','/enable'))), 'radio busy')
    daemon_hash = bg.ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]
    require(daemon_hash == '83a661a892b8ab71de3f4e7d64064c9c65030623dc7245eb3d3a1420a696ba4f', 'daemon hash')
    require(file_hash(bg.BINARY) == '24b8340dd5c56bcf643a44e1eadbd11450e3b5e528d2ec72dc26103e9f23e25f', 'Controller hash')
    require(bg.ssh(f'readlink /proc/{pid[0]}/exe').strip() == '/sd/sdr-agent/current/sdrd', 'daemon executable')
    bg.ssh('test -f /sd/sdr-agent/current/sdrd.conf && test -f /sd/sdr-agent/current/S60sdrd')
    require(sum(':43110 ' in line for line in bg.ssh('netstat -lnt').splitlines()) == 1, 'single listener')
    require(transport.run('sha256sum /usr/lib/uhd/examples/tx_samples_from_file').split()[0] ==
            'fe3aebc556c16a5065d63d4e6ef8f02ef277ac01dcf250a35dec58b84eceb5cf', 'TX host UHD binary hash')
    require(document_health(bg)['healthy'], 'preflight health')
    dest.mkdir(mode=0o700)
    (dest/'packet.fc32').write_bytes(frame.tobytes()); save(dest/'tx-plan.json', txp)
    save(dest/'source.json', dict(schema=SCHEMA, rows=rows, class_ids=labels.argmax(axis=1).tolist(),
         source_snr_db=snrs.tolist(), scales=scales.tolist(), original_iq_sha256=digest(iq.tobytes())))
    generation = time.time_ns() // 1000000
    rxp = dict(sweep_id=f'rml2018a-{index}-{generation}', session_generation=generation,
        frequencies=dict(kind='centers', centers_hz=[CENTER]), sample_rate_hz=RATE,
        rf_bandwidth_hz=BW, gain_db=rx_gain, settle_ms=500, frame_samples=RX_SAMPLES,
        aggregate_frames=1, point_timeout_ms=1000, detection_threshold_db=12.)
    remote = root.parent/f'{root.name}-b{index}'
    p201 = f'/tmp/sdr-agent-dev/agx-sweep-{generation}-0'
    save(dest/'rx-plan.json', rxp)
    audit = dict(batch=index, tx_host=transport.host, status='failed', started_unix_ns=time.time_ns(), radio_before=before,
        daemon_pid=pid[0], daemon_sha256=daemon_hash, remote=str(remote), p201_path=p201,
        maximum_rx_bytes=RX_SAMPLES*4, free_bytes=shutil.disk_usage(root).free, tx_plan=txp,
        stop='SIGINT/SIGTERM runner -> dedicated P201 generation cancel + identified TX host owner INT')
    save(dest/'audit.json', audit)
    print(json.dumps(dict(event='batch_plan',batch=index,rows=rows,rx=rxp,remote=str(remote),
                         p201_path=p201,max_bytes=RX_SAMPLES*4,free_bytes=audit['free_bytes'])),flush=True)
    tx = None; rx = None; owner = None; staged = False
    try:
        bg.ssh(f'test ! -e {p201}')
        transport.run(f'test ! -e {remote} && mkdir -m 700 {remote}'); staged = True
        transport.put([SCRIPTS/'rml2018a_campaign.py',SCRIPTS/'rml2018a-nx-tx.py',
                       dest/'packet.fc32',dest/'tx-plan.json'],remote)
        cmd = (f'cd {remote} && export PYTHONDONTWRITEBYTECODE=1 TMPDIR={remote} XDG_CACHE_HOME={remote} '
               f'&& echo OWNER $$ && exec timeout --signal=INT --kill-after=3s 58s python3 -B '
               f'{remote}/rml2018a-nx-tx.py --directory {remote}')
        tx = transport.spawn(cmd)
        first = read_line(tx, 10).decode().strip().split()
        require(len(first)==2 and first[0]=='OWNER' and first[1].isdigit(), 'TX owner receipt')
        owner = int(first[1]); audit['owner_pid'] = owner
        ready = json.loads(read_line(tx, 35)); require(ready['event']=='ready' and ready['batch']==index, 'TX ready')
        audit['tx_ready'] = ready
        tx.stdin.write(b'GO\n'); tx.stdin.flush()
        require(json.loads(read_line(tx, 3))['event']=='tx_start', 'TX start acknowledgement')
        audit['tx_start_ack_ns'] = time.time_ns()
        (dest/'rx').mkdir()
        rx = subprocess.Popen([str(bg.BINARY),'--mode','sweep','--sdrd','192.168.1.10:43110',
                 '--sigmf-directory',str(dest/'rx')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            out, err = rx.communicate(json.dumps(rxp).encode(),timeout=15)
            require(rx.returncode==0, 'RX failure: '+err.decode()[-1000:])
            save(dest/'report.json',json.loads(out))
        except BaseException:
            bg.command([bg.BINARY,'--mode','cancel','--sdrd','192.168.1.10:43110',
                        '--session-generation',str(generation)],timeout=6)
            raise
        bg.restoration(before)
        out, err = tx.communicate(timeout=15)
        require(tx.returncode==0, 'TX host failure: '+err.decode()[-1000:])
        audit['tx_stdout'] = out.decode(); audit['tx_stderr'] = err.decode()
        transport.get([remote/'tx-summary.json',remote/'tx-uhd.log'],dest)
        tx_result = document(dest/'tx-summary.json')
        require(tx_result['status']=='fed_complete' and tx_result['bytes_written']==txp['tx_samples']*8
                and tx_result['child_stopped'], 'TX byte/stop receipt')
        log=(dest/'tx-uhd.log').read_text()
        for label,value in [('Actual TX Rate',2.1),('Actual TX Freq',CENTER/1e6),
                            ('Actual TX Gain',float(tx_gain)),('Actual TX Bandwidth',1.5)]:
            matches=re.findall(re.escape(label)+r': ([\d.+-]+)',log)
            require(len(matches)==1 and abs(float(matches[0])-value)<1e-6, 'UHD readback '+label)
        require('LO: locked' in log, 'TX LO unlocked')
        audit['uhd_tail_markers']=log.split('Done!')[-1].strip()
        raw, seal = native_check(dest,rxp)
        audit['seal'] = seal
        received = None
        try:
            received, sync = synchronize(raw,campaign['run_id'],index,len(rows))
            audit['sync'] = sync; audit['status'] = 'synchronized'
        except ValueError as e:
            audit['status'] = 'sync_failed'; audit['sync_error'] = str(e)
        audit['receive_quality'] = [dict(row=row, source_snr_db=int(snrs[k]),rx_gain_db=rx_gain,tx_gain_db=tx_gain,
            **receive_quality(audit['status'],iq[k,:,0]+1j*iq[k,:,1],
                              None if received is None else received[k],float(snrs[k])))
            for k,row in enumerate(rows)]
    except BaseException as e:
        audit['error'] = f'{type(e).__name__}: {e}'
        raise
    finally:
        stop_tx(transport,tx,owner,remote)
        for process in (rx,):
            if process is not None and process.poll() is None:
                process.terminate()
                try: process.communicate(timeout=8)
                except subprocess.TimeoutExpired: process.kill(); process.communicate(timeout=3)
        try:
            audit['radio_after'] = bg.restoration(before)
            require(bg.ssh('pidof sdrd').split()==pid, 'daemon changed')
            require(bg.ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]==daemon_hash,'daemon hash changed')
            bg.ssh(f'test ! -e {p201}')
            if staged:
                transport.run(link.remote_absence_command(remote,owner,
                    audit.get('tx_ready',{}).get('child_pid')))
                # Preserve failed UHD startup/feed diagnostics before remote cleanup too.
                for name in ('tx-uhd.log','tx-summary.json'):
                    if not (dest/name).exists():
                        present=transport.run(f'if test -f {remote}/{name}; then echo yes; fi').strip()
                        if present=='yes':
                            transport.get([remote/name],dest)
                audit['remote_removed'] = remote_cleanup(transport,remote)
            audit[transport.host+'_after'] = transport.preflight()
            audit['health_after'] = document_health(bg)
            require(audit['health_after']['healthy'], 'postflight health')
            audit['restored'] = True
        finally:
            audit['elapsed_seconds'] = (time.time_ns()-audit['started_unix_ns'])/1e9
            save(dest/'audit.json',audit)
    # Payload can be deterministically re-exported from the pinned HDF5; no duplicate retained source.
    require(file_hash(dest/'packet.fc32')==txp['payload_sha256'], 'payload cleanup identity')
    audit['local_removed_payload_bytes'] = (dest/'packet.fc32').stat().st_size
    (dest/'packet.fc32').unlink()
    save(dest/'audit.json',audit)
    save(dest/'capture-complete.json',dict(status=audit['status'],audit_sha256=file_hash(dest/'audit.json'),rows=rows))
    print(json.dumps(dict(event='captured',batch=index,status=audit['status'],seconds=audit['elapsed_seconds'])),flush=True)
    return document(dest/'capture-complete.json')


def document_health(bg):
    return json.loads(bg.command([bg.BINARY,'--mode','health','--sdrd','192.168.1.10:43110']))


def infer_batches(root, campaign, indices):
    campaign_level(campaign,indices)
    require(len(indices)<=32, 'bounded GPU shard: at most32 batches')
    pending=[i for i in indices if not (root/f'batch-{i:07d}'/'predictions.json').exists()]
    if not pending:
        return
    multi=module('campaign_multi','validate-b210-multiclass.py')
    names=document(LABELS)['classes']
    # Reuse existing bounded idle-Spark pause/restore watchdog, never stop an active request.
    from gpu_lease import GpuLease
    lease=GpuLease(root/'scratch'/'gpu-gate','mamba')
    token=asyncio.run(lease.acquire(time.monotonic()+10,request='rml2018a-campaign'))
    with contextlib.ExitStack() as stack:
        stack.callback(lease.close)
        stack.callback(lease.release,token)
        stack.enter_context(multi.idle_spark_pause(evidence_root=root))
        worker=module('campaign_model','amc-mamba-worker.py')
        backend=worker.RfV1Backend(PROFILE)
        end=time.monotonic()+580
        for index in pending:
            require(time.monotonic()<end, 'GPU shard deadline')
            dest=root/f'batch-{index:07d}'; done=document(dest/'capture-complete.json')
            require(file_hash(dest/'audit.json')==done['audit_sha256'], 'audit modified')
            source=document(dest/'source.json'); raw,seal=native_check(dest,document(dest/'rx-plan.json'))
            audit=document(dest/'audit.json')
            require(seal==audit['seal'], 'RX evidence changed')
            require([q['row'] for q in audit['receive_quality']]==source['rows'], 'quality row membership')
            with h5py.File(DATASET,'r') as f:iq=f['X'][source['rows']]
            require(digest(iq.tobytes())==source['original_iq_sha256'], 'source row changed')
            received=None;sync=None
            if done['status']=='synchronized':
                received,sync=synchronize(raw,campaign['run_id'],index,len(iq))
            outputs=[]
            for k,row in enumerate(source['rows']):
                require(time.monotonic()<end, 'GPU shard deadline')
                z=iq[k,:,0].astype(float)+1j*iq[k,:,1]
                quality=audit['receive_quality'][k]
                require(quality['source_snr_db']==source['source_snr_db'][k], 'quality source Z')
                validate_receive_quality(quality,source['source_snr_db'][k])
                entry=dict(**quality,true_id=source['class_ids'][k],
                    receive_status=done['status'],source_prediction=None,received_prediction=None)
                for tag,data in [('source',z),('received',None if received is None else received[k])]:
                    if data is None:continue
                    tensor=normalize_window(data);logits,us=backend.classify_logits(tensor)
                    prediction=int(np.argmax(logits))
                    entry[tag+'_prediction']=dict(id=prediction,name=names[prediction],logits=logits,
                        input_sha256=digest(tensor.tobytes()),inference_us=us)
                if received is not None:
                    entry['source_rx_correlation']=float(abs(np.vdot(z,received[k])) /
                        max(np.linalg.norm(z)*np.linalg.norm(received[k]),1e-30))
                outputs.append(entry)
            save(dest/'predictions.json',dict(schema=SCHEMA,batch=index,rows=outputs,
                audit_sha256=done['audit_sha256'],
                sync=sync,model_identity=backend.admission_identity,profile_sha256=campaign['profile_sha256'],
                label_map_sha256=campaign['label_map_sha256'],name_status='provisional',
                uncalibrated=True,recognizer_available=False,
                semantics='all-row engineering comparison; pilot aligned single1024 windows, no production four-window admission'))
            print(json.dumps(dict(event='inferred',batch=index,rows=len(outputs))),flush=True)
        del backend
    if (root/'gpu-isolation.json').exists():
        (root/'gpu-isolation.json').rename(root/f'gpu-isolation-{time.time_ns()}.json')


def infer_child(root, campaign, indices):
    # A fresh process per shard also releases CUDA and Torch's one-shot thread setup.
    def abort(sig, frame):
        raise RuntimeError(f'inference stopped by signal {sig}')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, abort)
    signal.alarm(650)
    try:
        infer_batches(root, campaign, indices)
    finally:
        signal.alarm(0)
        if (root/'gpu-isolation.json').exists():
            (root/'gpu-isolation.json').rename(root/f'gpu-isolation-{time.time_ns()}.json')


def infer_shard(root, campaign, indices):
    if all((root/f'batch-{i:07d}'/'predictions.json').exists() for i in indices):
        return
    child = multiprocessing.get_context('spawn').Process(target=infer_child, args=(root,campaign,indices))
    child.start()
    try:
        child.join(670)
        require(child.exitcode == 0, f'inference child failed: {child.exitcode}')
    finally:
        if child.is_alive():
            child.terminate(); child.join(15)
        if child.is_alive():
            child.kill(); child.join(5)
        require(not child.is_alive(), 'inference child not stopped')
        child.close()


def summarize(root, campaign):
    total=campaign['budget']['rows']; attempted=0; inferred=0; correct=0; source_correct=0; source_inferred=0
    confusion=np.zeros((24,24),dtype=np.int64);by_source_snr={}; batches=0
    sinr_counts=dict(estimated=0,invalid=0,not_measured=0);sinr_reasons={};by_sinr={}
    for index in range(campaign['budget']['batches']):
        completed=root/f'batch-{index:07d}'/'capture-complete.json'
        if completed.exists():
            done=document(completed)
            require(done['rows']==batch_rows(total,index), 'capture row membership')
            require(done['audit_sha256']==file_hash(completed.parent/'audit.json'), 'capture audit changed')
            quality=document(completed.parent/'audit.json')['receive_quality']
            require([q['row'] for q in quality]==done['rows'], 'quality row membership')
            for q in quality:
                validate_receive_quality(q,q['source_snr_db'])
                status=q['rx_sinr_status'];sinr_counts[status]+=1
                if status=='estimated':
                    # Fixed 2 dB floor bins; includes failed inference in acquired count.
                    key=str(2*math.floor(q['rx_sinr_db']/2))
                    bucket=by_sinr.setdefault(key,dict(acquired=0,inferred=0,correct=0))
                    bucket['acquired']+=1
                else:
                    reason=q['rx_sinr_reason'];sinr_reasons[reason]=sinr_reasons.get(reason,0)+1
            attempted+=len(done['rows'])
        p=root/f'batch-{index:07d}'/'predictions.json'
        if not p.exists():continue
        result=document(p);require(result['batch']==index,'prediction batch identity')
        require(result['schema']==SCHEMA, 'prediction schema changed; do not relabel archived results')
        require(completed.exists() and result['audit_sha256']==done['audit_sha256'], 'prediction association')
        require([x['row'] for x in result['rows']]==batch_rows(total,index),'prediction row membership')
        batches+=1
        for row,q in zip(result['rows'],quality):
            source_inferred+=1;source_correct+=int(row['source_prediction']['id']==row['true_id'])
            require(all(k in row and row[k]==v for k,v in q.items()), 'prediction quality differs from capture audit')
            bucket=by_source_snr.setdefault(str(row['source_snr_db']),dict(attempted=0,inferred=0,correct=0))
            bucket['attempted']+=1
            if row['received_prediction'] is not None:
                inferred+=1;bucket['inferred']+=1;p=row['received_prediction']['id'];t=row['true_id']
                confusion[t,p]+=1;correct+=int(p==t);bucket['correct']+=int(p==t)
                if row['rx_sinr_status']=='estimated':
                    group=by_sinr[str(2*math.floor(row['rx_sinr_db']/2))]
                    group['inferred']+=1;group['correct']+=int(p==t)
    value=dict(schema=SCHEMA,rx_gain_db=registered_rx_gain(campaign['rf']['rx_gain_db']),
        tx_gain_db=registered_tx_gain(campaign['rf']['tx_gain_db']),
        total_source_rows=total,attempted_rows=attempted,received_inferred_rows=inferred,
        source_inferred_rows=source_inferred,receive_pending_or_failed_rows=attempted-inferred,
        pending_inference_rows=attempted-source_inferred,not_yet_attempted_rows=total-attempted,completed_batches=batches,
        complete=source_inferred==total,all_rows_received_and_inferred=inferred==total,
        source_accuracy=source_correct/source_inferred if source_inferred else None,
        received_correct=correct,source_correct=source_correct,confusion_matrix=confusion.tolist(),
        by_source_snr_db=by_source_snr,
        rx_sinr=dict(status='conditional_estimates',measured_rows=0,**sinr_counts,
            quality_rows=attempted,unavailable_reasons=sinr_reasons,
            by_estimated_rx_sinr_db=by_sinr,bin_width_db=2,bin_semantics='[key, key+2)',
            contract=sinr_contract()),
        received_accuracy=correct/inferred if inferred else None,
        end_to_end_success_fraction=correct/attempted if attempted else None,
        semantics='all-row engineering comparison, includes historical train/validation/test; not independent test accuracy',
        recognizer_available=False)
    if campaign_level(campaign) != 'standard':
        value['execution_limits']=campaign['execution_limits']
        value['scope']=campaign['scope']
    save(root/'summary.json',value);print(json.dumps(value),flush=True)


def selected_batches(total, start, count, explicit=None):
    if explicit is not None:
        require(start==0 and count==1, 'explicit batches cannot be combined with range overrides')
        require(1<=len(explicit)<=32 and len(set(explicit))==len(explicit) and
                all(type(i) is int and 0<=i<total for i in explicit), '1-32 unique in-range batches required')
        return list(explicit)
    require(0<=start<total and count>0, 'batch range')
    return list(range(start,min(total,start+count)))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['plan','acquire','infer','run','summary'])
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--start-batch',type=int,default=0)
    p.add_argument('--max-batches',type=int,default=1)
    p.add_argument('--batch-indices',type=int,nargs='+',help='explicit ordered pilot/shard, 1-32 unique batches; no range overrides')
    p.add_argument('--deadline-seconds',type=int,default=600)
    p.add_argument('--retry-failed',action='store_true',help='archive restored failed attempts, then retry; never discard evidence')
    p.add_argument('--rx-gain-db',type=int,choices=[20,40,50],help='plan only; default20; all execution uses the sealed plan')
    p.add_argument('--tx-gain-db',type=int,choices=[0,20,40,60,70,80],help='plan only; default0; all execution uses the sealed plan')
    p.add_argument('--tx-host',choices=['agx','nx'],help='plan only; default agx; P201 remains network RX')
    p.add_argument('--tx-level-profile',choices=['standard','gain-pair-pilot','timing-multiclass-pilot','qam-guard-pilot'],help='plan only; finite pilots restrict batch IDs at AGX TX60/RX40')
    args=p.parse_args();root=args.root
    if args.command=='plan':
        require(args.batch_indices is None,'batch selection is execution-only; preregister pilot separately')
        create_plan(root,20 if args.rx_gain_db is None else args.rx_gain_db,0 if args.tx_gain_db is None else args.tx_gain_db,args.tx_host or 'agx',args.tx_level_profile or 'standard');return
    require(args.rx_gain_db is None and args.tx_gain_db is None and args.tx_host is None and args.tx_level_profile is None,'RF gains/level are sealed in run-plan; create a new plan to change them')
    campaign=load_plan(root)
    indices=selected_batches(campaign['budget']['batches'],args.start_batch,args.max_batches,args.batch_indices)
    campaign_level(campaign,indices if args.command!='summary' else ())
    require(60<=args.deadline_seconds<=30*86400,'finite deadline')
    scratch=root/'scratch';scratch.mkdir(mode=0o700,exist_ok=True)
    os.environ.update(TMPDIR=str(scratch),XDG_CACHE_HOME=str(scratch),TRITON_CACHE_DIR=str(scratch/'triton'),
                      CUDA_CACHE_PATH=str(scratch/'cuda'),PYTHONDONTWRITEBYTECODE='1')
    def abort(sig,frame):raise RuntimeError(f'campaign stopped by signal {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
    signal.alarm(args.deadline_seconds)
    with lock(root):
        try:
            if args.command=='summary':summarize(root,campaign);return
            for offset in range(0,len(indices),32):
                shard=indices[offset:offset+32]
                if args.command in ('acquire','run'):
                    for index in shard:acquire_batch(root,campaign,index,args.retry_failed)
                if args.command in ('infer','run'):infer_shard(root,campaign,shard)
            if args.command in ('acquire','infer','run'):summarize(root,campaign)
        finally:
            signal.alarm(0)


if __name__=='__main__':main()
