"""Per-SNR SigMF/HDF5 corpus writer. No radio, GPU or model side effects.

One writer owns the files; receive/GPU workers may share read-only RAM buffers
but only submit completed blocks here. Raw IQ is never modified or deleted.
The atomic index commits only fsynced raw bytes / closed and fsynced HDF5.
Uncommitted tails are retained and rejected, not silently truncated on reopen.
"""
import fcntl
import json
import os
from pathlib import Path
import shutil

import h5py
import numpy as np

import rml2018a_campaign as c
from rml2018a_campaign_gpu import snr_block_rows, BLOCKS_PER_SNR, ROWS_PER_BLOCK

TAGS = ('source', 'raw', 'guard')
RESERVE = 64*1024**2
QUALITY_LIMIT = 16384
N = ROWS_PER_BLOCK


def source_rows(config, block):
    """Map observation order, preserving intentional repeats in finite pilots.

    Explicit mappings do not turn a pilot into a complete 96-block SNR corpus.
    The pinned configuration carries the mapping, including failed observations.
    """
    snr_block_rows(config['source_snr_db'], 0)
    if 'source_rows' not in config:
        return snr_block_rows(config['source_snr_db'], block)
    rows = config['source_rows']
    c.require(isinstance(rows, list) and 0 < len(rows) <= N*BLOCKS_PER_SNR and
              len(rows) % N == 0 and all(type(row) is int and 0 <= row < 2555904 for row in rows),
              'explicit source mapping type/size/range')
    rows = np.asarray(rows, dtype='<i8')
    c.require(np.all(2*((rows % 106496)//4096)-20 == config['source_snr_db']),
              'explicit source mapping SNR')
    c.require(type(block) is int and 0 <= block < len(rows)//N, 'explicit source mapping block budget')
    return rows[block*N:(block+1)*N]


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)+'\n').encode()


def sync_directory(root):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def atomic_json(path, value):
    pending = path.with_suffix(path.suffix+'.pending')
    with pending.open('xb') as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
    os.replace(pending, path); sync_directory(path.parent)


def background(value):
    c.require(isinstance(value, dict) and value.get('status') in ('measured', 'not_measured'), 'background status')
    if value['status'] == 'not_measured':
        c.require(isinstance(value.get('reason'), str) and value['reason'], 'unmeasured background reason')
        c.require('power_adc_squared' not in value, 'unmeasured background has no power')
    else:
        c.require(value.get('tx_state') == 'off' and value.get('reference_plane') == 'raw_adc' and
                  value.get('unit') == 'adc_counts_squared', 'background measurement semantics')
        for key in ('power_adc_squared', 'frequency_hz', 'sample_rate_hz', 'bandwidth_hz', 'rx_gain_db'):
            c.require(type(value.get(key)) in (int, float) and np.isfinite(value[key]) and
                      (key == 'rx_gain_db' or value[key] >= 0), 'background numeric field')
        c.require(type(value.get('sample_count')) is int and value['sample_count'] > 0 and
                  all(isinstance(value.get(k), str) and value[k] for k in
                      ('capture_id', 'timestamp_utc', 'raw_sha256')), 'background provenance')
    c.require(len(encoded(value)) <= QUALITY_LIMIT, 'background metadata bound')


def block_hash(inputs, masks, starts, counts, quality):
    import hashlib
    h = hashlib.sha256()
    for tag in TAGS:
        h.update(inputs[tag].tobytes()); h.update(masks[tag].tobytes())
    h.update(starts.tobytes()); h.update(counts.tobytes()); h.update(encoded(quality))
    return h.hexdigest()


class SnrStore:
    """Explicit create/open; close releases ownership without deleting data."""
    def __init__(self, root, *, configuration=None, raw_parent=None):
        self.root = Path(root)
        self.raw_parent=raw_parent
        c.require(self.root.is_absolute() and self.root.resolve() == self.root and
                  self.root.is_dir(), 'existing canonical corpus root')
        self.lock = os.open(self.root/'writer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for p in self.root.iterdir(): c.require(not p.is_symlink(), 'corpus symlink')
            if configuration is not None:
                c.require(set(p.name for p in self.root.iterdir()) == {'writer.lock'}, 'new empty SNR corpus')
                self._create(configuration)
            self.config = json.loads((self.root/'configuration.json').read_text())
            if raw_parent is not None:
                c.require(raw_parent.raw_parent is None and raw_parent.lock is not None and
                          self.root!=raw_parent.root and self.config.get('raw_parent')==dict(
                              root=str(raw_parent.root),configuration_sha256=c.file_hash(raw_parent.root/'configuration.json')),
                          'shared raw parent identity')
                c.require(all(self.config[k]==raw_parent.config[k] for k in ('session_id','source_sha256',
                    'preprocess_id','profile_sha256','label_map_sha256','sample_rate_hz','center_hz','bandwidth_hz',
                    'rx_gain_db','tx_gain_db','max_raw_samples')),'shared raw session/RF identity')
            else:c.require('raw_parent' not in self.config,'shared raw parent required on reopen')
            self.index = json.loads((self.root/'index.json').read_text())
            c.require(self.index['configuration_sha256'] == c.file_hash(self.root/'configuration.json'), 'configuration pin')
            self.verify()
            if not self.index['complete'] and not list(self.root.glob('*.pending')):
                self._meta()  # Rebuild derived SigMF annotations after a committed-raw interruption.
        except BaseException:
            os.close(self.lock); self.lock = None; raise

    def _create(self, config):
        source_rows(config, 0)
        c.require(type(config['max_raw_samples']) is int and 0 < config['max_raw_samples'] < 2**61,
                  'finite raw sample budget')
        for key in ('session_id', 'source_sha256', 'preprocess_id', 'profile_sha256', 'label_map_sha256'):
            c.require(isinstance(config.get(key), str) and config[key], 'corpus provenance')
        for key in ('sample_rate_hz', 'center_hz', 'bandwidth_hz', 'rx_gain_db', 'tx_gain_db'):
            c.require(type(config.get(key)) in (int, float) and np.isfinite(config[key]), 'RF metadata')
        c.require(config['sample_rate_hz'] > 0 and config['bandwidth_hz'] > 0, 'positive RF rate/bandwidth')
        self._space(RESERVE)
        atomic_json(self.root/'configuration.json', config)
        if self.raw_parent is None:
            with (self.root/'raw.sigmf-data').open('xb') as f: f.flush(); os.fsync(f.fileno())
        with h5py.File(self.root/'processed.h5', 'x') as f:
            f.attrs['schema'] = 'rml2018a-snr-processed-v1'
            f.attrs['configuration_sha256'] = c.file_hash(self.root/'configuration.json')
            f.create_group('blocks')
        self._sync_h5()
        atomic_json(self.root/'index.json', dict(schema='rml2018a-snr-corpus-v1',
            configuration_sha256=c.file_hash(self.root/'configuration.json'), raw=[], processed=[], complete=False))
        self.config = config; self.index = json.loads((self.root/'index.json').read_text())
        self._meta()

    def _space(self, size):
        c.require(shutil.disk_usage(self.root).free > size+RESERVE, 'corpus free-space reserve')

    def _sync_h5(self):
        with (self.root/'processed.h5').open('rb') as f: os.fsync(f.fileno())

    def _commit(self, index):
        atomic_json(self.root/'index.json', index)
        self.index = json.loads(encoded(index))

    def raw_receipts(self):
        return (self.raw_parent.index if self.raw_parent is not None else self.index)['raw']

    def raw_path(self):
        return (self.raw_parent.root if self.raw_parent is not None else self.root)/'raw.sigmf-data'

    def _meta(self):
        annotations = [dict(**{'core:sample_start':r['sample_start'], 'core:sample_count':r['sample_count']},
            **{'sdrharness:sequence':r['sequence'], 'sdrharness:quality':r['metadata']}) for r in self.raw_receipts()]
        atomic_json(self.root/'raw.sigmf-meta', {'global':{'core:datatype':'ci16_le', 'core:version':'1.2.5',
            'core:sample_rate':self.config['sample_rate_hz'], 'core:recorder':'sdrharness',
            'core:description':'Unmodified P201 RX IQ, including guards and failed payloads',
            'sdrharness:session_id':self.config['session_id'], 'sdrharness:configuration':'configuration.json',
            **({'core:dataset':str(self.raw_path()),'sdrharness:raw_parent':self.config['raw_parent']} if self.raw_parent is not None else {})},
            'captures':[{'core:sample_start':0, 'core:frequency':self.config['center_hz']}],
            'annotations':annotations})

    def _writable(self):
        c.require(self.lock is not None and not self.index['complete'], 'closed/completed corpus')
        c.require(not (self.root/'STOP').exists(), 'corpus STOP')
        c.require(not list(self.root.glob('*.pending')), 'interrupted metadata retained; inspect before append')

    def append_raw(self, iq, metadata):
        """One immutable host buffer; offsets count complex samples, not bytes."""
        self._writable()
        c.require(self.raw_parent is None,'only raw owner may append shared IQ')
        c.require(isinstance(iq, np.ndarray) and iq.dtype == np.dtype('<i2') and
                  iq.ndim == 2 and iq.shape[1] == 2 and 0 < len(iq) <= 4*1024**2, 'raw ci16 IQ shape/bound')
        c.require(isinstance(metadata, dict) and isinstance(metadata.get('capture_id'), str) and
                  metadata['capture_id'] and isinstance(metadata.get('timestamp_utc'), str) and metadata['timestamp_utc'], 'raw capture/time')
        c.require(type(metadata.get('dropped_samples')) is int and metadata['dropped_samples'] >= 0 and
                  type(metadata.get('overflow')) is bool and type(metadata.get('clipped_samples')) is int and
                  0 <= metadata['clipped_samples'] <= len(iq), 'raw quality counters')
        background(metadata['background'])
        c.require(len(encoded(metadata)) <= QUALITY_LIMIT and len(self.index['raw']) < 4096, 'raw metadata/segment budget')
        start = sum(r['sample_count'] for r in self.index['raw'])
        c.require(start+len(iq) <= self.config['max_raw_samples'], 'raw finite budget')
        data = iq.tobytes(order='C'); self._space(len(data)+2*1024**2)
        metadata = json.loads(encoded(metadata))
        counts = np.frombuffer(data, dtype='<i2').reshape(-1, 2).astype(np.int64)
        metadata['received_total_power_adc_squared'] = float(np.mean(np.sum(counts*counts, axis=1)))
        metadata['received_power_unit'] = 'adc_counts_squared_not_calibrated_watts'
        path = self.root/'raw.sigmf-data'
        c.require(path.stat().st_size == start*4, 'uncommitted raw tail retained')
        with path.open('ab') as f: f.write(data); f.flush(); os.fsync(f.fileno())
        receipt = dict(sequence=len(self.index['raw']), sample_start=start, sample_count=len(iq),
                       sha256=c.digest(data), metadata=metadata)
        index = dict(self.index, raw=self.index['raw']+[receipt]); self._commit(index); self._meta()
        return receipt

    def append_processed(self, inputs, masks, sample_starts, sample_counts, quality):
        """Commit exactly1024 original source rows; failed rows remain explicit.

        GPU work need not wait for raw fsync, but this commit requires its raw
        offsets to be durable. Invalid inputs contain NaNs plus a false mask.
        """
        self._writable(); block = len(self.index['processed'])
        rows = source_rows(self.config, block)
        c.require(set(inputs) == set(masks) == set(TAGS), 'source/raw/guard datasets')
        for tag in TAGS:
            c.require(inputs[tag].shape == (N,2,1024) and inputs[tag].dtype == np.dtype('<f4') and
                      masks[tag].shape == (N,) and masks[tag].dtype == np.bool_, 'processed shape/dtype')
            c.require(np.isfinite(inputs[tag][masks[tag]]).all() and
                      np.isnan(inputs[tag][~masks[tag]]).all(), 'processed finite/missing masks')
        starts = np.asarray(sample_starts); counts = np.asarray(sample_counts)
        c.require(starts.shape == counts.shape == (N,) and starts.dtype == counts.dtype == np.dtype('<i8'), 'raw offset arrays')
        mapped = masks['raw'] | masks['guard']
        raw_count = sum(v['sample_count'] for v in self.raw_receipts())
        c.require(((starts[mapped] >= 0) & (counts[mapped] > 0) & (starts[mapped] <= raw_count) &
                   (counts[mapped] <= raw_count-starts[mapped])).all() and
                  (starts[~mapped] == -1).all() and (counts[~mapped] == 0).all(), 'processed raw lineage bounds')
        c.require(len(quality) == N and all(len(encoded(q)) <= QUALITY_LIMIT for q in quality), 'per-row quality bound')
        for q in quality:
            c.require(isinstance(q, dict) and 'raw' in q and 'sync' in q, 'raw SINR/sync quality required')
            c.validate_receive_quality(q['raw'], self.config['source_snr_db'])
        self._space(3*N*2*1024*4+N*QUALITY_LIMIT+2*1024**2)
        name = f'{block:03d}'
        sha = block_hash(inputs, masks, starts, counts, quality)
        with h5py.File(self.root/'processed.h5', 'r+') as f:
            c.require(set(f['blocks']) == {f'{i:03d}' for i in range(block)}, 'uncommitted HDF5 tail retained')
            b = f['blocks'].create_group(name)
            b.create_dataset('source_row', data=rows)
            b.create_dataset('class_id', data=(rows//106496).astype('<i2'))
            b.create_dataset('source_snr_db', data=np.full(N, self.config['source_snr_db'], dtype='<i2'))
            b.create_dataset('raw_sample_start', data=starts); b.create_dataset('raw_sample_count', data=counts)
            for tag in TAGS:
                b.create_dataset('inputs/'+tag, data=inputs[tag], chunks=(128,2,1024), compression=None)
                b.create_dataset('valid/'+tag, data=masks[tag])
            b.create_dataset('quality_json', data=[encoded(q).decode() for q in quality], dtype=h5py.string_dtype('utf-8'))
            b.attrs['payload_sha256'] = sha
        self._sync_h5()
        receipt = dict(block=block, source_rows=N, payload_sha256=sha)
        self._commit(dict(self.index, processed=self.index['processed']+[receipt]))
        return receipt

    def verify(self):
        source_rows(self.config, 0)
        c.require(self.index['schema'] == 'rml2018a-snr-corpus-v1' and
                  len(self.index['processed']) <= BLOCKS_PER_SNR and len(self.index['raw']) <= 4096 and
                  type(self.index['complete']) is bool, 'corpus schema/bounds')
        c.require(self.raw_parent is None or not self.index['raw'],'shared child has no independent raw receipts')
        raw = self.raw_path(); offset = 0
        with raw.open('rb') as f:
            for seq, r in enumerate(self.raw_receipts()):
                c.require(r['sequence'] == seq and r['sample_start'] == offset and
                          type(r['sample_count']) is int and 0 < r['sample_count'] <= 4*1024**2 and
                          offset+r['sample_count'] <= self.config['max_raw_samples'], 'raw sequence/offset/budget')
                c.require(c.digest(f.read(r['sample_count']*4)) == r['sha256'], 'raw payload SHA')
                offset += r['sample_count']
        c.require(raw.stat().st_size == offset*4, 'uncommitted raw tail retained')
        with h5py.File(self.root/'processed.h5', 'r') as f:
            c.require(f.attrs['configuration_sha256'] == self.index['configuration_sha256'] and
                      set(f['blocks']) == {f'{i:03d}' for i in range(len(self.index['processed']))}, 'HDF5 identity/uncommitted tail')
            for i, receipt in enumerate(self.index['processed']):
                b = f['blocks'][f'{i:03d}']
                rows = source_rows(self.config, i)
                c.require(receipt['block'] == i and np.array_equal(b['source_row'][:], rows) and
                          np.array_equal(b['class_id'][:], rows//106496) and
                          (b['source_snr_db'][:] == self.config['source_snr_db']).all(), 'stored source mapping')
                sha = block_hash({t:b['inputs/'+t][:] for t in TAGS}, {t:b['valid/'+t][:] for t in TAGS},
                    b['raw_sample_start'][:], b['raw_sample_count'][:], [json.loads(s) for s in b['quality_json'].asstr()[:]])
                c.require(sha == receipt['payload_sha256'] == b.attrs['payload_sha256'], 'processed payload SHA')
        if self.index['complete']:
            c.require('source_rows' not in self.config, 'explicit pilot cannot seal as complete SNR')
            c.require(len(self.index['processed']) == BLOCKS_PER_SNR and
                      c.file_hash(raw) == self.index['raw_sha256'] and
                      c.file_hash(self.root/'processed.h5') == self.index['processed_sha256'] and
                      c.file_hash(self.root/'raw.sigmf-meta') == self.index['metadata_sha256'], 'completed corpus seal')

    def iter_processed(self, tag='raw', batch_rows=128):
        """Read only after this entire SNR is sealed; caller gates all26 groups.

        Includes invalid rows/masks/quality instead of shrinking the denominator.
        No model or GPU is loaded. Consumers must honor the validity mask.
        """
        c.require(self.lock is not None and self.index['complete'] and tag in TAGS and
                  type(batch_rows) is int and 0 < batch_rows <= N, 'sealed SNR reader')
        with h5py.File(self.root/'processed.h5', 'r') as f:
            for i in range(BLOCKS_PER_SNR):
                b = f['blocks'][f'{i:03d}']
                for start in range(0, N, batch_rows):
                    selection = slice(start, min(N, start+batch_rows))
                    yield dict(source_row=b['source_row'][selection], class_id=b['class_id'][selection],
                        source_snr_db=b['source_snr_db'][selection], inputs=b['inputs/'+tag][selection],
                        valid=b['valid/'+tag][selection], raw_sample_start=b['raw_sample_start'][selection],
                        raw_sample_count=b['raw_sample_count'][selection],
                        quality=[json.loads(v) for v in b['quality_json'].asstr()[selection]])

    def finish(self):
        self._writable(); self.verify()
        c.require('source_rows' not in self.config, 'explicit pilot cannot seal as complete SNR')
        c.require(self.raw_parent is None or self.raw_parent.index['complete'],'seal shared raw owner first')
        c.require(len(self.index['processed']) == BLOCKS_PER_SNR, 'complete SNR requires96 blocks including failures')
        self._meta()
        self._commit(dict(self.index, complete=True, raw_sha256=c.file_hash(self.raw_path()),
                          processed_sha256=c.file_hash(self.root/'processed.h5'),
                          metadata_sha256=c.file_hash(self.root/'raw.sigmf-meta')))

    def close(self):
        if self.lock is not None: os.close(self.lock); self.lock = None

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
