#!/usr/bin/env python3
"""Bounded frozen-D10 timing; no RF, training, power or production changes."""
import argparse,asyncio,ctypes,gc,importlib.metadata,json,os,resource,shutil,subprocess,sys,time
from pathlib import Path
import h5py,numpy as np
import amc_validation_eval as e
from gpu_lease import GpuLease

BASE=Path('/home/jetson/sdrharness/local-assets/amc-eval/results')
PARENT=BASE/'matched-source-baseline-20260928'
OLD=BASE/'validation-seed42-20260927-inference-a2'

def command(args,timeout=10):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout);return dict(args=args,returncode=p.returncode,stdout=p.stdout.strip(),stderr=p.stderr.strip())
    except (OSError,subprocess.TimeoutExpired) as x:return dict(args=args,error=str(x))

def host():
    paths=['/proc/device-tree/model','/proc/device-tree/compatible','/etc/nv_tegra_release','/etc/os-release','/proc/meminfo','/sys/devices/system/cpu/online']
    for k in ['cur_freq','min_freq','max_freq','governor','load']:
        paths.append('/sys/class/devfreq/17000000.gpu/'+k)
    values={}
    for name in paths:
        try:values[name]=Path(name).read_bytes().replace(b'\0',b'\n').decode().strip()
        except OSError:values[name]=None
    return dict(time_ns=time.time_ns(),files=values,commands=[command(['uname','-r']),command(['nvpmodel','-q']),command(['dpkg-query','-W','nvidia-jetpack','nvidia-l4t-core','cuda-toolkit-12-6']),command(['systemctl','show','spark-x25.service','-p','ActiveState','-p','MainPID'])])

def idle():
    e.capture.pilot().helpers()[0].spark_off()
    # Do not stop any running job; reject known concurrent compute workers.
    own=os.getpid();busy=[]
    for p in Path('/proc').glob('[0-9]*'):
        try:
            args=(p/'cmdline').read_bytes().split(b'\0');pid=int(p.name)
            if pid==own or not args:continue
            text=b' '.join(args).decode(errors='replace')
            if 'amc_paper_benchmark.py' in text:continue
            if args[0].endswith((b'python',b'python3')) and any(x in text for x in ['amc_validation_eval.py','amc_matched_source_baseline.py','amc_hisar_8psk_','amc-mamba-worker.py','spark-gpu-gateway.py']):busy.append(pid)
        except (OSError,ValueError):continue
    e.c.require(not busy,'other model workers active');return dict(known_other_compute_pids=busy,spark='inactive')

def stats(values):
    v=np.asarray(values,dtype=float);return dict(n=len(v),mean_ms=float(v.mean()),std_ms=float(v.std(ddof=1)),median_ms=float(np.median(v)),p05_ms=float(np.quantile(v,.05)),p95_ms=float(np.quantile(v,.95)),min_ms=float(v.min()),max_ms=float(v.max()))

def prepare(root,scratch):
    e.c.require(root.is_absolute() and root.resolve()==root and not root.exists(),'fresh benchmark root');e.c.require(shutil.disk_usage(root.parent).free>1024**3,'1GiB reserve')
    root.mkdir(mode=0o700);p=e.read(PARENT/'plan.json');e.atomic(root/'host-before.json',host());e.atomic(root/'idle-before.json',idle())
    e.atomic(root/'plan.json',dict(schema='amc-paper-d10-benchmark-v1',created_ns=time.time_ns(),scope='offline coax-link paper closeout; current inference microbenchmark only',parent=str(PARENT),parent_plan_sha256=e.backend.digest(PARENT/'plan.json'),datasets=p['datasets'],models=[m for m in p['models'] if m['variant']=='amc_mamba_d10'],batch_sizes=[1,128],warmup=30,repeats=200,selection='128 evenly spaced original validation ranks, frozen guard plane; batch1 uses first selected row',precision='FP32 weights/inputs/forward; TF32 off; autocast off',modes={'forward':'preloaded CUDA model-ready tensor -> CUDA logits; CUDA events and synchronized host wall time; excludes input adaptation/transfers/argmax','pipeline':'resident CPU decoded guard FP32 IQ -> frozen dataset adapter -> pageable H2D -> model -> CPU logits -> NumPy argmax; host wall time; excludes RF/capture/network/storage/sync/CFO/LO-cancellation/matched filtering/model loading'},cold_start_excluded=True,power_changes=False,clocks_changes=False,historical_power_mode='not recorded; current mode cannot be substituted',maximum_forward_rows=250000,deadline_seconds=1200,software={str(Path(__file__).resolve()):e.backend.digest(__file__),str(Path(e.__file__)):e.backend.digest(e.__file__),str(Path(e.backend.__file__)):e.backend.digest(e.backend.__file__)},no_rf=True,no_training=True,production_admission=False))

def benchmark(root,scratch,dataset):
    p=e.read(root/'plan.json');assert time.time_ns()>p['created_ns'];idle();e.resource_gate()
    for path,sha in p['software'].items():e.c.require(e.backend.digest(path)==sha,'frozen code')
    d=next(x for x in p['datasets'] if x['dataset']==dataset);spec=next(x for x in p['models'] if x['dataset']==dataset)
    for path,sha in spec['files'].items():e.c.require(e.backend.digest(path)==sha,'frozen weights/source/config')
    out=root/dataset;out.mkdir();before=host();e.atomic(out/'host-before.json',before)
    ids=np.unique(np.linspace(0,d['rows']-1,128,dtype=int));assert len(ids)==128
    with h5py.File(d['vds']) as f:
        raw=f['inputs/guard'][ids];members=f['source_row'][ids];labels=f['class_id'][ids]
    normalized=e.normalize(raw,dataset);expected=[];sources={}
    for rank in ids:
        path=OLD/dataset/'amc_mamba_d10'/f'rows-{int(rank//2048*2048):07d}.npz'
        if str(path) not in sources:sources[str(path)]=e.backend.digest(path);assert sources[str(path)]==e.read(path.with_suffix('.json'))['sha256']
        with np.load(path) as f:expected.append(f['guard_logits'][int(rank%2048)]);assert int(f['source_row'][int(rank%2048)])==int(members[len(expected)-1])
    expected=np.asarray(expected)
    for key in ['TMPDIR','CUDA_CACHE_PATH','TRITON_CACHE_DIR','TORCHINDUCTOR_CACHE_DIR']:
        path=scratch/key;path.mkdir(parents=True,exist_ok=True);os.environ[key]=str(path)
    lease=GpuLease(scratch/'gpu-gate','mamba');token=asyncio.run(lease.acquire(time.monotonic()+10,request='paper-benchmark/'+dataset))
    log=(out/'tegrastats.log').open('w');monitor=subprocess.Popen(['tegrastats','--interval','200'],stdout=log,stderr=subprocess.STDOUT);rows=0;began=time.monotonic();results=[];arrays={}
    try:
        package=Path(spec['package']);cfg=e.read(package/'config.json');model,torch=e.backend.load_frozen_model(package,cfg,True,d['class_names'])
        assert all(w.dtype==torch.float32 for w in model.parameters()) and not torch.is_autocast_enabled()
        props=torch.cuda.get_device_properties(0)
        import mamba_ssm,causal_conv1d
        runtime=dict(python=sys.version,torch=torch.__version__,torch_cuda_build=torch.version.cuda,cudnn_version=torch.backends.cudnn.version(),packages={k:importlib.metadata.version(k) for k in ['mamba-ssm','causal-conv1d','triton','numpy','h5py']},gpu=dict(name=props.name,total_memory_bytes=props.total_memory,compute_capability=[props.major,props.minor],multiprocessors=props.multi_processor_count),backend=model.encoder.backend,model_class=type(model).__module__+'.'+type(model).__name__,parameters=sum(w.numel() for w in model.parameters()),torch_threads=torch.get_num_threads(),torch_interop_threads=torch.get_num_interop_threads(),cudnn_benchmark=torch.backends.cudnn.benchmark,matmul_tf32=torch.backends.cuda.matmul.allow_tf32,cudnn_tf32=torch.backends.cudnn.allow_tf32,autocast=False)
        libs=sorted({line.split()[-1] for line in Path('/proc/self/maps').read_text().splitlines() if any(v in line for v in ['libcudart.so','causal_conv1d_cuda','selective_scan_cuda']) and '/' in line})
        runtime['loaded_libraries']={name:e.backend.digest(name) for name in libs}
        cudart=next((x for x in libs if 'libcudart.so' in x),None)
        if cudart:
            version=ctypes.c_int();status=ctypes.CDLL(cudart).cudaRuntimeGetVersion(ctypes.byref(version));runtime['cuda_runtime_version']=dict(status=status,value=version.value)
        e.atomic(out/'runtime.json',runtime)
        with torch.inference_mode():
            batch=model(torch.from_numpy(normalized).cuda()).float().cpu().numpy();rows+=128
            e.c.require(np.allclose(batch,expected,atol=2e-4,rtol=2e-4) and np.array_equal(batch.argmax(1),expected.argmax(1)),'frozen predictions')
            probe=np.linspace(0,127,8,dtype=int);single=np.concatenate([model(torch.from_numpy(normalized[i:i+1]).cuda()).float().cpu().numpy() for i in probe]);rows+=8
            e.c.require(np.allclose(single,batch[probe],atol=2e-4,rtol=2e-4) and np.array_equal(single.argmax(1),batch[probe].argmax(1)),'batch/single numerical gate')
            for bs in p['batch_sizes']:
                for mode in ['forward','pipeline']:
                    e.c.require(not (root/'STOP').exists() and time.monotonic()-began<p['deadline_seconds'],'stop/deadline');e.resource_gate();idle();gc.collect();torch.cuda.empty_cache()
                    host_input=raw[:bs];device_input=torch.from_numpy(normalized[:bs]).cuda() if mode=='forward' else None
                    def call():
                        if mode=='forward':return model(device_input)
                        xx=e.normalize(host_input,dataset);ll=model(torch.from_numpy(xx).cuda()).float().cpu().numpy();return ll.argmax(1)
                    for _ in range(p['warmup']):value=call();torch.cuda.synchronize();rows+=bs
                    del value;torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats();baseline_allocated=torch.cuda.memory_allocated();baseline_reserved=torch.cuda.memory_reserved();times=[];device_times=[]
                    event0=torch.cuda.Event(enable_timing=True);event1=torch.cuda.Event(enable_timing=True);event0.record();event1.record();event1.synchronize();started_ns=time.time_ns()
                    for iteration in range(p['repeats']):
                        torch.cuda.synchronize()
                        if mode=='forward':event0.record()
                        t0=time.perf_counter_ns();value=call()
                        if mode=='forward':event1.record();event1.synchronize()
                        else:torch.cuda.synchronize()
                        elapsed=(time.perf_counter_ns()-t0)/1e6;times.append(elapsed);rows+=bs
                        if mode=='forward':device_times.append(event0.elapsed_time(event1))
                        del value
                    memory=dict(baseline_allocated_bytes=baseline_allocated,peak_allocated_bytes=torch.cuda.max_memory_allocated(),incremental_peak_allocated_bytes=torch.cuda.max_memory_allocated()-baseline_allocated,baseline_reserved_bytes=baseline_reserved,peak_reserved_bytes=torch.cuda.max_memory_reserved(),process_ru_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,interpretation='CUDA allocator counters and process peak RSS share physical Jetson memory; do not add them; RSS includes loading/warmup since process start')
                    record=dict(dataset=dataset,batch_size=bs,mode=mode,scope=p['modes'][mode],warmup=p['warmup'],repeats=p['repeats'],start_ns=started_ns,end_ns=time.time_ns(),host=stats(times),memory=memory)
                    record['windows_per_second_from_mean_host']=bs*1000/record['host']['mean_ms'];record['host_mean_ms_per_window']=record['host']['mean_ms']/bs
                    if device_times:record['cuda_event']=stats(device_times)
                    arrays[f'{mode}_b{bs}_host_ms']=np.asarray(times)
                    if device_times:arrays[f'{mode}_b{bs}_cuda_ms']=np.asarray(device_times)
                    results.append(record);del device_input;gc.collect();torch.cuda.empty_cache();e.resource_gate();e.atomic(root/'progress.json',dict(dataset=dataset,batch_size=bs,mode=mode,status='timing'));print(dataset,bs,mode,record['host']['median_ms'],flush=True)
        torch.cuda.synchronize();after=host();e.atomic(out/'host-after.json',after)
        mode_before=next(x['stdout'] for x in before['commands'] if x['args']==['nvpmodel','-q']);mode_after=next(x['stdout'] for x in after['commands'] if x['args']==['nvpmodel','-q']);e.c.require(mode_before==mode_after,'unchanged current power mode')
        with (out/'timings.npz').open('wb') as f:np.savez_compressed(f,**arrays)
        e.atomic(out/'result.json',dict(dataset=dataset,results=results,forward_rows=rows,plan_sha256=e.backend.digest(root/'plan.json'),checkpoint_sha256=spec['files'][str(package/'best.pt')],frozen_source_predictions=sources,selection_validation_rank=ids.tolist(),selection_source_row=members.tolist(),input_sha256=e.c.digest(normalized.tobytes()),baseline_max_error=float(abs(batch-expected).max()),batch_single_max_error=float(abs(single-batch[probe]).max()),current_power_mode=mode_after,runtime_sha256=e.backend.digest(out/'runtime.json'),timings_sha256=e.backend.digest(out/'timings.npz'),elapsed_seconds=time.monotonic()-began))
    finally:
        monitor.terminate()
        try:monitor.wait(timeout=5)
        except subprocess.TimeoutExpired:monitor.kill();monitor.wait()
        log.close();lease.release(token);lease.close()

def run(root,scratch):
    p=e.read(root/'plan.json');start=time.monotonic();results=[]
    for d in p['datasets']:
        e.c.require(not (root/'STOP').exists() and time.monotonic()-start<p['deadline_seconds'],'stop/deadline')
        out=root/d['dataset'];log=root/(d['dataset']+'-worker.log')
        with log.open('w') as f:subprocess.run([sys.executable,'-B',__file__,'bench','--root',str(root),'--scratch',str(scratch),'--dataset',d['dataset']],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=p['deadline_seconds']-(time.monotonic()-start))
        results.append(e.read(out/'result.json'))
    total=sum(r['forward_rows'] for r in results);e.c.require(total<=p['maximum_forward_rows'],'forward budget')
    e.atomic(root/'benchmark-complete.json',dict(status='complete',forward_rows=total,results=results,plan_sha256=e.backend.digest(root/'plan.json')));e.atomic(root/'host-after.json',host());e.atomic(root/'progress.json',dict(status='complete',datasets=4))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run','bench']);p.add_argument('--root',type=Path,required=True);p.add_argument('--scratch',type=Path,required=True);p.add_argument('--dataset');a=p.parse_args()
    if a.command=='prepare':prepare(a.root,a.scratch)
    elif a.command=='run':run(a.root,a.scratch)
    else:benchmark(a.root,a.scratch,a.dataset)
