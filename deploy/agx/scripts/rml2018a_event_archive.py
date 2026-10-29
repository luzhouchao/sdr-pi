"""Lossless, bounded event archives and conservative finite-chunk storage budgets."""
import gzip
import json
from pathlib import Path
import shutil
import zlib
import rml2018a_campaign as c

RAW_LIMIT=16000000
ARCHIVE_LIMIT=2*1024*1024
METADATA_PER_BATCH=2*1024*1024
SCRATCH_RESERVE=256*1024*1024
FAILURE_POOL=8*1024**3


def batches(values):
    c.require(isinstance(values,list) and 1<=len(values)<=32 and len(set(values))==len(values) and
        all(type(i) is int and 0<=i<106496 for i in values),'1-32 unique registered chunk batches')
    return values


def budget(values):
    n=len(batches(values));success=ARCHIVE_LIMIT+c.RX_SAMPLES*4+METADATA_PER_BATCH
    failed=RAW_LIMIT+c.RX_SAMPLES*4+METADATA_PER_BATCH
    return dict(allowed_batch_indices=values,maximum_attempts_per_batch=2,
        maximum_tx_seconds=n*8,maximum_tx_samples=n*2*8381952,
        maximum_rx_iq_bytes=n*2*c.RX_SAMPLES*4,maximum_source_rows=n*24,
        maximum_inference_attempts_per_shard=2,maximum_model_windows=n*72*2,maximum_warmup_windows=n*4,
        maximum_event_raw_bytes=RAW_LIMIT,maximum_event_archive_bytes=ARCHIVE_LIMIT,
        metadata_reserve_per_batch=METADATA_PER_BATCH,
        successful_retention_budget_bytes=n*success,failed_attempt_reserve_bytes=n*failed,
        transient_event_reserve_bytes=RAW_LIMIT+ARCHIVE_LIMIT,
        scratch_reserve_bytes=SCRATCH_RESERVE,
        reserve_bytes=n*(success+failed)+RAW_LIMIT+ARCHIVE_LIMIT+SCRATCH_RESERVE,
        full_dataset_projection=dict(batches=106496,source_rows=2555904,
            successful_retention_budget_bytes=106496*success,
            failure_pool_bytes=FAILURE_POOL,
            required_bytes=106496*success+FAILURE_POOL+RAW_LIMIT+ARCHIVE_LIMIT+SCRATCH_RESERVE,
            maximum_tx_seconds_without_retries=106496*4,
            condition='Projection only: requires every successful archive<=2MiB and metadata<=2MiB per batch; stop when failure pool/space is exhausted. No automatic full-run authorization.'))


def decompress(data):
    c.require(len(data)<=ARCHIVE_LIMIT,'compressed event byte bound')
    decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
    result=decoder.decompress(data,RAW_LIMIT)
    c.require(len(result)<RAW_LIMIT and decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data,
        'bounded single gzip member, no truncation/trailing data')
    return result


def read(path):
    path=Path(path)
    if path.suffix!='.gz':
        c.require(path.stat().st_size<RAW_LIMIT,'raw event byte bound');return path.read_bytes()
    c.require(path.stat().st_size<=ARCHIVE_LIMIT,'compressed event byte bound')
    return decompress(path.read_bytes())


def seal(directory):
    """Only newly acquired, restored successful captures; never old sealed evidence."""
    directory=Path(directory);raw=directory/'tx-events.jsonl';archive=directory/'tx-events.jsonl.gz';receipt=directory/'event-storage.json'
    if receipt.exists():
        value=json.loads(receipt.read_text());verify(directory)
        if raw.exists():
            c.require(c.file_hash(raw)==value['original_sha256'] and raw.stat().st_size==value['original_bytes'],'pending original cleanup')
            raw.unlink()
        return value
    c.require(raw.is_file() and not raw.is_symlink()  ,'fresh archive or sealed recovery required')
    data=read(raw);encoded=gzip.compress(data,compresslevel=6,mtime=0)
    c.require(len(encoded)<=ARCHIVE_LIMIT and decompress(encoded)==data,'lossless archive ceiling; preserve raw and stop')
    if archive.exists():c.require(archive.is_file() and not archive.is_symlink() and archive.read_bytes()==encoded,'partial archive changed')
    else:
        with archive.open('xb') as stream:stream.write(encoded);stream.flush();__import__('os').fsync(stream.fileno())
    value=dict(schema='rml2018a-event-gzip-v1',original_bytes=len(data),original_sha256=c.digest(data),
        archive_bytes=len(encoded),archive_sha256=c.digest(encoded),codec='single-member-gzip-level6-mtime0',
        lossless=True,records_removed=0,original_path=str(raw),archive_path=str(archive))
    c.save(receipt,value);verify(directory);raw.unlink();return value


def verify(directory):
    directory=Path(directory);value=json.loads((directory/'event-storage.json').read_text())
    path=directory/'tx-events.jsonl.gz'
    c.require(value['schema']=='rml2018a-event-gzip-v1' and value['lossless'] and value['records_removed']==0 and
        value['archive_path']==str(path) and value['original_path']==str(directory/'tx-events.jsonl'),'archive identity')
    c.require(path.is_file() and not path.is_symlink() and path.stat().st_size==value['archive_bytes'] and
        c.file_hash(path)==value['archive_sha256'],'archive seal')
    data=read(path)
    c.require(len(data)==value['original_bytes'] and c.digest(data)==value['original_sha256'],'original event byte replay')
    return path


def space(root,limits):
    used=sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())
    free=shutil.disk_usage(root).free
    c.require(used<limits['reserve_bytes'] and free>limits['reserve_bytes'],'finite chunk used/free budget; stop without deleting evidence')
    return dict(used_bytes=used,free_bytes=free,reserve_bytes=limits['reserve_bytes'])


def retained_usage(root,limits):
    root=Path(root);failed=0;metadata=0;iq=0;events=0
    completed={p.parent.name:json.loads(p.read_text())['attempt'] for p in root.glob('batch-*/capture-complete.json')}
    for path in root.rglob('*'):
        if not path.is_file() or 'scratch' in path.relative_to(root).parts:continue
        c.require(not path.is_symlink(),'retention symlink')
        parts=path.relative_to(root).parts;size=path.stat().st_size
        if len(parts)>2 and parts[0].startswith('batch-') and parts[1].startswith('attempt-') and parts[1]!=f"attempt-{completed.get(parts[0],-1)}":
            failed+=size
        elif path.name.endswith('.sigmf-data'):iq+=size
        elif path.name=='tx-events.jsonl.gz':events+=size
        else:metadata+=size
    n=len(limits['allowed_batch_indices'])
    c.require(metadata<=n*METADATA_PER_BATCH and iq<=n*c.RX_SAMPLES*4 and events<=n*ARCHIVE_LIMIT,
        'successful retention ceiling; preserve evidence and pause')
    c.require(failed<=limits['failed_attempt_reserve_bytes'],'failed attempt retention ceiling')
    return dict(metadata_bytes=metadata,iq_bytes=iq,event_archive_bytes=events,failed_attempt_bytes=failed)
