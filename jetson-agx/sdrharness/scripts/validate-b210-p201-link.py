#!/usr/bin/env python3
"""Registered 2440/2455-MHz B210 TX / P201 RX finite engineering check."""
if not __debug__:
    raise RuntimeError('optimized Python would disable validation; refusing to run')

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import time

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).parent
spec = importlib.util.spec_from_file_location('rf_rx', SCRIPTS / 'validate-rf-v1-runtime-live.py')
rf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rf)
NX = ['ssh','-F','/home/jetson/.ssh/config','-o','ConnectTimeout=20','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=3','nx']


def remote_absence_command(feature,owner,child):
    # NX kernel omits /proc/PID/task/PID/children. Inspect exact argv/cwd instead;
    # this also detects orphaned UHD children after the timeout/helper exits.
    code = """import os
from pathlib import Path
root=Path(ROOT)
assert not (root/'tx.fc32.fifo').exists()
for pid in Path('/proc').iterdir():
    if not pid.name.isdigit():continue
    try:
        args=(pid/'cmdline').read_bytes().split(b'\\0')
        cwd=(pid/'cwd').resolve(strict=True)
    except (OSError,RuntimeError):continue
    assert int(pid.name) not in PIDS
    assert cwd != root
    assert str(root/'b210-finite-train-tx.py').encode() not in args
    assert str(root/'tx.fc32.fifo').encode() not in args
""".replace('ROOT',repr(str(feature))).replace('PIDS',repr([p for p in (owner,child) if p is not None]))
    return 'python3 -c '+shlex.quote(code)


async def run(feature, binary, mode="rml", rx_gain_db=50, center_hz=2440000000):
    assert feature.resolve() == feature and feature.parent == Path('/var/tmp/sdrharness-dev')
    assert feature.name.startswith('b210-') and feature.name.replace('-', '').isalnum()
    assert mode in ('rml', 'tone') and rx_gain_db in (40, 50)
    assert type(center_hz) is int and center_hz in (2440000000,2455000000)
    audit_path = feature / 'link-summary.json'
    assert not audit_path.exists(), 'refusing to overwrite evidence'
    # Exclusive attempt receipt prevents concurrent/repeated RF starts, even after a crash.
    with (feature / 'link-started.json').open('x') as receipt:
        json.dump({'mode':mode,'rx_gain_db':rx_gain_db,'started_at_ns':time.time_ns()},receipt)
    tx_plan = (dict(tx_gain_db=70) if mode == 'tone' else
               json.loads((feature / 'transmission-plan.json').read_text()))
    if mode=='rml':
        assert tx_plan['center_hz']==center_hz
        if center_hz==2455000000:assert tx_plan['schema_version']==4
    assert tx_plan['tx_gain_db'] in ((70,) if mode == 'tone' else (0, 40, 70))
    rate = 2500000 if mode == 'tone' else 2100000
    rx_bw = 1000000 if mode == 'tone' else 1500000
    generation = int(time.time()*1000)
    processes = []
    audit = dict(status='failed',generation=generation,feature_directory=str(feature),
                 mode=mode,max_rx_bytes=786420,max_tx_samples=(25000000 if mode == "tone" else tx_plan["tx_samples"]),tx_nominal_seconds=(10 if mode == "tone" else tx_plan["tx_nominal_seconds"]),
                 center_hz=center_hz,rate_sps=rate,bandwidth_hz=rx_bw,
                 tx_gain_db=tx_plan['tx_gain_db'],rx_gain_db=rx_gain_db,rx_input='RX1/RX0/A_BALANCED',
                 antenna_connection=True,recognizer_available=False,locked_test_read=False,
                 controller_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                 free_bytes=shutil.disk_usage(feature).free)
    assert audit['free_bytes'] > 8*1024*1024
    async def command(args, timeout=10):
        process = await asyncio.create_subprocess_exec(*map(str,args),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            out,err = await asyncio.wait_for(process.communicate(),timeout)
        finally:
            if process.returncode is None:
                process.kill();await process.wait()
        assert process.returncode == 0, err.decode()[-2000:]
        return out.decode()
    async def radio():
        return await command([*rf.SSH,rf.STATE_COMMAND])
    before = await radio()
    audit['radio_before'] = before
    state = dict(zip(before.splitlines()[::2],before.splitlines()[1::2]))
    assert all(v=='0' for p,v in state.items() if p.endswith('/enable') or p.endswith('_en'))
    connections = await command([*rf.SSH,'netstat -nt 2>/dev/null; true'])
    assert not any(':30431 ' in l and 'ESTABLISHED' in l for l in connections.splitlines())
    daemon = (await command([*rf.SSH,'pidof sdrd'])).strip()
    assert len(daemon.split()) == 1
    audit['sdrd_pid'] = daemon
    async def capture(tag, gen):
        plan = dict(sweep_id=f'b210-{tag}-{gen}',session_generation=gen,
                    frequencies=dict(kind='centers',centers_hz=[center_hz]),
                    sample_rate_hz=rate,rf_bandwidth_hz=rx_bw,gain_db=rx_gain_db,
                    settle_ms=500,frame_samples=65535,aggregate_frames=1,
                    point_timeout_ms=1000,detection_threshold_db=12.)
        audit.setdefault('plans',[]).append(plan)
        print(json.dumps(dict(event='rx_plan',plan=plan,max_bytes=262140,estimated_duration_ms=1500,
                             free_bytes=shutil.disk_usage(feature).free,agx_directory=str(feature/tag),
                             sdr_directory=f'/tmp/sdr-agent-dev/agx-sweep-{gen}-0',
                             stop=f'Controller --mode cancel --session-generation {gen}')),flush=True)
        assert shutil.disk_usage(feature).free > 262140+8*1024*1024
        path = feature/tag
        path.mkdir(mode=0o700)
        process = await asyncio.create_subprocess_exec(str(binary),'--mode','sweep','--sdrd','192.168.1.10:43110',
                    '--sigmf-directory',str(path),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        processes.append(process)
        try:
            out,err = await asyncio.wait_for(process.communicate(json.dumps(plan).encode()),15)
        except BaseException:
            try:await command([binary,'--mode','cancel','--sdrd','192.168.1.10:43110','--session-generation',gen],timeout=6)
            except Exception as error:audit.setdefault('cancel_errors',[]).append(str(error))
            raise
        (feature/f'{tag}-stderr.log').write_bytes(err)
        assert process.returncode == 0, err.decode()[-2000:]
        result = json.loads(out)
        (feature/f'{tag}-report.json').write_text(json.dumps(result,indent=2)+'\n')
        assert rf.restored_state(before,await radio()), 'P201 restoration mismatch'
        return result
    print(json.dumps({k:v for k,v in audit.items() if k!='radio_before'}),flush=True)
    tx = None
    remote_pid = None
    remote_child = None
    async def stop_remote():
        if remote_pid is None:return
        # RML helper unwinds FIFO/UHD in finally. Tone timeout forwards INT to UHD.
        if mode == 'rml':
            identity=f'case "$(tr "\\000" " " < /proc/{remote_pid}/cmdline)" in *"{feature}/b210-finite-train-tx.py"*) kill -TERM {remote_pid};; *) exit 1;; esac'
        else:
            identity=f'test "$(readlink /proc/{remote_pid}/cwd)" = "{feature}" && case "$(tr "\\000" " " < /proc/{remote_pid}/cmdline)" in *timeout*tx_waveforms*) kill -INT {remote_pid};; *) exit 1;; esac'
        await command([*NX,f'if test -d /proc/{remote_pid}; then {identity}; fi'],timeout=25)
    try:
        audit['baseline'] = await capture('baseline',generation)
        if mode == 'tone':
            # Fixed historical single-tone diagnostic, moved into the authorized
            # 2.4-GHz band. Sample count is finite even if the SSH link fails.
            tx_args = ('timeout --signal=INT --kill-after=2s 35s '
                       '/usr/lib/uhd/examples/tx_waveforms '
                       '--args type=b200,serial=2508504 --channels 0 --ant TX/RX '
                       f'--freq {center_hz} --rate 2500000 --bw 500000 '
                       '--gain 70 --wave-type SINE --wave-freq 100000 --ampl 0.2 '
                       '--nsamps 25000000')
            audit['tx_command'] = tx_args
            print(json.dumps(dict(event='finite_tone_plan',command=tx_args,
                                  max_tx_samples=25000000,nominal_seconds=10)),flush=True)
            owned_args=f'cd {feature} && echo TX_OWNER $$ && exec '+tx_args
            tx = await asyncio.create_subprocess_exec(*NX,owned_args,stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.STDOUT)
            processes.append(tx)
            owner=(await asyncio.wait_for(tx.stdout.readline(),25)).decode().strip().split()
            assert len(owner)==2 and owner[0]=='TX_OWNER' and owner[1].isdigit()
            remote_pid=int(owner[1]);assert remote_pid>1
            audit['tx_remote_owner_pid']=remote_pid
            prefix = b''
            deadline = time.monotonic()+25
            while b'Press Ctrl' not in prefix:
                remaining = deadline-time.monotonic()
                assert remaining > 0, 'tone startup timeout'
                line = await asyncio.wait_for(tx.stdout.readline(),remaining)
                assert line, prefix.decode()[-2000:]
                prefix += line
                (feature/'tx-uhd.log').write_bytes(prefix)
                assert len(prefix) <= 16384, 'tone log bound'
            children=(await command([*NX,f'ps -o pid= --ppid {remote_pid}'],timeout=25)).split()
            assert len(children)==1 and children[0].isdigit()
            remote_child=int(children[0]);audit['tx_remote_child_pid']=remote_child
            audit['tone_ready_agx_ns'] = time.time_ns()
            audit['during_tx'] = await capture('during-tx',generation+1)
            rest = await asyncio.wait_for(tx.stdout.read(),15)
            await asyncio.wait_for(tx.wait(),3)
            (feature/'tx-uhd.log').write_bytes(prefix+rest)
            assert tx.returncode == 0, (prefix+rest).decode()[-2000:]
            audit['tx_exit_code'] = tx.returncode
            audit['after_tx'] = await capture('after-tx',generation+2)
            audit['status'] = 'transport_completed_pending_signal_analysis'
            return
        # Remote timeout also bounds the NX process if the SSH transport fails.
        tx = await asyncio.create_subprocess_exec(*NX,
                f'timeout --signal=TERM --kill-after=3s 65s python3 {feature}/b210-finite-train-tx.py --directory {feature}',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        processes.append(tx)
        line = await asyncio.wait_for(tx.stdout.readline(),45)
        assert json.loads(line)['event'] == 'ready', line.decode()
        audit['tx_ready'] = json.loads(line)
        remote_pid=audit['tx_ready']['pid'];remote_child=audit['tx_ready']['child_pid']
        assert type(remote_pid) is int and type(remote_child) is int and remote_pid>1 and remote_child>1
        # A bounded, already-connected read-only sampler catches the short
        # retune/settle window without SSH startup latency.
        sampler_cmd = 'echo WATCHING; n=0; while test "$n" -lt 1000; do v=$(cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency); if test "$v" -ge 2439999900 && test "$v" -le 2440000100; then echo APPLIED; break; fi; n=$((n+1)); usleep 10000; done; n=0; while test "$n" -lt 200; do v=$(cat /sys/bus/iio/devices/iio:device3/buffer/enable); if test "$v" = 1; then echo RX_ACTIVE; exit 0; fi; n=$((n+1)); usleep 10000; done; exit 1'
        sampler_cmd=sampler_cmd.replace('2439999900',str(center_hz-100)).replace('2440000100',str(center_hz+100))
        sampler = await asyncio.create_subprocess_exec(*rf.SSH,sampler_cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        processes.append(sampler)
        assert (await asyncio.wait_for(sampler.stdout.readline(),5)).strip()==b'WATCHING'
        receive = asyncio.create_task(capture('during-tx',generation+1))
        try:
            assert (await asyncio.wait_for(sampler.stdout.readline(),12)).strip()==b'APPLIED'
            audit['go_unix_ns']=time.time_ns()
            tx.stdin.write(b'GO\n');await tx.stdin.drain()
            started_line=await asyncio.wait_for(tx.stdout.readline(),2)
            assert json.loads(started_line)['event']=='tx_start'
            audit['tx_start_ack_agx_ns']=time.time_ns()
            assert (await asyncio.wait_for(sampler.stdout.readline(),3)).strip()==b'RX_ACTIVE'
            audit['rx_active_observed_agx_ns']=time.time_ns()
            audit['during_tx']=await receive
        finally:
            if not receive.done():
                # Keep the bounded RX owner alive until restoration completes.
                await receive
        tx.stdin.close()
        output,error=await asyncio.wait_for(tx.communicate(),tx_plan['tx_nominal_seconds']+5)
        (feature/'tx-stdout.log').write_bytes(line+output)
        (feature/'tx-stderr.log').write_bytes(error)
        assert tx.returncode==0,error.decode()
        audit['tx_result']=json.loads(output.decode().strip())
        assert audit['tx_result']['status']=='sent' and audit['tx_result']['bytes_written']==tx_plan['tx_samples']*8
        audit['after_tx']=await capture('after-tx',generation+2)
        audit['status']='transport_completed_pending_signal_analysis'
    except BaseException as error:
        audit['failure']=f'{type(error).__name__}: {error}'
        raise
    finally:
        errors=[]
        if tx is not None and tx.returncode is None:
            try:await stop_remote()
            except Exception as error:errors.append('direct TX stop: '+str(error))
        for process in reversed(processes):
            if process.returncode is None:
                process.terminate()
                try:await asyncio.wait_for(process.wait(),5)
                except asyncio.TimeoutError:process.kill();await process.wait()
        try:
            if remote_pid is not None:
                for _ in range(10):
                    try:
                        await command([*NX,remote_absence_command(feature,remote_pid,remote_child)],timeout=25)
                        audit['remote_tx_stopped']=True
                        break
                    except AssertionError:await asyncio.sleep(.2)
                else:errors.append('remote TX process or FIFO remains')
            audit['radio_after']=await radio()
            if not rf.restored_state(before,audit['radio_after']):errors.append('radio restoration mismatch')
            if (await command([*rf.SSH,'pidof sdrd'])).strip()!=daemon:errors.append('daemon changed')
            for gen in (generation,generation+1,generation+2):
                await command([*rf.SSH,f'test ! -e /tmp/sdr-agent-dev/agx-sweep-{gen}-0'])
        except Exception as error:errors.append(str(error))
        audit['restoration_errors']=errors
        if errors:audit['status']='failed'
        audit['local_process_exit_codes']=[p.returncode for p in processes]
        audit_path.write_text(json.dumps(audit,indent=2)+'\n')
        assert not errors, errors


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--controller',type=Path,required=True)
    p.add_argument('--mode',choices=['rml','tone'],default='rml')
    p.add_argument('--rx-gain-db',type=int,choices=[40,50],default=50,help='40 dB is link diagnostic only; frozen RF-v1 remains 50 dB')
    p.add_argument('--center-hz',type=int,choices=[2440000000,2455000000],default=2440000000)
    a=p.parse_args()
    async def main():
        task=asyncio.current_task()
        for sig in (signal.SIGINT,signal.SIGTERM):asyncio.get_running_loop().add_signal_handler(sig,task.cancel)
        await run(a.directory,a.controller,a.mode,a.rx_gain_db,a.center_hz)
    asyncio.run(main())
