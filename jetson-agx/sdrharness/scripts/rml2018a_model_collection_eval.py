#!/usr/bin/env python3
"""Finite single-window engineering evaluation of imported models and HDF5s.

Preserves source IDs and skip masks; infers only eligible RX rows. No RF, training,
normalization, model fallback, production binding, or four-window aggregation.
"""
import argparse
import csv
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor
import fcntl

import h5py
import numpy as np

ROWS = 2555904
BLOCK = 16384
REPO = Path(__file__).resolve().parents[3]
ASSET = REPO / "local-assets/amc-eval"
COLLECTION = ASSET / "checkpoints/rml2018a/server-models-20260914"
CLEAN = ASSET / "datasets/rml2018a/rx-clean-20260914"
ORIGINAL_SHA = "e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38"
FIELDS = ("d_model", "dropout", "use_real_mamba", "mamba_d_state",
          "mamba_d_conv", "mamba_expand", "mamba_headdim")


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while data := f.read(8 * 1024**2):
            h.update(data)
    return h.hexdigest()


def atomic(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    tmp.replace(path)


def identity(path, expected=None):
    path = Path(path).resolve(strict=True)
    s = path.stat()
    sha = digest(path)
    require(expected is None or sha == expected, f"hash mismatch: {path}")
    require(path.stat().st_mtime_ns == s.st_mtime_ns, "input changed during hash")
    return dict(path=str(path), bytes=s.st_size, mtime_ns=s.st_mtime_ns, sha256=sha)


def unchanged(record):
    s = Path(record["path"]).stat()
    require((s.st_size, s.st_mtime_ns) == (record["bytes"], record["mtime_ns"]),
            f"input changed: {record['path']}")


def metadata(path, plane, original_y=None, original_z=None, classes=None):
    with h5py.File(path, "r") as f:
        if plane == "source":
            require(f["X"].shape == (ROWS, 1024, 2) and f["X"].dtype == np.float32,
                    "original IQ contract")
            onehot = f["Y"][:]
            require(onehot.shape == (ROWS, 24) and np.isin(onehot, (0, 1)).all()
                    and (onehot.sum(1) == 1).all(), "original labels")
            y = onehot.argmax(1).astype(np.int16)
            z = f["Z"][:].reshape(-1)
            ids = np.arange(ROWS, dtype=np.int64)
            extra = {}
        else:
            require(f.attrs["status"] == "complete" and int(f.attrs["rows_written"]) == ROWS,
                    "incomplete cleaned dataset")
            require(f["iq"].shape == (ROWS, 2, 1024) and f["iq"].dtype == np.float32,
                    "clean IQ contract")
            require(list(f["class_names"].asstr()[:]) == classes, "class order")
            y, z, ids = f["class_id"][:], f["source_snr_db"][:], f["source_row"][:]
            require(np.array_equal(np.sort(ids), np.arange(ROWS)), "source IDs not full permutation")
            require(np.array_equal(y, original_y[ids]) and np.array_equal(z, original_z[ids]),
                    "source row / label / SNR mismatch")
            extra = {k: f[k][:] for k in ("usable", "strict_quality_pass", "quality_flags",
                                         "guard_applied", "raw_sinr_db", "guard_sinr_db")}
            flags = extra["quality_flags"]
            for name, attr in (("usable", "usable_required_mask"),
                               ("strict_quality_pass", "strict_quality_required_mask")):
                mask = int(f.attrs[attr])
                require(np.array_equal(extra[name], flags & mask == mask), "quality flag contract")
        require(z.shape == (ROWS,) and np.isin(z, np.arange(-20, 31, 2)).all(), "SNR contract")
        return dict(source_row=ids, class_id=y, source_snr_db=z.astype(np.int16), **extra)


def select_metadata(root, datasets):
    """User-selected strict RX masks; common source IDs for fair paired reports."""
    values = {}
    common = np.ones(ROWS, bool)
    for ds in datasets:
        with np.load(root / f"{ds['plane']}-metadata.npz", allow_pickle=False) as f:
            m = {k: f[k] for k in f.files}
        selected = np.ones(ROWS, bool) if ds["plane"] == "source" else m["usable"] & m["strict_quality_pass"]
        m["selected_for_inference"] = selected
        if ds["plane"] != "source":
            canonical = np.zeros(ROWS, bool)
            canonical[m["source_row"]] = selected
            common &= canonical
        values[ds["plane"]] = m
    for ds in datasets:
        m = values[ds["plane"]]
        m["common_source_subset"] = common[m["source_row"]]
        require((~m["common_source_subset"] | m["selected_for_inference"]).all(), "common subset not selected")
        np.savez(root / f"{ds['plane']}-metadata.npz", **m)
        ds.update(metadata_sha256=digest(root / f"{ds['plane']}-metadata.npz"),
                  selected_rows=int(m["selected_for_inference"].sum()),
                  skipped_rows=int((~m["selected_for_inference"]).sum()), common_rows=int(common.sum()))
        ds["eligibility_by_snr"] = [dict(source_snr_db=z,
            file_rows=int((m["source_snr_db"]==z).sum()),
            selected_rows=int(((m["source_snr_db"]==z)&m["selected_for_inference"]).sum()),
            skipped_rows=int(((m["source_snr_db"]==z)&~m["selected_for_inference"]).sum()))
            for z in range(-20,31,2)]
        if ds["plane"] != "source":
            with h5py.File(ds["path"],"r") as f:
                required = int(f.attrs["strict_quality_required_mask"]) | int(f.attrs["usable_required_mask"])
                definitions = json.loads(f.attrs["quality_flag_definitions_json"])
            ds["skip_reasons_overlapping"] = {
                definitions[str(bit)]: int(((m["quality_flags"] & bit)==0).sum())
                for bit in (1,2,4,8,16,32) if required & bit}


def prepare(root):
    require(not root.exists(), "use a new output root")
    require(json.loads((CLEAN / "COPY_COMPLETE.json").read_text())["complete"], "copy incomplete")
    require(shutil.disk_usage(root.parent).free > 15 * 1024**3, "15 GiB free required")
    root.mkdir(mode=0o700)
    manifest = json.loads((COLLECTION / "manifest.json").read_text())
    classes = json.loads((COLLECTION / "class-order.json").read_text())["classes"]
    # Verify all imported code/config/checkpoint bytes before any module import.
    for f in manifest["transferred_files"]:
        require(digest(COLLECTION / f["relative"]) == f["sha256"], "imported file changed")
    original = ASSET / "datasets/rml2018a/RML2018a.hdf5"
    source = metadata(original, "source")
    datasets = []
    for plane in ("source", "raw", "guard"):
        if plane == "source":
            path, expected, values = original, ORIGINAL_SHA, source
        else:
            path = CLEAN / f"RadioML2018A_RX_{plane}_1024_per_window_RMS_v1.h5"
            expected = json.loads(path.with_name(path.name + ".manifest.json").read_text())["sha256"]
            values = metadata(path, plane, source["class_id"], source["source_snr_db"], classes)
        record = identity(path, expected)
        np.savez(root / f"{plane}-metadata.npz", **values)
        datasets.append(dict(plane=plane, **record,
                             metadata_sha256=digest(root / f"{plane}-metadata.npz")))
        atomic(root / "progress.json", dict(stage="prepare", plane=plane))
    select_metadata(root,datasets)
    plan = dict(schema="rml2018a-clean12-strict-single-window-v2", created_ns=time.time_ns(),
                script=identity(__file__), plot_script=identity(Path(__file__).with_name("rml2018a_collection_plots.py")), collection_manifest=identity(COLLECTION / "manifest.json"),
                datasets=datasets, models=manifest["models"], classes=classes,
                rows_per_dataset=ROWS, model_dataset_pairs=36,
                total_predictions=sum(d["selected_rows"] for d in datasets)*len(manifest["models"]),
                batch_size=1024, block_rows=BLOCK, deadline_seconds=172800,
                normalization="none added; RX files already per-window complex RMS; original unchanged",
                sample_scope="all rows, includes historical train/validation/test; engineering only",
                quality_policy="RX usable AND strict_quality_pass only; original all; common source-ID subset additionally reported",
                precision_policy="FP32 weights; pilot validates FP16 against FP32, otherwise FP32",
                recognizer_available=False, training=False, rf=False)
    atomic(root / "plan.json", plan)
    print(json.dumps(dict(prepared=True, predictions=plan["total_predictions"])), flush=True)


def setup(root):
    cache = cache_root(root)
    cache.mkdir(parents=True, exist_ok=True)
    for name in ("TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "TORCHINDUCTOR_CACHE_DIR", "TMPDIR"):
        p = cache / name
        p.mkdir(exist_ok=True)
        os.environ[name] = str(p)
    for name in ("models", "utils"):
        require(name not in sys.modules, "unexpected imported namespace")
        module = types.ModuleType(name)
        module.__path__ = [str(COLLECTION / "source" / name)]
        sys.modules[name] = module
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    require(torch.cuda.is_available(), "CUDA unavailable")
    return torch


def cache_root(root):
    token = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return Path("/var/tmp/sdrharness-dev") / f"rml2018a-collection-cache-{token}"


def load_model(spec, torch):
    cfg = json.loads((COLLECTION / spec["config_relative"]).read_text())
    mc = cfg["resolved_config"]["model"]
    variant = spec["variant"]
    module = "models.d8.model" if variant == "amc_mamba_d8" else "models.baselines." + variant.removeprefix("baseline_")
    cls = getattr(importlib.import_module(module), cfg["selected_model_class"])
    model = cls(model_variant=variant, num_classes=24, **{k: mc[k] for k in FIELDS})
    require(digest(COLLECTION / spec["checkpoint"]["relative"]) == spec["checkpoint"]["sha256"], "checkpoint changed")
    state = torch.load(COLLECTION / spec["checkpoint"]["relative"], map_location="cpu", weights_only=True)
    model.load_state_dict(state["model_state"], strict=True)
    require(sum(p.numel() for p in model.parameters()) == cfg["model_parameters"], "parameter count")
    require(model.encoder.backend == spec["backend"], "model backend mismatch; fallback forbidden")
    return model.eval().cuda()


def read_iq(ds, start, stop, selected=None):
    unchanged(ds)
    with h5py.File(ds["path"], "r") as f:
        x = f["X" if ds["plane"] == "source" else "iq"][start:stop]
    if ds["plane"] == "source":
        x = x.transpose(0, 2, 1)
    if selected is not None:
        x = x[selected]
    x = np.ascontiguousarray(x, dtype=np.float32)
    require(np.isfinite(x).all(), "nonfinite input; no row dropping")
    if ds["plane"] != "source" and len(x):
        rms = np.sqrt(np.mean(np.sum(x.astype(np.float64)**2, axis=1), axis=1))
        require(np.max(np.abs(rms - 1)) <= 2e-6, "clean per-window RMS mismatch")
    return x


def predict(model, x, torch, precision):
    host = torch.from_numpy(x).pin_memory()
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=precision == "fp16"):
        output = model(host.to("cuda", non_blocking=True))
    require(tuple(output.shape) == (len(x), 24), "output shape")
    values = output.float().cpu().numpy()
    require(np.isfinite(values).all(), "nonfinite logits")
    return values


def probabilities(x):
    e = np.exp(x.astype(np.float64) - x.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def probe(root, plan, torch):
    results = []
    # Fixed positions independent of labels/predictions; include all three domains.
    samples = []
    for ds in plan["datasets"]:
        with np.load(root/f"{ds['plane']}-metadata.npz",allow_pickle=False) as m:
            eligible = np.flatnonzero(m["selected_for_inference"])
        require(len(eligible)>=64, "insufficient eligible pilot rows")
        rows = eligible[np.linspace(0,len(eligible)-1,64,dtype=int)]
        with h5py.File(ds["path"], "r") as f:
            x = f["X" if ds["plane"] == "source" else "iq"][rows]
        samples.append(x.transpose(0, 2, 1) if ds["plane"] == "source" else x)
    pilot = np.ascontiguousarray(np.concatenate(samples), dtype=np.float32)
    for spec in plan["models"]:
        model = load_model(spec, torch)
        fp32 = predict(model, pilot, torch, "fp32")
        fp16_failure = None
        try:
            fp16 = predict(model, pilot, torch, "fp16")
        except ValueError as exc:
            if str(exc) != "nonfinite logits":
                raise
            fp16 = None
            fp16_failure = "nonfinite FP16 pilot logits; use verified FP32"
        error = float(np.max(np.abs(probabilities(fp16) - probabilities(fp32)))) if fp16 is not None else None
        top1_changes = int((fp16.argmax(1) != fp32.argmax(1)).sum()) if fp16 is not None else None
        precision = "fp16" if error is not None and error <= 0.005 and top1_changes == 0 else "fp32"
        # Exercise full intended batch; ensure batching does not change class decisions.
        full = np.ascontiguousarray(pilot[np.arange(1024) % len(pilot)])
        t = time.monotonic()
        output = predict(model, full, torch, precision)
        seconds = time.monotonic() - t
        reference = fp16 if precision == "fp16" else fp32
        batch_error = float(np.max(np.abs(probabilities(output[:len(pilot)]) - probabilities(reference))))
        fp16_batch_failure = None
        if precision == "fp16" and (batch_error > 0.005 or
                                     (output[:len(pilot)].argmax(1) != reference.argmax(1)).any()):
            fp16_batch_failure = dict(probability_error=batch_error,
                                      top1_changes=int((output[:len(pilot)].argmax(1)!=reference.argmax(1)).sum()))
            precision="fp32"
            t=time.monotonic();output=predict(model,full,torch,precision);seconds=time.monotonic()-t
            reference=fp32
            batch_error=float(np.max(np.abs(probabilities(output[:len(pilot)])-probabilities(reference))))
        require(batch_error <= 0.005, "batch numerical mismatch")
        result = dict(variant=spec["variant"], seed=spec["seed"], strict_load=True,
                      backend=spec["backend"], precision=precision, fp16_probability_error=error,
                      fp16_failure=fp16_failure,
                      fp16_batch_failure=fp16_batch_failure,
                      fp16_top1_changes=top1_changes,
                      batch_probability_error=batch_error,
                      batch_top1_changes=int((output[:len(pilot)].argmax(1) != reference.argmax(1)).sum()),
                      full_batch_seconds=seconds, pilot_rows=len(pilot), passed=True)
        results.append(result)
        atomic(root / "probe-progress.json", results)
        print(json.dumps(result), flush=True)
        del model
        torch.cuda.empty_cache()
    atomic(root / "probe.json", dict(passed=True, models=results, torch_version=torch.__version__,
                                     cuda=torch.version.cuda, device=torch.cuda.get_device_name(),
                                     script_sha256=plan["script"]["sha256"]))
    plan["probe_sha256"]=digest(root/"probe.json")
    atomic(root/"plan.json",plan)


def confusion(y, z, pred, mask=None):
    if mask is not None:
        y, z, pred = y[mask], z[mask], pred[mask]
    idx = ((z.astype(np.int64) + 20) // 2 * 24 + y) * 24 + pred
    return np.bincount(idx, minlength=26*24*24).reshape(26, 24, 24)


def report(root, name, ds, counts, common, done):
    total = int(counts.sum())
    correct = int(np.trace(counts.sum(0)))
    per_snr = []
    for i, snr in enumerate(range(-20, 31, 2)):
        n = int(counts[i].sum()); c = int(np.trace(counts[i]))
        per_snr.append(dict(source_snr_db=snr, rows=n, correct=c, accuracy=c/n if n else None))
    s = int(common.sum())
    out = dict(model=name, dataset=ds["plane"], complete=done, rows=total,
               eligible_rows=ds["selected_rows"], skipped_rows=ds["skipped_rows"],
               correct=correct, accuracy=correct/total if total else None,
               common_rows=s, common_accuracy=int(np.trace(common.sum(0)))/s if s else None,
               per_snr=per_snr, confusion_by_snr=counts.tolist(), common_confusion_by_snr=common.tolist())
    atomic(root / name / f"{ds['plane']}-summary.json", out)


def run(root, plan, torch):
    require(digest(root/"probe.json")==plan["probe_sha256"], "probe changed")
    probe_result = json.loads((root / "probe.json").read_text())
    require(probe_result["passed"] and len(probe_result["models"]) == 12, "all-model probe required")
    start = time.monotonic()
    completed = 0
    def check():
        require(not (root / "STOP").exists(), "operator STOP")
        require(time.monotonic()-start < plan["deadline_seconds"], "run deadline exceeded")
        require(shutil.disk_usage(root).free > 3 * 1024**3, "free space floor")
    for spec, tested in zip(plan["models"], probe_result["models"]):
        require((spec["variant"], spec["seed"]) == (tested["variant"], tested["seed"]), "probe identity")
        check()
        name = f"{spec['variant']}-seed{spec['seed']}"
        (root / name).mkdir(exist_ok=True)
        model = load_model(spec, torch)
        for ds in plan["datasets"]:
            counts = np.zeros((26,24,24), dtype=np.int64)
            common = np.zeros_like(counts)
            require(digest(root / f"{ds['plane']}-metadata.npz") == ds["metadata_sha256"], "metadata changed")
            with np.load(root / f"{ds['plane']}-metadata.npz", allow_pickle=False) as meta:
                y, z = meta["class_id"], meta["source_snr_db"]
                mask = meta["selected_for_inference"]
                common_mask = meta["common_source_subset"]
            folder = root / name / ds["plane"]
            folder.mkdir(exist_ok=True)
            with ThreadPoolExecutor(max_workers=1) as reader:
                future = None
                for lo in range(0, ROWS, BLOCK):
                    check(); hi = min(lo+BLOCK, ROWS)
                    row_ids = np.flatnonzero(mask[lo:hi]) + lo
                    path = folder / f"{lo:07d}.npz"
                    receipt = path.with_suffix(".json")
                    if receipt.exists():
                        rec = json.loads(receipt.read_text())
                        require((rec["start"], rec["stop"], rec["checkpoint_sha256"],
                                 rec["input_sha256"], rec["precision"]) ==
                                (lo, hi, spec["checkpoint"]["sha256"], ds["sha256"], tested["precision"]),
                                "existing result identity mismatch")
                        require(rec["sha256"] == digest(path), "existing result hash mismatch")
                        with np.load(path, allow_pickle=False) as f:
                            logits, pred = f["logits"], f["predicted_class"]
                            require(int(f["start"]) == lo and int(f["stop"]) == hi, "result row bounds")
                            require(np.array_equal(f["dataset_row"],row_ids), "saved row selection changed")
                            require(logits.shape == (len(row_ids),24) and np.isfinite(logits).all()
                                    and np.array_equal(pred, logits.argmax(1)), "saved logits invalid")
                        completed += len(row_ids)
                    else:
                        committed_before_block = completed
                        x = future.result() if future is not None else read_iq(ds,lo,hi,mask[lo:hi])
                        future = None
                        if hi < ROWS:
                            next_path = folder / f"{hi:07d}.json"
                            if not next_path.exists():
                                future = reader.submit(read_iq, ds, hi, min(hi+BLOCK,ROWS),mask[hi:min(hi+BLOCK,ROWS)])
                        logits = np.empty((len(row_ids),24), np.float32)
                        for offset in range(0,len(x),plan["batch_size"]):
                            check(); stop = min(offset+plan["batch_size"],len(x))
                            logits[offset:stop] = predict(model,x[offset:stop],torch,tested["precision"])
                            completed += stop-offset
                            elapsed = time.monotonic()-start
                            atomic(root / "progress.json", dict(stage="inference",model=name,dataset=ds["plane"],
                                   dataset_rows=int(counts.sum())+stop,completed_predictions=completed,total_predictions=plan["total_predictions"],
                                   committed_predictions=committed_before_block,
                                   elapsed_seconds=elapsed, updated_ns=time.time_ns()))
                        pred = logits.argmax(1).astype(np.int16)
                        tmp = path.with_suffix(".tmp")
                        with tmp.open("wb") as f:
                            np.savez(f, start=np.int64(lo), stop=np.int64(hi), dataset_row=row_ids,
                                     logits=logits, predicted_class=pred)
                            f.flush(); os.fsync(f.fileno())
                        tmp.replace(path)
                        atomic(receipt,dict(start=lo,stop=hi,bytes=path.stat().st_size,sha256=digest(path),
                                            checkpoint_sha256=spec["checkpoint"]["sha256"],
                                            input_sha256=ds["sha256"],precision=tested["precision"]))
                    counts += confusion(y[row_ids],z[row_ids],pred)
                    common += confusion(y[row_ids],z[row_ids],pred,common_mask[row_ids])
                    report(root,name,ds,counts,common,hi==ROWS)
                    atomic(root/"progress.json",dict(stage="inference",model=name,dataset=ds["plane"],
                           dataset_rows=int(counts.sum()),completed_predictions=completed,committed_predictions=completed,
                           total_predictions=plan["total_predictions"],elapsed_seconds=time.monotonic()-start,
                           updated_ns=time.time_ns()))
            require(int(counts.sum()) == ds["selected_rows"], "eligible denominator missing")
        del model
        torch.cuda.empty_cache()
    require(completed == plan["total_predictions"], "incomplete evaluation")
    summaries = [json.loads(p.read_text()) for p in sorted(root.glob("*-seed*/*-summary.json"))]
    require(len(summaries)==36 and all(s["complete"] for s in summaries), "36 reports required")
    with (root / "summary.csv").open("w") as f:
        writer = csv.DictWriter(f,fieldnames=("model","dataset","rows","skipped_rows","correct","accuracy","common_rows","common_accuracy"))
        writer.writeheader()
        writer.writerows({k:s[k] for k in writer.fieldnames} for s in summaries)
    verify_outputs(root, plan)
    render(root, plan)
    atomic(root / "COMPLETE.json",dict(complete=True,predictions=completed,model_dataset_pairs=36,
                                      elapsed_seconds=time.monotonic()-start,summary_sha256=digest(root/"summary.csv")))
    atomic(root / "progress.json",dict(stage="complete",predictions=completed))


def verify_outputs(root, plan):
    """Read back persisted results and independently reconcile all denominators."""
    files = []
    atomic(root/"progress.json",dict(stage="verification",total_predictions=plan["total_predictions"],
                                    completed_predictions=plan["total_predictions"]))
    for spec in plan["models"]:
        name = f"{spec['variant']}-seed{spec['seed']}"
        for ds in plan["datasets"]:
            with np.load(root / f"{ds['plane']}-metadata.npz", allow_pickle=False) as m:
                y, z = m["class_id"], m["source_snr_db"]
                mask = m["selected_for_inference"]
                common_mask = m["common_source_subset"]
            counts = np.zeros((26,24,24),np.int64)
            common = np.zeros_like(counts)
            for lo in range(0,ROWS,BLOCK):
                require(not (root/"STOP").exists(), "operator STOP during verification")
                hi = min(lo+BLOCK,ROWS)
                row_ids = np.flatnonzero(mask[lo:hi])+lo
                p = root/name/ds["plane"]/f"{lo:07d}.npz"
                rec = json.loads(p.with_suffix(".json").read_text())
                require(rec["input_sha256"]==ds["sha256"] and
                        rec["checkpoint_sha256"]==spec["checkpoint"]["sha256"], "readback input/model identity")
                require(digest(p)==rec["sha256"], "result readback checksum")
                with np.load(p,allow_pickle=False) as f:
                    logits = f["logits"]
                    require(int(f["start"])==lo and int(f["stop"])==hi and
                            np.array_equal(f["dataset_row"],row_ids) and
                            logits.shape==(len(row_ids),24) and np.isfinite(logits).all(), "readback result bounds")
                    pred = logits.argmax(1)
                    require(np.array_equal(pred,f["predicted_class"]), "readback predictions")
                # Direct indexed increments, independent of the online bincount implementation.
                zi = (z[row_ids].astype(np.int64)+20)//2
                np.add.at(counts,(zi,y[row_ids],pred),1)
                selected = common_mask[row_ids]
                np.add.at(common,(zi[selected],y[row_ids][selected],pred[selected]),1)
                files.append(dict(path=str(p),bytes=p.stat().st_size,sha256=rec["sha256"]))
            s = json.loads((root/name/f"{ds['plane']}-summary.json").read_text())
            require(s["complete"] and s["rows"]==ds["selected_rows"] and s["correct"]==int(np.trace(counts.sum(0)))
                    and np.array_equal(counts,s["confusion_by_snr"])
                    and np.array_equal(common,s["common_confusion_by_snr"]), "readback statistics mismatch")
    atomic(root/"verification.json",dict(passed=True,files=len(files),predictions=plan["total_predictions"],
                                        method="full logits readback, hashes, argmax, independent indexed confusion recount"))
    atomic(root/"retention.json",dict(purpose="user-authorized 12 checkpoints x 3 datasets single-window engineering comparison",
                                      predictions=files,bytes=sum(f["bytes"] for f in files),
                                      plan_sha256=digest(root/"plan.json") if (root/"plan.json").exists() else None,
                                      manual_delete_argv=["rm","-rf","--",str(root)],
                                      constraint="only this evaluation root; preserve model and dataset roots"))


def render(root, plan):
    """Use the existing system matplotlib without changing the model venv."""
    script = Path(__file__).with_name("rml2018a_collection_plots.py")
    require(digest(script) == plan["plot_script"]["sha256"], "plot renderer changed")
    import subprocess
    subprocess.run(["/usr/bin/python3", "-B", str(script), "--root", str(root)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "probe", "run", "verify", "render", "status"))
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(); root = args.root.resolve()
    if args.action == "prepare":
        prepare(root); return
    if args.action == "status":
        print((root / "progress.json").read_text()); return
    lock = (root / "RUN.lock").open("a")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    plan = json.loads((root / "plan.json").read_text())
    require(digest(__file__) == plan["script"]["sha256"], "runner changed since plan")
    require(digest(COLLECTION / "manifest.json") == plan["collection_manifest"]["sha256"], "collection changed")
    for ds in plan["datasets"]:
        unchanged(ds)
    if args.action == "verify":
        verify_outputs(root,plan); return
    if args.action == "render":
        try:
            render(root,plan)
        finally:
            cache=cache_root(root)
            if cache.exists():shutil.rmtree(cache)
        return
    manifest = json.loads((COLLECTION / "manifest.json").read_text())
    for record in manifest["transferred_files"]:
        require(digest(COLLECTION / record["relative"]) == record["sha256"], "model source/config changed")
    def stop(_signum, _frame):
        raise InterruptedError("operator signal")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        torch = setup(root)
        if args.action == "probe":
            probe(root,plan,torch)
        else:
            run(root,plan,torch)
    except Exception as exc:
        atomic(root / "ERROR.json",dict(stage=args.action,error=repr(exc),time_ns=time.time_ns()))
        raise
    finally:
        cache = cache_root(root)
        if cache.exists():
            shutil.rmtree(cache)


if __name__ == "__main__":
    main()
