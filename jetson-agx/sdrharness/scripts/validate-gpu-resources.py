#!/usr/bin/env python3
"""S4b preregistered finite real candidate resource acceptance, no RF or datasets."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import signal
import statistics
import sys
import time

if not __debug__:
    raise RuntimeError('validation requires assertions')
ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).parent
spec = importlib.util.spec_from_file_location('s4a', SCRIPTS/'validate-gpu-lease.py')
s4a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s4a)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def proc_memory(pid):
    values = {}
    for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines()[1:]:
        key, value = line.split(':', 1)
        if key in ('Rss', 'Pss'):
            values[key.lower()+'_kib'] = int(value.split()[0])
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    values['cpu_ticks'] = int(fields[11])+int(fields[12])
    return values


def distribution(values):
    ordered = sorted(values)
    return dict(min=min(values), p50=statistics.median(values),
                p95=ordered[max(0, (len(values)*95+99)//100-1)], max=max(values))


def evaluate(samples, rounds, duration, *, allow_missing_gpu_temperature=False):
    """Pure acceptance reducer, using only the frozen pre-registration gates."""
    allowed = {'gpu'} if allow_missing_gpu_temperature else set()
    assert all(not set(s.get('missing_temperatures', []))-allowed for s in samples), 'missing temperature coverage'
    assert len(rounds) == 96 and duration >= 1200
    assert len(samples) >= int(duration/5)*.95, 'telemetry coverage'
    assert max(s['max_temp_c'] for s in samples) < 80, 'thermal ceiling'
    assert min(s['available_kib'] for s in samples) >= 4*1024**2, 'available memory'
    for metric in ('pss_kib', 'nvmap_kib'):
        assert max(s[metric] for s in samples) <= 24*1024**2, metric+' ceiling'
        first = [s[metric] for s in samples if s['elapsed'] < 300]
        last = [s[metric] for s in samples if s['elapsed'] >= duration-300]
        assert first and last
        assert statistics.median(last)-statistics.median(first) <= 512*1024, metric+' growth'
    last = [s['max_temp_c'] for s in samples if s['elapsed'] >= duration-300]
    previous = [s['max_temp_c'] for s in samples if duration-600 <= s['elapsed'] < duration-300]
    assert last and previous and statistics.median(last)-statistics.median(previous) <= 5, 'thermal plateau'
    result = {}
    for metric, ceiling in [('mamba_seconds', 5), ('planner_seconds', 60)]:
        assert distribution([r[metric] for r in rounds])['p95'] <= ceiling, metric+' p95'
        result[metric] = {}
        for size in (0, 2048, 8192, 16384):
            group = [r[metric] for r in rounds if r['history_bytes'] == size]
            half = len(group)//2
            ratio = statistics.median(group[half:])/max(.05, statistics.median(group[:half]))
            assert ratio <= 2, metric+' degradation'
            result[metric][str(size)] = dict(**distribution(group), late_early_p50_ratio=ratio)
    return result


async def validate(root, *, allow_missing_gpu_temperature=False):
    assert root.resolve() == root and root.parent == Path('/var/tmp/sdrharness-dev')
    assert root.name == 's4b-906a' and not (root/'live-summary.json').exists()
    assert shutil.disk_usage(root).free >= 4*1024**3
    fixture = json.loads((root/'replay.json').read_text())
    assert (root/'model.f32').stat().st_size == 32768
    assert sha(root/'model.f32') == fixture['batch']['model_bytes_sha256']
    controller = root/'target/debug/sdr-agent'
    runtime, gate = root/'mamba', root/'gate'
    port, backend = s4a.unused_port(), s4a.unused_port()
    assert port != backend
    key = secrets.token_hex(32)
    keyfile = root/'gateway-key'; keyfile.write_text(key); keyfile.chmod(0o600)
    env = {**os.environ, 'TMPDIR':str(root/'tmp'), 'PYTHONDONTWRITEBYTECODE':'1',
           'TRITON_CACHE_DIR':str(root/'triton'), 'CUDA_CACHE_PATH':str(root/'cuda-cache')}
    processes, children, samples, rounds = [], set(), [], []
    report = dict(schema_version=1, status='failed', rx_bytes=0, synthetic_input=True,
                  locked_test_read=False, recognizer_available=False, feature_directory=str(root),
                  allow_missing_gpu_temperature=allow_missing_gpu_temperature,
                  plan_sha256=sha(ROOT/'docs/evidence/GPU_RESOURCE_S4B_PLAN_2026-09-06.md'),
                  controller_sha256=sha(controller), model_bytes_sha256=sha(root/'model.f32'))
    measurement_start = None
    monitor_task = None
    thermal_task = None
    thermal_process = None
    latest_thermal = {}
    async def command(args, timeout=70):
        p = await asyncio.create_subprocess_exec(*map(str,args), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(p.communicate(), timeout)
            assert p.returncode == 0, err.decode(errors='replace')[-1500:]
            return out.decode()
        finally:
            if p.returncode is None:
                p.kill(); await p.wait()
    async def health():
        m = await s4a.sup.exchange(runtime/'control.sock', dict(schema_version=1,operation='health'),1,s4a.sup.FRAME)
        status, s = await asyncio.wait_for(s4a.gw.backend_http(port,key,'/health'),1)
        assert status == 200 and not m['fault'] and not s['fault']
        assert not m['recognizer_available'] and not s['recognizer_available']
        assert m['queue_depth'] <= 1
        return m, s
    async def monitor():
        while True:
            began = time.monotonic()
            mem = {line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
            assert latest_thermal and began-latest_thermal['time'] <= 2, 'stale tegrastats'
            temperatures = latest_thermal['temperatures']
            assert all(k in temperatures for k in ('cpu', 'tj', 'soc0', 'soc1', 'soc2')), 'missing safety temperatures'
            missing_temperatures = [k for k in ('cpu','gpu','soc0','soc1','soc2') if k not in temperatures]
            memory = {str(pid):proc_memory(pid) for pid in children}
            nvmap = await command(['sudo','-n','cat','/sys/kernel/debug/nvmap/iovmm/clients'],3)
            allocated = {}
            for line in nvmap.splitlines():
                fields = line.split()
                if len(fields)==4 and fields[2].isdigit() and int(fields[2]) in children:
                    allocated[fields[2]] = allocated.get(fields[2],0)+int(fields[3].removesuffix('K'))
            assert set(allocated) == {str(pid) for pid in children}, 'missing nvmap client'
            row = dict(elapsed=began-measurement_start, available_kib=mem['MemAvailable'],
                       swap_used_kib=mem['SwapTotal']-mem['SwapFree'], processes=memory,
                       pss_kib=sum(p['pss_kib'] for p in memory.values()), nvmap_clients_kib=allocated,
                       nvmap_kib=sum(allocated.values()), temperatures=temperatures,
                       max_temp_c=max(temperatures.values()), thermal_sample_age_seconds=began-latest_thermal['time'])
            m, spark = await health()
            row['missing_temperatures'] = missing_temperatures
            row['queue_depth'] = m['queue_depth']
            row['mamba_active'] = m['active'] is not None
            row['spark_active'] = spark['active']
            row['gpu_frequencies_hz'] = {str(p):int(p.read_text()) for p in Path('/sys/class/devfreq').glob('*gpu*/cur_freq')}
            assert row['max_temp_c'] < 80 and row['available_kib'] >= 4*1024**2, 'resource stop'
            assert row['gpu_frequencies_hz'], 'missing GPU frequency'
            samples.append(row)
            with (root/'telemetry.jsonl').open('a') as out:out.write(json.dumps(row)+'\n')
            await asyncio.sleep(max(0,5-(time.monotonic()-began)))
    async def launch(name, args):
        with (root/f'{name}.log').open('w') as out:
            p = await asyncio.create_subprocess_exec(*map(str,args),env=env,stdout=out,stderr=asyncio.subprocess.STDOUT)
        processes.append(p)
    async def cycle(index):
        value = json.loads(json.dumps(fixture)); generation = 1000+index
        value['batch']['session_generation'] = generation
        value['batch']['capture']['session_generation'] = generation
        request = root/'current-replay.json'; request.write_text(json.dumps(value))
        start = time.monotonic()
        result = json.loads(await command([controller,'--mode','recognize-supervised-replay',
            '--recognizer-supervisor-root',runtime,'--recognition-profile',s4a.sup.PROFILE,
            '--recognizer-spool-root',root,'--repository-root',ROOT,'--request',request],12))['result']
        mamba_seconds = time.monotonic()-start
        assert result['observation']['status']=='unavailable' and len(result['experimental_batch']['windows'])==4
        observation = root/'observation.json'; observation.write_text(json.dumps(result['observation']))
        history = (0,2048,8192,16384)[index%4]
        start = time.monotonic()
        planner = json.loads(await command(['node',ROOT/'raspberry-pi/sdr-agent/planner-worker/scripts/validate-resource-planner.mjs',port,keyfile,observation,history],65))
        planner_seconds = time.monotonic()-start
        m,s = await health()
        assert {m['worker_pid'],s['worker_pid']} == children
        assert m['metrics']['failed']==0 and m['metrics']['expired']==0 and m['metrics']['busy']==0
        assert s['metrics']['failed']==0 and s['metrics']['busy']==0
        assert not list((runtime/'incoming').iterdir()) and not list((runtime/'owned').iterdir())
        return dict(index=index, history_bytes=history, mamba_seconds=mamba_seconds, planner_seconds=planner_seconds,
                    planner=planner, mamba_health=m, spark_health=s, timing=result['observation']['timing'])
    async def thermal_reader():
        while True:
            line = await thermal_process.stdout.readline()
            assert line, 'tegrastats exited'
            text = line.decode()
            temperatures = {key:float(value) for key,value in re.findall(r'(\w+)@([0-9.]+)C',text)}
            latest_thermal.update(time=time.monotonic(), temperatures=temperatures)
            with (root/'tegrastats.log').open('a') as out:out.write(text)
    try:
        thermal_process = await asyncio.create_subprocess_exec('tegrastats','--interval','1000',env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        thermal_task = asyncio.create_task(thermal_reader())
        print('S4b plan: 4 warm-up + 96 cycles, >=1200s measurement, 2400s deadline, RX=0, private root='+str(root),flush=True)
        await launch('spark',[sys.executable,SCRIPTS/'spark-gpu-gateway.py','--runtime-root',root/'spark','--gpu-lease-root',gate,'--port',port,'--backend-port',backend,'--api-key-file',keyfile,'--lifetime-seconds','3000','--max-requests','104'])
        await launch('mamba',[sys.executable,SCRIPTS/'amc-worker-supervisor.py','--runtime-root',runtime,'--gpu-lease-root',gate,'--lifetime-seconds','3000','--max-batches','104','--max-restarts','2'])
        async def workload():
            for _ in range(2400):
                try:
                    m,s = await health()
                    if m['ready'] and s['ready']:break
                except (OSError,asyncio.TimeoutError):pass
                await asyncio.sleep(.1)
            else:raise RuntimeError('startup timeout')
            children.update([m['worker_pid'],s['worker_pid']])
            report['startup_health'] = dict(mamba=m,spark=s)
            for index in range(4):await cycle(index)
            nonlocal measurement_start, monitor_task
            measurement_start = time.monotonic()
            monitor_task = asyncio.create_task(monitor())
            for index in range(4,100):
                started = time.monotonic()
                row = await cycle(index); rounds.append(row)
                print(json.dumps(dict(cycle=len(rounds),mamba_seconds=row['mamba_seconds'],planner_seconds=row['planner_seconds'],elapsed=time.monotonic()-measurement_start)),flush=True)
                await asyncio.sleep(max(0,12.5-(time.monotonic()-started)))
                if monitor_task.done():await monitor_task
            duration = time.monotonic()-measurement_start
            report['duration_seconds'] = duration
            report['latency'] = evaluate(samples,rounds,duration, allow_missing_gpu_temperature=allow_missing_gpu_temperature)
            report['status'] = 'pass'
        await asyncio.wait_for(workload(),2400)
    except BaseException as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if monitor_task:
            monitor_task.cancel(); await asyncio.gather(monitor_task,return_exceptions=True)
        for p in reversed(processes):
            if p.returncode is None:
                p.terminate()
                try:await asyncio.wait_for(p.wait(),12)
                except asyncio.TimeoutError:p.kill();await p.wait()
        if thermal_task:
            thermal_task.cancel(); await asyncio.gather(thermal_task,return_exceptions=True)
        if thermal_process and thermal_process.returncode is None:
            thermal_process.terminate(); await thermal_process.wait()
        report['thermal_exit_code'] = None if thermal_process is None else thermal_process.returncode
        report['rounds'] = rounds
        report['samples'] = len(samples)
        report['worker_pids'] = sorted(children)
        report['cleanup'] = dict(workers_dead=all(s4a.dead(pid) for pid in children),exit_codes=[p.returncode for p in processes],
            spools_empty=all(not list((runtime/name).glob('*')) for name in ('incoming','owned')),
            sockets_absent=all(not (runtime/name).exists() for name in ('control.sock','supervisor.sock','worker.sock')))
        events=[]
        for name in ('mamba','spark'):
            for line in (root/f'{name}.log').read_text().splitlines():
                if line.startswith('{"gpu_lease":'):events.append(json.loads(line)['gpu_lease'])
        events.sort(key=lambda e:e['monotonic_ns']);held=None;valid=True
        for event in events:
            identity=(event['instance'],event['serial'])
            if event['event']=='acquire':
                if held is not None:valid=False
                held=identity
            else:
                if identity!=held:valid=False
                held=None
        report['lease_intervals']=len(events)//2
        report['lease_valid']=valid and held is None and bool(events)
        if samples:
            report['resources']={key:distribution([s[key] for s in samples]) for key in ('max_temp_c','pss_kib','nvmap_kib','available_kib','swap_used_kib')}
        if not all(report['cleanup'][k] for k in ('workers_dead','spools_empty','sockets_absent')) or not report['lease_valid'] or any(p.returncode!=0 for p in processes):report['status']='failed'
        (root/'live-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    assert report['status']=='pass',report.get('failure',report['cleanup'])
    print('S4b sustained resource acceptance passed',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-directory',type=Path,required=True)
    parser.add_argument('--allow-missing-gpu-temperature',action='store_true',
                        help='explicit operator exception: report absent GPU temperature without accepting it as measured')
    args=parser.parse_args()
    async def run():
        task=asyncio.current_task()
        for sig in (signal.SIGINT,signal.SIGTERM):asyncio.get_running_loop().add_signal_handler(sig,task.cancel)
        await validate(args.feature_directory, allow_missing_gpu_temperature=args.allow_missing_gpu_temperature)
    asyncio.run(run())


if __name__=='__main__':main()
