"""Read sealed all-SNR corpora with one frozen, batch-one RF-v1 model.

No RF or training entry points. Per-block predictions are atomic and restartable;
source IQ and acquisition receipts are never opened for writing.
"""
import argparse
import asyncio
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import h5py
import numpy as np

import rml2018a_campaign as c
from rml2018a_campaign_gpu import snr_block_rows
from rml2018a_campaign_store import TAGS, atomic_json, block_hash, sync_directory

SCRIPTS = Path(__file__).resolve().parent
CONFIG = c.REPO/'jetson-agx/sdrharness/config/amc'
PROFILE = CONFIG/'rml2018a-d8-rf-v1.runtime-profile.json'
LABELS = CONFIG/'rml2018a-labels.server-v1.json'
TOTAL = 2555904
RESERVE = 4*1024**3


def read(path):
    return json.loads(Path(path).read_text())


def software():
    return {str(p): c.file_hash(p) for p in sorted(SCRIPTS.glob('*.py'))}


def corpus(campaign):
    done = read(campaign/'acquisition-complete.json')
    c.require(done.get('complete') and done.get('inference_eligible') and
              done['source_rows'] == TOTAL and done['completed_snr_groups'] == 26,
              'all26 acquisition gate')
    c.require(read(campaign/'service-state.json')['phase'] == 'complete' and
              read(campaign/'final-radio-state.json')['restored'], 'finished RF owner')
    c.require(done['ledger_plan_sha256'] == c.file_hash(campaign/'ledger-plan.json'), 'acquisition plan pin')
    groups = []
    for pair in done['groups']:
        receipt_path = campaign/'entries'/f"{pair['index']:02d}.complete.json"
        receipt = read(receipt_path)
        c.require(receipt['root'] == pair['root'] and receipt['snrs'] == pair['snrs'] and
                  receipt['source_rows'] == 196608 and
                  c.file_hash(Path(receipt['receipt'])) == receipt['receipt_sha256'], 'pair receipt')
        for z in pair['snrs']:
            name = f'snr-plus{z}' if z >= 0 else f'snr-minus{abs(z)}'
            root = Path(pair['root'])/name
            index = read(root/'index.json'); config = read(root/'configuration.json')
            c.require(index['complete'] and len(index['processed']) == 96 and
                      config['source_snr_db'] == z and
                      config['profile_sha256'] == c.file_hash(PROFILE) and
                      config['label_map_sha256'] == c.file_hash(LABELS), 'sealed compatible SNR')
            for file in ('index.json', 'configuration.json', 'raw.sigmf-meta'):
                c.require(c.file_hash(root/file) == receipt['sealed_artifacts'][f'{name}/{file}'], 'sealed metadata pin')
            groups.append(dict(snr=z, root=str(root), index_sha256=c.file_hash(root/'index.json'),
                               configuration_sha256=c.file_hash(root/'configuration.json'),
                               processed_sha256=index['processed_sha256']))
    c.require(len(groups) == 26 and {g['snr'] for g in groups} == set(range(-20,31,2)), 'unique SNR coverage')
    return groups


def plan(campaign, root):
    c.require(root.parent == Path('/var/tmp/sdrharness-dev') and root.resolve() == root and
              not root.exists(), 'new private inference root')
    groups = corpus(campaign)
    c.require(shutil.disk_usage(root.parent).free > RESERVE, 'inference free space')
    root.mkdir(mode=0o700)
    value = dict(schema='rml2018a-all26-offline-inference-v1', campaign=str(campaign), groups=groups,
                 acquisition_sha256=c.file_hash(campaign/'acquisition-complete.json'),
                 software=software(), profile_sha256=c.file_hash(PROFILE), label_map_sha256=c.file_hash(LABELS),
                 total_rows=TOTAL, maximum_model_windows=TOTAL*3, maximum_warmup_windows=2,
                 deadline_seconds=7*86400, reserve_bytes=RESERVE, batch_size=1, tags=list(TAGS),
                 model='frozen epoch10 FP32 weights / FP16 autocast / existing RF-v1 backend',
                 semantics='All-source engineering comparison; not independent locked-test admission. '
                           'SINR is conditional, invalid SINR does not exclude predictions. '
                           'Missing inputs keep full denominators. Labels remain provisional.',
                 maximum_rf_samples=0, recognizer_available=False, spark='must remain inactive',
                 automatic_retry=False, created_ns=time.time_ns())
    atomic_json(root/'plan.json', value)
    return value


def load_block(group, index, number):
    z = group['snr']; root = Path(group['root'])
    with h5py.File(root/'processed.h5', 'r') as f:
        c.require(f.attrs['configuration_sha256'] == group['configuration_sha256'] and
                  set(f['blocks']) == {f'{i:03d}' for i in range(96)}, 'HDF5 identity/blocks')
        b = f['blocks'][f'{number:03d}']
        rows = b['source_row'][:]; ids = b['class_id'][:]
        c.require(np.array_equal(rows, snr_block_rows(z, number)) and
                  np.array_equal(ids, rows//106496) and (b['source_snr_db'][:] == z).all(), 'row/class/Z mapping')
        inputs = {t:b['inputs/'+t][:] for t in TAGS}
        masks = {t:b['valid/'+t][:] for t in TAGS}
        quality = [json.loads(v) for v in b['quality_json'].asstr()[:]]
        sha = block_hash(inputs, masks, b['raw_sample_start'][:], b['raw_sample_count'][:], quality)
        c.require(sha == index['processed'][number]['payload_sha256'] == b.attrs['payload_sha256'], 'input payload SHA')
    for tag in TAGS:
        c.require(inputs[tag].shape == (1024,2,1024) and inputs[tag].dtype == np.float32 and
                  masks[tag].dtype == np.bool_ and masks[tag].shape == (1024,), 'input shape/type')
        valid = inputs[tag][masks[tag]]
        c.require(np.isfinite(valid).all() and np.isnan(inputs[tag][~masks[tag]]).all(), 'input validity')
        rms = np.sqrt(np.mean(np.sum(valid.astype(np.float64)**2, axis=1), axis=1))
        c.require(np.all(abs(rms-1) <= 1e-6), 'frozen input RMS')
    return rows, ids, inputs, masks, quality


def statistics(ids, logits, masks, quality):
    result = {}
    for tag in TAGS:
        valid = masks[tag]
        c.require(logits[tag].shape == (len(ids),24) and np.isfinite(logits[tag][valid]).all() and
                  np.isnan(logits[tag][~valid]).all(), 'prediction/missing validity')
        pred = np.full(len(ids), -1, dtype=int)
        pred[valid] = logits[tag][valid].argmax(axis=1)
        matrix = np.zeros((24,24), dtype=np.int64)
        np.add.at(matrix, (ids[valid], pred[valid]), 1)
        statuses = {}; reasons = {}; bins = {}
        if tag != 'source':
            for i,q in enumerate(quality):
                v = q[tag]; status = v['rx_sinr_status']
                stat = statuses.setdefault(status, dict(total=0,predicted=0,correct=0))
                stat['total'] += 1; stat['predicted'] += int(valid[i]); stat['correct'] += int(pred[i] == ids[i])
                if status == 'estimated':
                    key = str(int(np.floor(v['rx_sinr_db']/2)*2))
                    b = bins.setdefault(key, dict(total=0,predicted=0,correct=0))
                    b['total'] += 1; b['predicted'] += int(valid[i]); b['correct'] += int(pred[i] == ids[i])
                else:
                    reason = v.get('rx_sinr_reason', 'unspecified')
                    reasons[reason] = reasons.get(reason,0)+1
        result[tag] = dict(total=len(ids), predicted=int(valid.sum()), correct=int((pred==ids).sum()),
                           missing=int((~valid).sum()), confusion=matrix.tolist(),
                           class_total=np.bincount(ids,minlength=24).tolist(),
                           sinr_status=statuses, sinr_reasons=reasons, sinr_bins_2db=bins)
    return result


def merge(a, b):
    for k,v in b.items():
        if isinstance(v, dict): merge(a.setdefault(k,{}), v)
        elif isinstance(v, list): a[k] = (np.asarray(a.get(k,np.zeros_like(v)))+np.asarray(v)).tolist()
        else: a[k] = a.get(k,0)+v


def publish(root, key, rows, ids, logits, masks, stats, input_sha):
    path = root/'blocks'/f'{key}.npz'; pending = path.with_suffix('.pending')
    c.require(not path.exists() and not pending.exists(), 'no overwrite of partial predictions')
    with pending.open('xb') as f:
        np.savez(f, source_row=rows, class_id=ids, **{f'logits_{t}':logits[t] for t in TAGS},
                 **{f'valid_{t}':masks[t] for t in TAGS})
        f.flush(); os.fsync(f.fileno())
    os.replace(pending,path); sync_directory(path.parent)
    receipt = dict(input_sha256=input_sha, output_sha256=c.file_hash(path), statistics=stats,
                   rows=len(rows), completed_ns=time.time_ns())
    atomic_json(path.with_suffix('.json'), receipt)
    return receipt


def spark_stopped():
    state = subprocess.run(['systemctl','show','spark-x25.service','-p','ActiveState','-p','MainPID'],
                           capture_output=True,text=True,check=True,timeout=10).stdout.splitlines()
    c.require('ActiveState=inactive' in state and 'MainPID=0' in state, 'Spark must remain stopped')


def run(root):
    p = read(root/'plan.json')
    c.require(p['software'] == software() and p['profile_sha256'] == c.file_hash(PROFILE) and
              p['label_map_sha256'] == c.file_hash(LABELS), 'inference software/profile pin')
    c.require(p['maximum_model_windows'] == TOTAL*3 and p['batch_size'] == 1 and
              p['groups'] == corpus(Path(p['campaign'])) and
              p['acquisition_sha256'] == c.file_hash(Path(p['campaign'])/'acquisition-complete.json'), 'inference plan scope')
    lock = (root/'owner.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    c.require(not (root/'complete.json').exists(), 'already complete; inspect result instead')
    (root/'blocks').mkdir(exist_ok=True)
    scratch = root/'scratch'; scratch.mkdir(mode=0o700,exist_ok=True)
    os.environ.update(TMPDIR=str(scratch), XDG_CACHE_HOME=str(scratch), CUDA_CACHE_PATH=str(scratch/'cuda'),
                      TRITON_CACHE_DIR=str(scratch/'triton'), PYTHONDONTWRITEBYTECODE='1')
    started = time.monotonic(); deadline = started+p['deadline_seconds']; calls = 0
    state = dict(phase='starting',pid=os.getpid(),completed_blocks=0,total_blocks=2496,completed_rows=0,
                 model_loads=0,model_windows=0,started_ns=time.time_ns())
    total = {}; by_snr = {}; token = None; lease = None; backend = None
    def status(**fields):
        state.update(fields,updated_ns=time.time_ns(),elapsed_seconds=time.monotonic()-started)
        atomic_json(root/'state.json',state)
    def check():
        c.require(not (root/'STOP').exists() and time.monotonic()<deadline, 'inference STOP/deadline')
    def stop(*_): raise InterruptedError('inference signal stop')
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,stop)
    try:
        check(); spark_stopped(); status(phase='loading_model')
        from gpu_lease import GpuLease
        lease = GpuLease(scratch/'gpu-gate','mamba')
        token = asyncio.run(lease.acquire(time.monotonic()+10,request='sealed-all26-inference'))
        spec = importlib.util.spec_from_file_location('snr_frozen_worker', SCRIPTS/'amc-mamba-worker.py')
        worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
        backend = worker.RfV1Backend(PROFILE)
        c.require(all(v.dtype == worker.torch.float32 for v in backend.model.parameters()) and
                  not backend.model.training, 'frozen FP32 eval model')
        atomic_json(root/'model.json',dict(identity=backend.admission_identity,model_loads=1,warmup_windows=2,
                                         batch_size=1,compute='FP16 autocast; FP32 weights/logits',pid=os.getpid()))
        status(phase='model_loaded',model_loads=1)
        for g in p['groups']:
            check(); spark_stopped(); z = g['snr']; folder = Path(g['root'])
            status(phase='verifying_snr',source_snr_db=z)
            c.require(c.file_hash(folder/'processed.h5') == g['processed_sha256'], 'sealed HDF5 hash')
            index = read(folder/'index.json'); by_snr[str(z)] = {}
            for block in range(96):
                check(); key = f'{z:+03d}-{block:03d}'; target = root/'blocks'/f'{key}.json'
                rows,ids,inputs,masks,quality = load_block(g,index,block)
                sha = index['processed'][block]['payload_sha256']
                if target.exists():
                    r = read(target)
                    c.require(r['input_sha256'] == sha and c.file_hash(target.with_suffix('.npz')) == r['output_sha256'], 'committed result pin')
                    with np.load(target.with_suffix('.npz'),allow_pickle=False) as f:
                        c.require(np.array_equal(f['source_row'],rows) and np.array_equal(f['class_id'],ids) and
                                  all(np.array_equal(f['valid_'+t],masks[t]) for t in TAGS), 'result lineage')
                        stats = statistics(ids,{t:f['logits_'+t] for t in TAGS},masks,quality)
                    c.require(stats == r['statistics'], 'committed statistics')
                else:
                    c.require(shutil.disk_usage(root).free > RESERVE, 'inference disk reserve')
                    logits = {t:np.full((1024,24),np.nan,dtype=np.float32) for t in TAGS}
                    for tag in TAGS:
                        for i in np.flatnonzero(masks[tag]):
                            check(); c.require(calls < p['maximum_model_windows'], 'model window bound')
                            calls += 1
                            logits[tag][i] = backend.classify_logits(inputs[tag][i])[0]
                            if calls%64 == 0:
                                status(phase='inferring',block=block,tag=tag,model_windows=calls)
                    stats = statistics(ids,logits,masks,quality)
                    r = publish(root,key,rows,ids,logits,masks,stats,sha)
                merge(total,stats); merge(by_snr[str(z)],stats)
                status(phase='inferring',block=block,completed_blocks=state['completed_blocks']+1,
                       completed_rows=state['completed_rows']+1024,model_windows=calls)
                atomic_json(root/'summary.json',dict(complete=False,classification=total,by_source_snr_db=by_snr,
                            labels=read(LABELS)['classes'],semantics=p['semantics'],recognizer_available=False))
                print(json.dumps({k:state[k] for k in ('completed_blocks','completed_rows','source_snr_db','elapsed_seconds')}),flush=True)
            spark_stopped()
        c.require(state['completed_rows'] == TOTAL and state['completed_blocks'] == 2496, 'full inference accounting')
        result = read(root/'summary.json'); result['complete'] = True
        atomic_json(root/'summary.json',result)
        atomic_json(root/'complete.json',dict(source_rows=TOTAL,blocks=2496,summary_sha256=c.file_hash(root/'summary.json'),
                                             plan_sha256=c.file_hash(root/'plan.json'),completed_ns=time.time_ns()))
        status(phase='complete',model_windows=calls)
    except BaseException as error:
        status(phase='stopped' if isinstance(error,InterruptedError) else 'failed',error=repr(error),model_windows=calls)
        raise
    finally:
        if backend is not None:
            del backend
            worker.torch.cuda.synchronize(); worker.torch.cuda.empty_cache()
        if token is not None: lease.release(token)
        if lease is not None: lease.close()
        removed = [dict(path=str(v),bytes=v.stat().st_size) for v in scratch.rglob('*') if v.is_file()]
        c.require(scratch.resolve() == root/'scratch', 'exact scratch cleanup')
        shutil.rmtree(scratch)
        c.require(not scratch.exists(), 'scratch removed')
        retained = [dict(path=str(v),bytes=v.stat().st_size,sha256=c.file_hash(v))
                    for v in sorted(root.rglob('*')) if v.is_file() and v.name != 'retention.json']
        atomic_json(root/'retention.json',dict(purpose='Full RF engineering inference and per-row logits; source corpus referenced without copying',
                    parent_campaign=p['campaign'],model_profile_sha256=p['profile_sha256'],
                    removed=removed,removed_bytes=sum(v['bytes'] for v in removed),
                    retained=retained,retained_bytes=sum(v['bytes'] for v in retained),
                    manual_delete_argv=['rm','-rf','--',str(root)],
                    deletion_constraint='Only after service stopped and these inference results are no longer needed; parent RF corpus is separate.'))
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','run'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--campaign',type=Path)
    args = parser.parse_args()
    if args.command == 'plan':
        c.require(args.campaign is not None,'campaign required')
        plan(args.campaign,args.root)
    else: run(args.root)


if __name__ == '__main__': main()
