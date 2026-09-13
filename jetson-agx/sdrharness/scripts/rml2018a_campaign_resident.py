"""Finite receive/CPU pipeline, disk input cache, then one resident RF-v1 model.

Only the campaign CLI owns this workflow. Replay mode has no radio executor;
acquisition mode requires current finite event-chunk parents. No model tuning.
"""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager, ExitStack
import multiprocessing
import os
from pathlib import Path
import shutil
import signal
import time
import zipfile

import numpy as np
import rml2018a_campaign_ledger as l
c=l.c;e=l.e;m=l.m
CACHE_LIMIT=600000
RESERVE=512*1024**2


class Resident:
    def __init__(self,backend,root,maximum,deadline):
        self.backend=backend;self.root=root;self.maximum=maximum;self.deadline=deadline;self.calls=0
        self.admission_identity=backend.admission_identity
        self.identity=dict(root=str(root),plan_sha256=c.file_hash(root/'resident-plan.json'),pid=os.getpid(),model_loads=1)

    def check(self):
        c.require(self.backend is not None and time.monotonic()<self.deadline,'resident closed/deadline')
        c.require(not (self.root/'STOP').exists(),'resident STOP')

    def classify_logits(self,tensor):
        self.check();c.require(self.calls<self.maximum,'resident model window budget')
        self.calls+=1 # Failed calls also consume the finite allowance.
        return self.backend.classify_logits(tensor)


@contextmanager
def session(root,maximum,deadline):
    scratch=root/'scratch';scratch.mkdir(mode=0o700,exist_ok=True)
    os.environ.update(TMPDIR=str(scratch),XDG_CACHE_HOME=str(scratch),TRITON_CACHE_DIR=str(scratch/'triton'),
        CUDA_CACHE_PATH=str(scratch/'cuda'),PYTHONDONTWRITEBYTECODE='1')
    from gpu_lease import GpuLease
    lease=GpuLease(scratch/'gpu-gate','mamba');token=None;resident=None
    audit=dict(status='failed',pid=os.getpid(),model_loads=0,model_windows=0,warmup_windows=0,started_ns=time.time_ns())
    try:
        token=asyncio.run(lease.acquire(min(deadline,time.monotonic()+10),request='resident-rml-campaign'))
        multi=m.module('resident_multi','validate-b210-multiclass.py')
        with multi.idle_spark_pause(evidence_root=root):
            started=time.monotonic();w=m.module('resident_worker','amc-mamba-worker.py')
            backend=w.RfV1Backend(m.PROFILE)
            c.require(all(p.dtype==w.torch.float32 for p in backend.model.parameters()),'resident FP32 weights')
            resident=Resident(backend,root,maximum,deadline)
            audit.update(model_loads=1,warmup_windows=2,load_and_warmup_seconds=time.monotonic()-started,
                model_identity=backend.admission_identity)
            del backend
            try:yield resident
            finally:
                audit['model_windows']=resident.calls;resident.backend=None
        audit['status']='completed'
    except BaseException as error:
        audit['error']=f'{type(error).__name__}: {error}';raise
    finally:
        if token is not None:lease.release(token)
        audit.update(finished_ns=time.time_ns(),lease=lease.metrics.copy());lease.close()
        c.save(root/'resident-session.json',audit)


def parent(child,acquire):
    l.private_root(child);p=m.load_plan(child) if acquire else m.document(child/'run-plan.json')
    c.require(p['tx_level_profile']=='event-chunk','resident event-chunk parent')
    c.require(p['source']['sha256']==l.DATA_SHA and p['profile_sha256']==c.file_hash(m.PROFILE) and
        p['label_map_sha256']==c.file_hash(m.LABELS),'resident source/model/labels')
    if not acquire:
        orchestration={'rml2018a-rf-campaign.py','rml2018a_campaign_events.py','rml2018a_campaign_ledger.py',
            'rml2018a_campaign_coverage.py','rml2018a_campaign_resident.py','compare-rml2018a-pilot-timing.py'}
        current=l.software()
        c.require(all(current.get(path)==sha for path,sha in p['event_software'].items() if Path(path).name not in orchestration),'resident unchanged scientific assets')
        c.require(p['guard_contract']==e.r.guard.contract(),'resident guard contract')
        c.require(all(e.capture_complete(child,p,i) for i in e.indices(p)),'resident replay requires completed RX')
    return p


def create(root,children,acquire=False):
    l.private_root(root);c.require(not root.exists() and children and len(set(children))==len(children) and root not in children,'new resident scope')
    tasks=[];parents=[];seen=set()
    for child in children:
        p=parent(child,acquire);ids=e.indices(p)
        c.require(not seen.intersection(ids),'resident duplicate source batches');seen.update(ids)
        parents.append(dict(root=str(child),plan_sha256=c.file_hash(child/'run-plan.json'),
            inventory=None if acquire else l.inventory(child)))
        for i in ids:tasks.append(dict(child=str(child),batch=i,ordinal=len(tasks)))
    c.require(1<=len(tasks)<=32,'resident maximum32 batches')
    c.require(shutil.disk_usage(root.parent).free>RESERVE,'resident disk reserve')
    c.require(c.file_hash(m.DATASET)==l.DATA_SHA,'resident full source pin')
    root.mkdir(mode=0o700)
    p=dict(schema='rml2018a-resident-session-v1',acquire=acquire,parents=parents,tasks=tasks,
        source=l.source_identity(),software=l.software(),maximum_model_windows=len(tasks)*72,maximum_warmup_windows=2,
        maximum_tx_seconds=len(tasks)*4 if acquire else 0,maximum_rx_bytes=len(tasks)*262140 if acquire else 0,
        maximum_cache_bytes=len(tasks)*CACHE_LIMIT,cache_file_limit=CACHE_LIMIT,maximum_pending_cpu_batches=2,
        reserve_bytes=RESERVE,free_bytes=shutil.disk_usage(root).free,deadline_seconds=600,
        ordering='Receive and single CPU worker preprocess/verify concurrently; persist normalized inputs to disk. Join all RX/CPU before loading model once; infer in original task order.',
        profile_sha256=c.file_hash(m.PROFILE),label_map_sha256=c.file_hash(m.LABELS),
        recognizer_available=False,automatic_retry=False,automatic_next_session=False,
        stop='Create this root/STOP or send SIGINT/SIGTERM to parent; forward to finite session child. Existing Controller cancel and Spark restore watchdog remain active.',
        created_ns=time.time_ns())
    c.save(root/'resident-plan.json',p);return dict(status='planned',plan_sha256=c.file_hash(root/'resident-plan.json'),**{k:p[k] for k in ('tasks','maximum_model_windows','maximum_tx_seconds','maximum_rx_bytes','maximum_cache_bytes')})


def load(root):
    l.private_root(root);p=m.document(root/'resident-plan.json')
    c.require(p['schema']=='rml2018a-resident-session-v1' and p['source']==l.source_identity() and p['software']==l.software(),'resident identity changed')
    n=len(p['tasks']);c.require(1<=n<=32 and p['maximum_model_windows']==n*72 and p['maximum_warmup_windows']==2 and
        p['maximum_cache_bytes']==n*CACHE_LIMIT and p['cache_file_limit']==CACHE_LIMIT and p['maximum_pending_cpu_batches']==2 and
        p['deadline_seconds']==600 and p['reserve_bytes']==RESERVE and type(p['acquire']) is bool and
        p['maximum_tx_seconds']==(n*4 if p['acquire'] else 0) and p['maximum_rx_bytes']==(n*262140 if p['acquire'] else 0),'resident finite limits')
    tasks=[];seen=set()
    for v in p['parents']:
        child=Path(v['root']);c.require(child!=root and c.file_hash(child/'run-plan.json')==v['plan_sha256'],'resident parent plan')
        if not p['acquire']:l.check_inventory(v['inventory'])
        cp=parent(child,p['acquire'])
        for i in e.indices(cp):
            c.require(i not in seen,'resident duplicate batch');seen.add(i);tasks.append(dict(child=str(child),batch=i,ordinal=len(tasks)))
    c.require(tasks==p['tasks'],'resident ordered tasks')
    return p


def prepare_task(root,task):
    child=Path(task['child']);p=m.document(child/'run-plan.json');started=time.time_ns()
    report,tensors=e.prepare(child,p,[task['batch']]);arrays={}
    for tag,values in tensors[task['batch']].items():
        if values is not None:arrays[tag]=np.stack([c.normalize_window(x) for x in values])
    out=root/'prepared'/f"task-{task['ordinal']:03d}";out.mkdir(parents=True,mode=0o700)
    c.save(out/'prepared.json',report)
    with (out/'inputs.npz').open('xb') as stream:np.savez(stream,**arrays)
    size=(out/'inputs.npz').stat().st_size;c.require(size<=CACHE_LIMIT,'resident cache size')
    receipt=dict(task=task,prepared_sha256=c.file_hash(out/'prepared.json'),cache_sha256=c.file_hash(out/'inputs.npz'),cache_bytes=size,
        started_ns=started,finished_ns=time.time_ns(),pid=os.getpid())
    c.save(out/'cache.json',receipt);return receipt


def cached(root,task):
    out=root/'prepared'/f"task-{task['ordinal']:03d}";receipt=m.document(out/'cache.json')
    c.require(receipt['task']==task and c.file_hash(out/'prepared.json')==receipt['prepared_sha256'],'resident prepared pin')
    path=out/'inputs.npz';c.require(path.is_file() and not path.is_symlink() and path.stat().st_size==receipt['cache_bytes']<=CACHE_LIMIT and c.file_hash(path)==receipt['cache_sha256'],'resident cache pin')
    with zipfile.ZipFile(path) as z:
        c.require(len(z.infolist())<=3 and all(i.compress_type==zipfile.ZIP_STORED and i.file_size<200000 for i in z.infolist()),'resident bounded uncompressed cache')
    report=m.document(out/'prepared.json');parts={}
    with np.load(path,allow_pickle=False) as blob:
        expected={tag for tag in e.TAGS if report['results'][0]['rows'][0]['inputs'][tag] is not None}
        c.require(set(blob.files)==expected,'resident cache tags')
        for tag in e.TAGS:
            values=blob[tag] if tag in expected else None
            if values is not None:
                c.require(values.shape==(24,2,1024) and values.dtype==np.float32 and np.isfinite(values).all(),'resident cache tensor')
                c.require(all(c.digest(x.tobytes())==row['inputs'][tag] for x,row in zip(values,report['results'][0]['rows'])),'resident cached input hash')
            parts[tag]=values
    return report,{task['batch']:parts}


def combined(root,tasks):
    reports=[];tensors={}
    for task in tasks:
        report,parts=cached(root,task);reports.append(report);tensors.update(parts)
    c.require(reports and len({r['parent_plan_sha256'] for r in reports})==1,'resident combined parent')
    return dict(reports[0],source_rows=len(tasks)*24,maximum_model_windows=len(tasks)*72,
        results=[b for r in reports for b in r['results']]),tensors


def worker(root):
    p=load(root);audit=dict(status='failed',pid=os.getpid(),started_ns=time.time_ns(),parent_plan_sha256=c.file_hash(root/'resident-plan.json'),cpu_receipts=[])
    c.save(root/'started.json',audit)
    def abort(sig,frame):raise RuntimeError(f'resident cancelled by signal {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
    signal.alarm(p['deadline_seconds']);deadline=time.monotonic()+p['deadline_seconds']
    try:
        with ExitStack() as locks:
            if p['acquire']:
                ledgers=set()
                for v in p['parents']:
                    cp=m.document(Path(v['root'])/'run-plan.json')
                    if cp.get('source_verification'):ledgers.add(Path(cp['source_verification']['ledger_root']))
                c.require(len(ledgers)<=1,'one owning ledger per resident session')
                for ledger in sorted(ledgers):
                    locks.enter_context(m.lock(ledger));state=l.refresh(ledger);l.gate(l.load(ledger),state)
                    c.require(state['retained_bytes']+state['outstanding_reserve_bytes']+RESERVE<=l.TOTAL_CAP,'resident extra storage reserve')
                for v in p['parents']:locks.enter_context(m.lock(Path(v['root'])))
            # Only this process performs RF; the one CPU child consumes completed native captures.
            pending=[]
            with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn')) as pool:
                for task in p['tasks']:
                    c.require(not (root/'STOP').exists() and shutil.disk_usage(root).free>RESERVE,'resident STOP/space')
                    if p['acquire']:
                        child=Path(task['child']);cp=m.load_plan(child)
                        if cp.get('source_verification'):
                            ledger=Path(cp['source_verification']['ledger_root']);l.gate(l.load(ledger),l.refresh(ledger))
                        e.acquire_batch(child,cp,task['batch'])
                    pending.append(pool.submit(prepare_task,root,task))
                    if len(pending)>=2:audit['cpu_receipts'].append(pending.pop(0).result())
                for future in pending:audit['cpu_receipts'].append(future.result())
            audit['receive_preprocess_finished_ns']=time.time_ns()
            c.save(root/'prepared-stage.json',audit)
            c.require(sum(v['cache_bytes'] for v in audit['cpu_receipts'])<=p['maximum_cache_bytes'],'resident total cache limit')
            with session(root,p['maximum_model_windows'],deadline) as resident:
                for ordinal,v in enumerate(p['parents']):
                    resident.check();child=Path(v['root']);cp=m.document(child/'run-plan.json')
                    tasks=[t for t in p['tasks'] if t['child']==str(child)]
                    if p['acquire']:
                        def provider(indices):return combined(root,[t for t in tasks if t['batch'] in indices])
                        e.infer_batches(child,cp,e.indices(cp),resident=resident,prepare_inputs=provider)
                    else:
                        report,tensors=combined(root,tasks);provider=lambda _: (report,tensors)
                        out=root/f'inference-{ordinal:03d}';out.mkdir(mode=0o700);c.save(out/'prepared.json',report)
                        e.r.compare.infer(child,out,prepare_inputs=provider,resident=resident,normalized_inputs=True)
                        e.r.compare.verify(child,out,prepare_inputs=provider)
            if p['acquire']:
                for v in p['parents']:
                    child=Path(v['root']);cp=m.load_plan(child);e.summarize(child,cp);e.pause_receipt(child,cp,e.indices(cp),'run')
                    if cp.get('source_verification'):
                        ledger=Path(cp['source_verification']['ledger_root']);l.complete(ledger,m.document(l.entry_path(ledger,child)));l.refresh(ledger)
            audit['status']='completed'
    except BaseException as error:
        audit['error']=f'{type(error).__name__}: {error}';raise
    finally:
        signal.alarm(0);audit['finished_ns']=time.time_ns();c.save(root/'execution.json',audit)


def run(root):
    p=load(root)
    with m.lock(root):
        c.require(not (root/'STOP').exists(),'resident STOP')
        if (root/'completion.json').exists():
            done=m.document(root/'completion.json');c.require(done['plan_sha256']==c.file_hash(root/'resident-plan.json'),'resident completion association')
            l.check_inventory(done['files']);return dict(status='already_completed',new_model_windows=0,new_tx_seconds=0)
        c.require(not (root/'started.json').exists(),'resident attempt retained; no automatic retry')
        c.require(shutil.disk_usage(root).free>RESERVE,'resident free space')
        process=multiprocessing.get_context('spawn').Process(target=worker,args=(root,));process.start()
        def abort(sig,frame):raise RuntimeError(f'resident parent signal {sig}')
        handlers={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
        for sig in handlers:signal.signal(sig,abort)
        try:
            end=time.monotonic()+620
            while process.is_alive():
                c.require(not (root/'STOP').exists() and time.monotonic()<end,'resident parent STOP/deadline');process.join(.25)
            c.require(process.exitcode==0 and m.document(root/'execution.json')['status']=='completed','resident child failed; evidence retained')
        finally:
            if process.is_alive():os.kill(process.pid,signal.SIGINT);process.join(60)
            if process.is_alive():process.terminate();process.join(10)
            if process.is_alive():process.kill();process.join(5)
            c.require(not process.is_alive(),'resident child survived stop');process.close()
            for sig,handler in handlers.items():signal.signal(sig,handler)
        # Completion is published only after CUDA process exit and Spark restoration.
        gpu=m.document(root/'gpu-isolation.json');c.require(gpu['resumed'] and gpu['restore_watchdog_stopped'],'resident Spark restoration')
        removed=l.prune_scratch(root)
        for path in sorted(root.glob('prepared/task-*/inputs.npz')):
            c.require(path.resolve()==path and path.stat().st_size<=CACHE_LIMIT,'resident cache cleanup identity')
            removed.append(dict(path=str(path),bytes=path.stat().st_size,sha256=c.file_hash(path)));path.unlink()
        c.save(root/'cache-cleanup.json',dict(removed=removed,bytes=sum(v['bytes'] for v in removed)))
        files=l.inventory(root);c.save(root/'completion.json',dict(plan_sha256=c.file_hash(root/'resident-plan.json'),files=files))
        return dict(m.document(root/'resident-session.json'),source_rows=len(p['tasks'])*24)
