"""四数据集原生窗口和显式源行合同；不含模型或硬件访问。"""
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

SPECS = {'rml2016a': (220000, 128, 11), 'rml2016b': (1200000, 128, 10),
         'rml2018a': (2555904, 1024, 24), 'hisarmod2019': (780000, 1024, 26)}
SCHEMA = 'amc-native-source-v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def label_hash(names):
    return hashlib.sha256((json.dumps(names, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False)+'\n').encode()).hexdigest()


def validate(contract):
    """先导源行有界且不重复；标签顺序独立于旧2018A算术映射。"""
    require(isinstance(contract, dict) and contract.get('schema') == SCHEMA, 'native source schema')
    dataset = contract.get('dataset_id')
    require(dataset in SPECS, 'native dataset identity')
    total, length, classes = SPECS[dataset]
    require(contract.get('total_source_rows') == total and contract.get('window_samples') == length,
            'native dataset shape')
    names = contract.get('class_names')
    require(isinstance(names, list) and len(names) == classes and
            all(isinstance(x, str) and x for x in names) and len(set(names)) == classes, 'native classes')
    raw_values = contract.get('raw_label_values')
    require(isinstance(raw_values, list) and len(raw_values) == classes and
            all(type(v) is int for v in raw_values) and raw_values == sorted(set(raw_values)),
            'native raw label mapping')
    rows = contract.get('source_rows')
    require(isinstance(rows, list) and 0 < len(rows) <= 8192 and
            all(type(x) is int and 0 <= x < total for x in rows) and len(set(rows)) == len(rows),
            'native source rows')
    labels, snrs = contract.get('class_ids'), contract.get('source_snr_db')
    require(isinstance(labels, list) and len(labels) == len(rows) and
            all(type(x) is int and 0 <= x < classes for x in labels), 'native source labels')
    # 估计器当前只承认这个名义Z范围；不为导入而放宽门限。
    require(isinstance(snrs, list) and len(snrs) == len(rows) and
            all(type(x) in (int, float) and np.isfinite(x) and -20 <= x <= 30 for x in snrs),
            'native source SNR')
    sha = contract.get('source_sha256')
    require(isinstance(sha, str) and len(sha) == 64 and all(x in '0123456789abcdef' for x in sha),
            'native source SHA')
    return contract


def select_rows(labels, snrs, validation_sets, classes, per_class=32):
    """最高源Z档、共同val集合、每类同数；不足上限时明确缩小，不混入train。"""
    labels, snrs = np.asarray(labels), np.asarray(snrs)
    require(labels.ndim == snrs.ndim == 1 and len(labels) == len(snrs) and np.isfinite(snrs).all(),
            'source metadata shape')
    require(type(classes) is int and classes >= 2 and labels.dtype.kind in 'iu' and
            ((labels >= 0) & (labels < classes)).all(), 'mapped source labels')
    require(type(per_class) is int and 1 <= per_class <= 32 and len(validation_sets) >= 1,
            'selection budget')
    common = np.arange(len(labels), dtype=np.int64)
    for values in validation_sets:
        values = np.asarray(values)
        require(values.ndim == 1 and values.dtype.kind in 'iu' and
                ((values >= 0) & (values < len(labels))).all() and len(np.unique(values)) == len(values),
                'validation source IDs')
        common = np.intersect1d(common, values)
    highest = float(np.max(snrs))
    candidates = [common[(labels[common] == cid) & (snrs[common] == highest)] for cid in range(classes)]
    count = min(per_class, min(map(len, candidates)))
    require(count > 0, 'empty class in common validation at highest Z')
    # 固定种子，仅打散源行顺序，不依赖预测/源波形能量挑样。
    rng = np.random.default_rng(20260926)
    selected = np.stack([rng.permutation(x)[:count] for x in candidates], axis=1).ravel()
    return selected, dict(highest_source_snr_db=highest, requested_per_class=per_class,
                          selected_per_class=count, available_per_class=list(map(len, candidates)),
                          common_validation_rows=len(common), selection_seed=20260926)


def read_selected(path, dataset_id, rows, class_names, source_sha256):
    """按原始行读取X/Y/Z；源文件整体SHA由调用方在读取前核对。"""
    require(dataset_id in SPECS, 'native dataset identity')
    total, length, classes = SPECS[dataset_id]
    rows = np.asarray(rows)
    require(rows.ndim == 1 and rows.dtype.kind in 'iu' and 0 < len(rows) <= 8192 and
            ((rows >= 0) & (rows < total)).all() and len(np.unique(rows)) == len(rows), 'selected rows')
    order = np.argsort(rows); undo = np.argsort(order)
    with h5py.File(Path(path), 'r') as f:
        expected = (total, length, 2) if dataset_id == 'rml2018a' else (total, 2, length)
        require(f['X'].shape == expected, 'source X shape')
        raw_values = list(range(classes))
        if dataset_id != 'rml2018a':
            all_labels = f['Y'][:].reshape(-1)
            require(all_labels.dtype.kind in 'iu', 'integer source labels')
            raw_values = np.unique(all_labels).tolist()
            require(len(raw_values) == classes, 'source label cardinality')
            names = [v.decode() if isinstance(v, bytes) else str(v) for v in f['classes'][:]]
            require(names == class_names, 'source class order')
        x = f['X'][rows[order]][undo]
        y = f['Y'][rows[order]][undo]; z = f['Z'][rows[order]][undo].reshape(-1)
    if dataset_id == 'rml2018a':
        require(y.shape == (len(rows), classes) and np.array_equal(y, np.eye(classes)[y.argmax(1)]), 'one-hot labels')
        y = y.argmax(1); x = x.transpose(0, 2, 1)
    else:
        y = y.reshape(-1)
        require(y.dtype.kind in 'iu', 'integer labels')
        # 与冻结H5IQDataset一致：全体原始整数标签排序后映射到连续模型ID。
        y = np.searchsorted(np.asarray(raw_values), y)
    require(np.isfinite(x).all(), 'finite source IQ')
    contract = dict(schema=SCHEMA, dataset_id=dataset_id, total_source_rows=total, window_samples=length,
                    class_names=class_names, raw_label_values=raw_values, source_rows=rows.tolist(), class_ids=y.tolist(),
                    source_snr_db=z.tolist(), source_sha256=source_sha256)
    validate(contract)
    return x[:, 0, :].astype(np.float64)+1j*x[:, 1, :].astype(np.float64), contract


def spectrum_screen(iq, *, rate_hz=2100000, bandwidth_hz=1500000, lo_offset_hz=250000,
                    margin_hz=50000, maximum_outside_fraction=.01):
    """只读FFT筛查；保留源噪声/DC，模拟带宽并非实测砖墙响应。"""
    iq = np.asarray(iq)
    require(iq.ndim == 2 and iq.shape[1] in (128, 1024) and 0 < len(iq) <= 8192 and
            np.iscomplexobj(iq) and np.isfinite(iq).all(), 'spectral IQ shape')
    require(0 < bandwidth_hz <= rate_hz and 0 <= margin_hz < bandwidth_hz/2 and
            0 <= maximum_outside_fraction < 1, 'spectral limits')
    frequency = np.fft.fftshift(np.fft.fftfreq(iq.shape[1], d=1/rate_hz))
    power = abs(np.fft.fftshift(np.fft.fft(iq, axis=1), axes=1))**2
    total = power.sum(axis=1)
    require((total > 0).all(), 'spectral zero power')
    power /= total[:, None]
    # TX数字等效移频为-offset；同时检查TX模拟通带及RX模拟通带。
    inside = ((abs(frequency) <= bandwidth_hz/2-margin_hz) &
              (abs(frequency-lo_offset_hz) <= bandwidth_hz/2-margin_hz))
    outside = power[:, ~inside].sum(axis=1)
    cumulative = power.cumsum(axis=1)
    lo = frequency[np.argmax(cumulative >= .005, axis=1)]
    hi = frequency[np.argmax(cumulative >= .995, axis=1)]
    mean_fraction = abs(iq.mean(axis=1))**2 / np.mean(abs(iq)**2, axis=1)
    return dict(method='native-rectangular-FFT-no-demean-v1', rate_hz=rate_hz,
                bandwidth_hz=bandwidth_hz, lo_offset_hz=lo_offset_hz, margin_hz=margin_hz,
                maximum_outside_fraction=maximum_outside_fraction,
                passed=bool(np.all(outside <= maximum_outside_fraction)),
                outside_fraction=outside.tolist(), frequency_resolution_hz=rate_hz/iq.shape[1],
                central_99_percent_lower_hz=lo.tolist(), central_99_percent_upper_hz=hi.tolist(),
                mean_projection_fraction=mean_fraction.tolist(),
                limitation='FFT有限窗泄漏及源噪声均计入；筛查通过不等于硬件通带标定或无失真')
