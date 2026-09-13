"""Campaign-owned cross-chunk receipts, dataset pin reuse and finite total gates.

Invoked only through rml2018a-rf-campaign.py. JSON receipts are authoritative;
state.json is rebuildable. No independent radio or model implementation.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import rml2018a_campaign as c
import rml2018a_campaign_events as e
m=e.m
BASE=Path('/var/tmp/sdrharness-dev')
DATA_SHA='e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38'
TOTAL_CAP=483469927424+2*1024**3


def private_root(root):
    c.require(root.is_absolute() and root.resolve()==root and root.parent==BASE and
        root.name.startswith('b210-rml2018a-') and root.name.replace('-','').isalnum(),'ledger/campaign root')


def source_identity():
    s=m.DATASET.stat()
    return dict(path=str(m.DATASET),bytes=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns,device=s.st_dev,inode=s.st_ino,sha256=DATA_SHA)


def software():return e.r.software()


def create(root,max_new=2):
    private_root(root);c.require(not root.exists() and type(max_new) is int and 1<=max_new<=106496,'new finite ledger')
    c.require(m.DATASET.stat().st_size==21449148312 and c.file_hash(m.DATASET)==DATA_SHA,'full source pin')
    root.mkdir(mode=0o700);(root/'entries').mkdir(mode=0o700)
    p=dict(schema='rml2018a-global-campaign-ledger-v1',source=source_identity(),software=software(),
        profile_sha256=c.file_hash(m.PROFILE),label_map_sha256=c.file_hash(m.LABELS),
        maximum_new_batches=max_new,maximum_new_tx_seconds=max_new*8,
        retention_limit_bytes=TOTAL_CAP,failure_pool_bytes=e.storage.FAILURE_POOL,
        total_source_rows=2555904,chunk_max_batches=32,automatic_next_chunk=False,
        source_verification='one full SHA at ledger creation; exact path/device/inode/size/mtime and known SHA before every child plan/run',
        scope='Explicit bounded cross-chunk engineering campaign; imported engineering results remain separately identified',
        recognizer_available=False,created_unix_ns=time.time_ns())
    c.save(root/'ledger-plan.json',p);return p


def load(root):
    private_root(root);p=m.document(root/'ledger-plan.json')
    c.require(p['schema']=='rml2018a-global-campaign-ledger-v1' and p['source']==source_identity() and p['software']==software(),'ledger source/software identity')
    c.require(p['profile_sha256']==c.file_hash(m.PROFILE) and p['label_map_sha256']==c.file_hash(m.LABELS),'ledger model profile/labels')
    c.require(type(p['maximum_new_batches']) is int and 1<=p['maximum_new_batches']<=106496 and
        p['maximum_new_tx_seconds']==p['maximum_new_batches']*8 and p['failure_pool_bytes']==e.storage.FAILURE_POOL and
        p['retention_limit_bytes']==TOTAL_CAP and p['automatic_next_chunk'] is False,'ledger fixed total limits')
    return p


def cached_source(root):
    p=load(root)
    return dict(ledger_root=str(root),ledger_plan_sha256=c.file_hash(root/'ledger-plan.json'),identity=p['source'])


def verify_cached(value):
    root=Path(value['ledger_root']);c.require(value==cached_source(root),'shared source receipt changed')
    return value['identity']['sha256']


def key(child):return c.digest(str(child).encode())[:24]


def entry_path(root,child):return root/'entries'/(key(child)+'.entry.json')


def entries(root):
    return [(path,m.document(path)) for path in sorted((root/'entries').glob('*.entry.json'))]


def inventory(child):
    rows=[]
    for path in sorted(child.rglob('*')):
        if 'scratch' in path.relative_to(child).parts or path.name=='owner.lock':continue
        c.require(not path.is_symlink(),'campaign inventory symlink')
        if path.is_file():rows.append(dict(path=str(path),bytes=path.stat().st_size,sha256=c.file_hash(path)))
    return rows


def check_inventory(rows):
    for v in rows:
        path=Path(v['path']);c.require(path.is_file() and not path.is_symlink() and path.stat().st_size==v['bytes'] and c.file_hash(path)==v['sha256'],'completed inventory changed')


def prune_scratch(child):
    removed=[]
    for base in [child/'scratch',*child.glob('inference-*/attempt-*/scratch')]:
        if not base.exists():continue
        c.require(base.resolve()==base and base.is_relative_to(child),'scratch identity')
        for path in sorted(base.rglob('*'),key=lambda p:len(p.parts),reverse=True):
            c.require(not path.is_symlink(),'scratch symlink')
            if path.is_dir():path.rmdir()
            else:
                c.require(path.is_file(),'unexpected scratch/socket; inspect owner')
                removed.append(dict(path=str(path),bytes=path.stat().st_size,sha256=c.file_hash(path)));path.unlink()
        base.rmdir()
    return removed


def failure_budget(b):
    return b['failed_attempt_reserve_bytes']+len(b['allowed_batch_indices'])*b['metadata_reserve_per_batch']


def failure_bytes(child,p):
    total=e.storage.retained_usage(child,p['execution_limits'])['failed_attempt_bytes']
    for receipt in child.glob('inference-*/attempt-*/inference.json'):
        if m.document(receipt)['status']!='completed':
            total+=sum(q.stat().st_size for q in receipt.parent.rglob('*') if q.is_file() and 'scratch' not in q.relative_to(receipt.parent).parts)
    return total


def complete(root,entry,imported_inventory=None):
    child=Path(entry['child_root']);p=m.document(child/'run-plan.json')
    c.require(p['tx_level_profile']=='event-chunk' and e.indices(p)==entry['batch_indices'],'completed child scope')
    c.require(p['source']['sha256']==DATA_SHA and p['profile_sha256']==c.file_hash(m.PROFILE) and
        p['label_map_sha256']==c.file_hash(m.LABELS),'completed child identities')
    c.require(all(e.capture_complete(child,p,i) and e.prediction_complete(child,p,i) for i in entry['batch_indices']),'complete RX/inference replay')
    summary=m.document(child/'summary.json');c.require(summary['complete'] and summary['registered_source_rows']==len(entry['batch_indices'])*24,'complete summary')
    c.require(e.aggregate(summary['rows'])=={k:summary[k] for k in e.aggregate(summary['rows'])},'complete statistics replay')
    removed=[] if imported_inventory is not None else prune_scratch(child)
    if removed:c.save(child/'ledger-scratch-cleanup.json',dict(removed=removed,bytes=sum(v['bytes'] for v in removed)))
    files=inventory(child)
    # Imported evidence is read-only, checked against its pre-existing sealed inventory.
    if imported_inventory is not None:check_inventory(imported_inventory)
    value=dict(schema='rml2018a-ledger-completion-v1',started_attempts=len(list(child.glob('batch-*/attempt-*/started.json'))),entry_sha256=c.file_hash(entry_path(root,child)),
        child_plan_sha256=c.file_hash(child/'run-plan.json'),batch_indices=entry['batch_indices'],
        retained_files=files,retained_bytes=sum(v['bytes'] for v in files),
        failure_bytes=failure_bytes(child,p),
        statistics={k:v for k,v in summary.items() if k!='rows'},scratch_removed_bytes=sum(v['bytes'] for v in removed))
    path=root/'entries'/(key(child)+'.complete.json');c.require(not path.exists(),'completion already published')
    c.save(path,value);return value


def refresh(root,deep=False):
    p=load(root);seen=set();failed=reserved=fail_reserved=new_batches=completed=captured=inferred=attempts=0;states=[];registered_groups={}
    ledger_bytes=sum(q.stat().st_size for q in root.rglob('*') if q.is_file());used=ledger_bytes
    sums={tag:dict(total=0,predicted=0,correct=0) for tag in e.TAGS};groups={}
    for path,v in entries(root):
        child=Path(v['child_root']);private_root(child);ids=e.storage.batches(v['batch_indices'])
        c.require(path==entry_path(root,child) and v['ledger_plan_sha256']==c.file_hash(root/'ledger-plan.json') and not seen.intersection(ids),'ledger association/duplicate batches')
        seen.update(ids);new_batches+=len(ids) if v['kind']=='reserved' else 0
        for i in ids:
            for row in c.batch_rows(2555904,i):
                group=f'{row//106496}/{2*((row%106496)//4096)-20}';registered_groups[group]=registered_groups.get(group,0)+1
        done=root/'entries'/(key(child)+'.complete.json')
        if done.exists():
            d=m.document(done);c.require(d['entry_sha256']==c.file_hash(path) and d['batch_indices']==ids,'completion association')
            if deep:check_inventory(d['retained_files'])
            used+=d['retained_bytes'];failed+=d['failure_bytes'];completed+=len(ids);captured+=len(ids);inferred+=len(ids);attempts+=d['started_attempts']
            for tag in e.TAGS:
                for k in sums[tag]:sums[tag][k]+=d['statistics']['classification'][tag][k]
            for group,record in d['statistics']['by_class_source_snr'].items():
                target=groups.setdefault(group,{tag:dict(total=0,predicted=0,correct=0) for tag in e.TAGS})
                for tag in e.TAGS:
                    for k in target[tag]:target[tag][k]+=record['classification'][tag][k]
            state='completed'
        else:
            b=e.storage.budget(ids);reserved+=b['reserve_bytes'];fail_reserved+=failure_budget(b)
            if (child/'run-plan.json').exists():
                cp=m.load_plan(child)
                captured+=sum(e.capture_complete(child,cp,i) is not None for i in ids)
                inferred+=sum(e.prediction_complete(child,cp,i) for i in ids)
                attempts+=len(list(child.glob('batch-*/attempt-*/started.json')))
            state='reserved_or_interrupted';used+=sum(q.stat().st_size for q in child.rglob('*') if q.is_file()) if child.exists() else 0
        states.append(dict(child_root=str(child),kind=v['kind'],batch_indices=ids,state=state))
    result=dict(schema='rml2018a-ledger-state-v1',registered_batches=len(seen),completed_batches=completed,
        registered_source_rows=len(seen)*24,captured_source_rows=captured*24,inferred_source_rows=inferred*24,started_attempts=attempts,completed_source_rows=completed*24,pending_registered_rows=(len(seen)-completed)*24,
        total_source_rows=2555904,unregistered_source_rows=2555904-len(seen)*24,
        new_batches_reserved=new_batches,new_tx_seconds_reserved=new_batches*8,ledger_bytes=ledger_bytes,retained_bytes=used,failure_bytes=failed,
        outstanding_reserve_bytes=reserved,outstanding_failure_reserve_bytes=fail_reserved,
        classification_completed=sums,by_class_source_snr_completed=groups,
        by_class_source_snr={group:dict(registered_rows=count,completed=groups.get(group),pending_rows=count-groups.get(group,{}).get('source',{}).get('total',0)) for group,count in registered_groups.items()},campaigns=states,recognizer_available=False,
        whole_dataset_complete=completed==106496,stop_requested=(root/'STOP').exists())
    temp=root/'state.json.tmp'
    if temp.exists():
        c.require(temp.is_file() and not temp.is_symlink(),'state staging type');recovery=root/'recovery';recovery.mkdir(exist_ok=True)
        temp.rename(recovery/f'state-incomplete-{time.time_ns()}.json')
    c.save(root/'state.json',result);return result


def gate(p,state,n=0):
    extra=e.storage.budget(list(range(n))) if n else None
    c.require(state['new_batches_reserved']+n<=p['maximum_new_batches'] and
        state['new_tx_seconds_reserved']+n*8<=p['maximum_new_tx_seconds'],'total new TX/batch budget exhausted')
    c.require(state['failure_bytes']+state['outstanding_failure_reserve_bytes']+(failure_budget(extra) if extra else 0)<=p['failure_pool_bytes'],'global failure pool exhausted')
    c.require(state['retained_bytes']+state['outstanding_reserve_bytes']+(extra['reserve_bytes'] if extra else 0)<=p['retention_limit_bytes'],'global storage budget exhausted')
    c.require(not state['stop_requested'],'ledger STOP requested')


def reserve(root,child,ids):
    p=load(root);private_root(child);c.require(child!=root,'child differs from ledger');e.storage.batches(ids)
    path=entry_path(root,child)
    value=dict(kind='reserved',child_root=str(child),batch_indices=ids,ledger_plan_sha256=c.file_hash(root/'ledger-plan.json'))
    state=refresh(root)
    if path.exists():c.require(m.document(path)==value,'reservation changed')
    else:
        c.require(not child.exists() and not set(ids).intersection(i for row in state['campaigns'] for i in row['batch_indices']),'duplicate source or existing child')
        gate(p,state,len(ids));c.save(path,value) # Durable before creating a child plan.
    if not child.exists():m.create_plan(child,50,60,'agx','event-chunk',ids,source_receipt=cached_source(root))
    cp=m.load_plan(child);c.require(cp.get('source_verification')==cached_source(root) and e.indices(cp)==ids,'reserved child/source identity')
    refresh(root);return value


def import_completed(root,child,evidence):
    p=load(root);private_root(child);audit=m.document(evidence)
    c.require(audit['retained_root']==str(child),'import root');check_inventory(audit['retained_files'])
    cp=m.document(child/'run-plan.json');ids=e.indices(cp);path=entry_path(root,child)
    value=dict(kind='imported',child_root=str(child),batch_indices=ids,ledger_plan_sha256=c.file_hash(root/'ledger-plan.json'),
        inventory_path=str(evidence),inventory_sha256=c.file_hash(evidence))
    if path.exists():c.require(m.document(path)==value,'import identity changed')
    else:
        state=refresh(root);c.require(not set(ids).intersection(i for row in state['campaigns'] for i in row['batch_indices']),'duplicate imported source')
        c.require(state['retained_bytes']+audit['retained_bytes']<=p['retention_limit_bytes'],'import storage budget')
        c.save(path,value)
    done=root/'entries'/(key(child)+'.complete.json')
    if not done.exists():complete(root,value,audit['retained_files'])
    return refresh(root,deep=True)


def run(root,child,retry=False):
    p=load(root);v=m.document(entry_path(root,child));c.require(v['kind']=='reserved','imported evidence is read-only')
    state=refresh(root);gate(p,state)
    done=root/'entries'/(key(child)+'.complete.json')
    if done.exists():check_inventory(m.document(done)['retained_files']);return state
    cp=m.load_plan(child);c.require(cp.get('source_verification')==cached_source(root) and e.indices(cp)==v['batch_indices'],'child binding')
    c.require(shutil.disk_usage(root).free>state['outstanding_reserve_bytes'],'global free-space reserve')
    cmd=[sys.executable,'-B',str(m.SCRIPTS/'rml2018a-rf-campaign.py'),'run','--root',str(child),'--batch-indices',*map(str,v['batch_indices']),'--deadline-seconds','680']
    if retry:cmd.append('--retry-failed')
    logs=root/'commands';logs.mkdir(exist_ok=True);log=logs/f'{key(child)}-{time.time_ns()}.log'
    process=None
    def abort(sig,frame):raise RuntimeError(f'ledger signal {sig}')
    handlers={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
    for s in handlers:signal.signal(s,abort)
    try:
        with log.open('xb') as stream:
            process=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT);deadline=time.monotonic()+710
            while process.poll() is None:
                c.require(not (root/'STOP').exists(),'ledger STOP requested during child')
                c.require(time.monotonic()<deadline,'ledger child deadline');time.sleep(.25)
        c.require(process.returncode==0,'child failed; reservation and evidence retained')
        complete(root,v)
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:process.wait(timeout=60)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
        for s,h in handlers.items():signal.signal(s,h)
        refresh(root)
    return refresh(root)


def main(args):
    root=args.root
    if args.command=='ledger-plan':return create(root,args.ledger_max_new_batches)
    load(root)
    with m.lock(root):
        if args.command=='ledger-status':return refresh(root,deep=args.ledger_deep)
        c.require(args.campaign_root is not None,'campaign root required')
        if args.command=='ledger-import':
            c.require(args.inventory is not None,'sealed import inventory required')
            return import_completed(root,args.campaign_root,args.inventory)
        if args.command=='ledger-reserve':return reserve(root,args.campaign_root,args.batch_indices)
        return run(root,args.campaign_root,args.retry_failed)
