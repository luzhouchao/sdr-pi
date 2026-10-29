#!/usr/bin/env python3
"""Validate joint stop/cache recovery, then run the registered26-SNR ledger.

One supervised background job. No model invocation, polling agent or automatic
RF retry on unexpected failure. All evidence stays outside Git.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import rml2018a_snr_stream as s


def state(root,phase,**fields):
    s.storage.atomic_json(root/'service-state.json',dict(phase=phase,updated_ns=time.time_ns(),model_loaded=False,**fields))
    print(json.dumps(dict(phase=phase,**fields)),flush=True)


def hardware_idle(p):
    bg=s.module('service_bg',s.SCRIPTS/'validate-p201-termination-background.py')
    tx=s.module('service_tx',s.c.REPO/'devices/b210/transport.py').Transport('agx',bg)
    baseline=json.loads((Path(p['backend'])/'before-deploy.json').read_text())
    bg.idle();bg.restoration(baseline['radio']);value=tx.preflight()
    s.module('service_pilot',s.SCRIPTS/'rml2018a-continuous-pilot.py').spark_off()
    return dict(restored=True,tx_preflight=value,spark='inactive',checked_ns=time.time_ns())


def final_inventory(root,p):
    """Inventory stopped results only; exclude this manifest and open logs."""
    groups=[];removed=[]
    for path in [Path(v) for g in p['groups'] for v in g['attempts']]:
        if not path.exists():continue
        scratch=path/'scratch'
        if scratch.exists():
            for f in sorted(scratch.rglob('*'),key=lambda v:len(v.parts),reverse=True):
                s.c.require(not f.is_symlink(),'scratch symlink')
                if f.is_file():removed.append(dict(path=str(f),bytes=f.stat().st_size));f.unlink()
                elif f.is_dir():f.rmdir()
                else:raise ValueError('unexpected socket retained for inspection')
            scratch.rmdir()
        wave=path/'tx.fc32'
        if wave.exists() and (path/'plan.json').exists():
            plan=json.loads((path/'plan.json').read_text())
            s.c.require(s.c.file_hash(wave)==plan['tx_sha256'],'final TX staging identity')
            removed.append(dict(path=str(wave),bytes=wave.stat().st_size,sha256=plan['tx_sha256']));wave.unlink()
        files=[dict(path=str(f),bytes=f.stat().st_size,sha256=s.c.file_hash(f))
               for f in sorted(path.rglob('*')) if f.is_file()]
        groups.append(dict(root=str(path),files=files,file_count=len(files),bytes=sum(f['bytes'] for f in files),
            purpose='RF attempt IQ/HDF5, frames, source/SINR metadata and success/failure/recovery records',
            lineage=str(path/'plan.json'),manual_delete=f"rm -rf -- '{path}'"))
    s.storage.atomic_json(root/'retention.json',dict(schema='rml2018a-snr-service-retention-v1',groups=groups,
        removed=removed,removed_files=len(removed),removed_bytes=sum(f['bytes'] for f in removed),
        retained_files=sum(g['file_count'] for g in groups),retained_bytes=sum(g['bytes'] for g in groups),
        original_iq_deleted=0,processed_results_deleted=0,imported_read_only=p['imported'],
        deletion_constraint='Manual user deletion only when results/dependent evidence no longer needed; each continuous pair shares one raw owner, delete pair as unit. Imported prior experiment untouched.'))


def run_locked(root):
    p=s.full_load(root);stopped=False;child=None;recovery_root=None
    expected=s.c.file_hash(Path(__file__))
    manifest=json.loads((root/'service-plan.json').read_text())
    s.c.require(manifest['service_sha256']==expected and manifest['ledger_plan_sha256']==s.c.file_hash(root/'ledger-plan.json'),
                'registered service/ledger identities')
    s.c.require(not (root/'service-started.json').exists(),'service is one-shot; inspect stopped receipts before restart')
    s.c.require(not (root/'STOP').exists(),'operator STOP')
    s.storage.atomic_json(root/'service-started.json',dict(started_ns=time.time_ns(),pid=os.getpid()))
    def stop(sig,frame):
        nonlocal stopped
        stopped=True;(root/'STOP').touch()
        if recovery_root is not None:(recovery_root/'RECOVERY_STOP').touch()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
    def start(args,logname):
        nonlocal child
        log=(root/logname).open('xb')
        try:child=subprocess.Popen([sys.executable,'-B',str(s.SCRIPTS/'rml2018a-snr-stream.py'),*args],stdout=log,stderr=subprocess.STDOUT)
        finally:log.close()
    def wait_for(predicate,seconds):
        deadline=time.monotonic()+seconds
        while True:
            s.c.require(not stopped,'operator stopped service')
            if predicate():return
            s.c.require(child is not None and child.poll() is None,'child exited before validation trigger')
            s.c.require(time.monotonic()<deadline,'validation trigger deadline')
            time.sleep(.5)
    def internal_stop():
        token='validation-'+uuid.uuid4().hex
        with (root/'STOP').open('x') as f:f.write(token)
        return token
    def clear_internal_stop(token):
        s.c.require(not stopped and (root/'STOP').read_text()==token,'operator STOP is never cleared')
        (root/'STOP').unlink();s.storage.sync_directory(root)
    success=False;failure=None
    try:
        state(root,'validating_joint_stop');hardware_idle(p)
        first=Path(p['groups'][1]['attempts'][0]);second=Path(p['groups'][1]['attempts'][1])
        start(['full-run','--root',str(root),'--stop-after','1'],'validation-joint-stop.log')
        wait_for(lambda:(first/'rx-events.jsonl').exists() and (first/'rx-events.jsonl').stat().st_size>262144,300)
        token=internal_stop();code=child.wait(timeout=200);s.c.require(code!=0,'joint stop must terminate incomplete attempt')
        audit=json.loads((first/'execution.json').read_text());rx=json.loads((first/'rx-process.json').read_text())
        s.c.require(audit['status']=='failed' and audit['restored'] and audit['worker_threads_stopped'] and
                    0<rx['bytes_received']<225443840*4,'joint stop partial RX preserved/restored')
        events=[json.loads(line) for line in (first/'tx-events.jsonl').read_text().splitlines()]
        s.c.require(0<events[-1]['accepted_samples']<2*s.SNR_SAMPLES,'joint stop actually interrupted TX')
        retained=(first/'snr-plus26/raw.sigmf-data').stat().st_size
        if (first/'pending-raw.ci16').exists():retained+=(first/'pending-raw.ci16').stat().st_size
        s.c.require(retained==rx['bytes_received'],'all received partial IQ retained')
        restored=hardware_idle(p);clear_internal_stop(token)
        s.storage.atomic_json(root/'joint-stop-validation.json',dict(status='passed',attempt=str(first),
            received_bytes=rx['bytes_received'],accepted_tx_samples=events[-1]['accepted_samples'],restored=restored))
        state(root,'validating_cache_recovery')
        start(['full-run','--root',str(root),'--retry','--stop-after','1'],'validation-drain-stop.log')
        wait_for(lambda:(second/'rx-process.json').exists(),420)
        rx=json.loads((second/'rx-process.json').read_text());s.c.require(rx['status']=='completed','complete RX before processing stop')
        token=internal_stop();code=child.wait(timeout=200);s.c.require(code!=0,'processing stop must preserve incomplete processing')
        before=json.loads((second/'execution.json').read_text())
        s.c.require(before['status']=='failed' and before['worker_threads_stopped'] and before['restored'] and
                    0<len(before['processed_receipts'])<192,'real processing backlog interrupted')
        tx_hash=s.c.file_hash(second/'tx-events.jsonl');rx_hash=s.c.file_hash(second/'rx-events.jsonl')
        hardware_idle(p);clear_internal_stop(token)
        recovery_root=second
        start(['recover','--root',str(second)],'validation-recovery.log')
        s.c.require(child.wait(timeout=1900)==0 and not stopped,'cache recovery must pass')
        recovery_root=None
        recovered=json.loads((second/'recovery.json').read_text())
        s.c.require(recovered['status']=='passed' and recovered['new_tx_samples']==recovered['new_rx_samples']==0 and
                    recovered['committed_prefix_blocks']==len(before['processed_receipts']) and
                    s.c.file_hash(second/'tx-events.jsonl')==tx_hash and s.c.file_hash(second/'rx-events.jsonl')==rx_hash,
                    'cache recovery preserves prefix and invokes no RF')
        hardware_idle(p)
        start(['full-run','--root',str(root),'--stop-after','1'],'validation-reconcile.log')
        s.c.require(child.wait(timeout=180)==0,'reconcile recovered group')
        receipt=root/'entries/01.complete.json';receipt_hash=s.c.file_hash(receipt)
        start(['full-run','--root',str(root),'--stop-after','1'],'validation-skip.log')
        s.c.require(child.wait(timeout=180)==0 and s.c.file_hash(receipt)==receipt_hash and
                    s.c.file_hash(second/'tx-events.jsonl')==tx_hash,'completed group never retransmitted')
        s.storage.atomic_json(root/'recovery-validation.json',dict(status='passed',attempt=str(second),
            committed_prefix_blocks=recovered['committed_prefix_blocks'],appended_blocks=recovered['appended_blocks'],
            repeated_run_new_tx_samples=0,repeated_run_new_rx_samples=0,tx_events_sha256=tx_hash,rx_events_sha256=rx_hash))
        state(root,'validation_passed_acquiring_remaining',completed_snr_groups=4)
        start(['full-run','--root',str(root)],'full-run.log')
        s.c.require(child.wait(timeout=p['maximum_wall_seconds'])==0 and not stopped,'full acquisition stopped/failed')
        result=s.full_status(root);s.c.require(result['complete'],'all26 sealed')
        state(root,'acquisition_complete',source_rows=result['source_rows'],completed_snr_groups=26)
        success=True
    except BaseException as error:
        failure=repr(error)
        state(root,'stopped_or_failed',error=repr(error))
        raise
    finally:
        if child is not None and child.poll() is None:
            (root/'STOP').touch()
            if recovery_root is not None:(recovery_root/'RECOVERY_STOP').touch()
            try:child.wait(timeout=200)
            except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=30)
        # Only clean after actual hardware restoration. A failed restoration
        # keeps all files for investigation instead of claiming safe cleanup.
        restoration=hardware_idle(p);s.storage.atomic_json(root/'final-radio-state.json',restoration)
        final_inventory(root,p)
        state(root,'complete' if success else 'stopped_or_failed',retention=str(root/'retention.json'),restored=True,error=failure)


def main(root):
    owner=os.open(root/'service-owner.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run_locked(root)
    finally:os.close(owner)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path)
    main(parser.parse_args().root)
