#!/usr/bin/env python3
"""Finite daily RX/browser acceptance on installed services with private Web storage.

Temporarily overlays only Web data paths, then restores the original service and
checks original user records. Requires an idle single operator and AGENTS.md RX
authorization. Does not prompt a model, change Planner settings, or retain IQ.
Use a fresh direct feature directory; never repeat a failed attempt in place.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import time
import urllib.request

REPO = Path(__file__).resolve().parents[3]
BIN = Path('/home/jetson/.local/lib/sdrharness/bin')
spec = importlib.util.spec_from_file_location('rx_helpers', Path(__file__).with_name('validate-installed-rx-clients.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
BASE = 'http://127.0.0.1:8787'
OVERLAY = Path('/etc/systemd/system/sdrharness-web.service.d/90-rx-daily.conf')
PLANS = [
    dict(name='433mhz', start_hz=433000000, stop_hz=435000000, step_hz=1000000, dwell_ms=20, gain_db=20),
    dict(name='24ghz', start_hz=2400000000, stop_hz=2480000000, step_hz=8000000, dwell_ms=20, gain_db=20),
    dict(name='58ghz', start_hz=5725000000, stop_hz=5805000000, step_hz=8000000, dwell_ms=20, gain_db=20),
    dict(name='stop', start_hz=2455000000, stop_hz=2470000000, step_hz=1000000, dwell_ms=1000, gain_db=20),
]


def command(*args, check=True):
    p = subprocess.run(list(map(str, args)), text=True, capture_output=True, timeout=60)
    if check and p.returncode:
        raise RuntimeError(f'{args[:4]}: {p.stderr[-1200:]}')
    return p.stdout.strip()


def api(route, method='GET', data=None):
    return h.http(BASE, route, method, data)


def active():
    s = api('/api/state')
    return next(x for x in s['sessions'] if x['id'] == s['active_session_id'])


def wait(check, timeout=20):
    def ready():
        try:
            return check()
        except (OSError, StopIteration):
            return None
    return h.wait_for(ready, timeout)


def stop_web():
    state = api('/api/state')
    if state['active_session_id']:
        old = {e['id'] for e in active()['events']}
        api('/api/sessions/' + state['active_session_id'] + '/command', 'POST', {'command': '/stop'})
        wait(lambda: any(e['id'] not in old and '会话已停止' in e['text'] for e in active()['events']))
    command('sudo', '-n', 'systemctl', 'stop', 'sdrharness-web.service')
    assert command('systemctl', 'show', 'sdrharness-web.service', '-p', 'MainPID', '--value') == '0'


def start_web():
    command('sudo', '-n', 'systemctl', 'daemon-reload')
    command('sudo', '-n', 'systemctl', 'start', 'sdrharness-web.service')
    wait(lambda: api('/api/health')['ready'])


def health_snapshot():
    command('sudo', '-n', 'systemctl', 'start', 'sdrharness-health.service')
    assert command('systemctl', 'show', 'sdrharness-health.service', '-p', 'ExecMainStatus', '--value') == '0'
    result = json.loads(Path('/var/lib/sdrharness/health/state.json').read_text())
    assert result['statuses'] == {'web': 'healthy', 'planner': 'healthy', 'disk': 'healthy'}
    return result


def run(root):
    assert __debug__ and root.is_absolute() and root.resolve() == root
    assert root.parent == Path('/var/tmp/sdrharness-dev') and all(c.isalnum() or c == '-' for c in root.name)
    assert not OVERLAY.exists() and not OVERLAY.is_symlink()
    credential = Path('/home/jetson/.config/sdrharness/p201-root.password')
    assert credential.is_file() and not credential.is_symlink() and stat.S_IMODE(credential.stat().st_mode) == 0o600
    root.mkdir(mode=0o700)
    (root / 'tmp').mkdir(mode=0o700)
    audit = dict(schema_version=1, status='failed', root=str(root), cases=[], plans=[], generations=[], rx_only=True,
                 recognizer_available=False, browser_errors=[], requests=[], started_at_ms=int(time.time()*1000), validator_sha256=h.digest(Path(__file__)))
    before = {p: api(p) for p in ('/api/state', '/api/results', '/api/corpus')}
    assert all(s['initial_survey_status'] == 'complete' for s in before['/api/state']['sessions'])
    audit['protected_before'] = {k: hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest() for k, v in before.items()}
    audit['protected_session_ids'] = [s['id'] for s in before['/api/state']['sessions']]
    audit['protected_config_hashes'] = {str(p): h.digest(p) for p in (
        Path('/etc/sdrharness/runtime.env'), Path('/etc/sdrharness/request.json'),
        Path('/var/lib/sdrharness/web-console/provider.json'), BIN/'sdr-agent', BIN/'sdr-agent-web-console')}
    radio = h.rf.ssh(h.rf.STATE)
    values = dict(zip(radio.splitlines()[::2], radio.splitlines()[1::2]))
    assert all(v == '0' for p,v in values.items() if p.endswith('_en') or p.endswith('/enable'))
    assert not any(':43110 ' in x and 'ESTABLISHED' in x for x in h.rf.ssh('netstat -nt').splitlines())
    audit['sdrd_pid'] = h.rf.ssh('pidof sdrd').strip()
    assert len(audit['sdrd_pid'].split()) == 1
    assert sum(':43110 ' in x for x in h.rf.ssh('netstat -lnt').splitlines()) == 1
    audit['radio_before'] = radio
    for p in PLANS:
        plan = dict(p, points=(p['stop_hz']-p['start_hz'])//p['step_hz']+1,
                    sample_rate_hz=10000000, rf_bandwidth_hz=10000000, samples_per_point=4096,
                    point_deadline_ms=250, aggregate_frames=1, save_iq=False, input='RX1/RX0/A_BALANCED')
        plan['maximum_bytes'] = plan['points']*4096*4
        audit['plans'].append(plan)
    audit['budget'] = dict(maximum_points=sum(p['points'] for p in audit['plans']),
                           maximum_rx_bytes=sum(p['maximum_bytes'] for p in audit['plans']),
                           conservative_rx_duration_ms=41*1251, test_wall_deadline_seconds=300,
                           free_bytes=shutil.disk_usage(root).free,
                           stop='Visible /stop; dedicated CLI cancel; finally removes overlay and restores original Web')
    assert audit['budget']['free_bytes'] > audit['budget']['maximum_rx_bytes'] + 64*1024**2
    (root/'plan.json').write_text(json.dumps(audit, indent=2)+'\n')
    print(json.dumps(audit['budget']), flush=True)
    # A future private generation floor lets every P201 path be registered before RX.
    request = json.loads((REPO/'jetson-agx/sdrharness/config/request.json').read_text())
    request['session_generation'] = int(time.time()*1000)+86400000
    (root/'request.json').write_text(json.dumps(request))
    provider = dict(schema_version=1, api='openai-completions', base_url='http://127.0.0.1:9/v1',
                    provider='spark-local', model='rx-only-validation', api_key='local-no-model-request',
                    context_window=32768, compression_threshold_percent=90,
                    initial_survey=dict(mode='disabled', **{k:v for k,v in PLANS[0].items() if k!='name'}),
                    result_storage=dict(save_iq=False))
    (root/'provider.json').write_text(json.dumps(provider)); (root/'provider.json').chmod(0o600)
    fields={'SDR_WEB_STATE_PATH':root/'state.json','SDR_WEB_PROVIDER_CONFIG_PATH':root/'provider.json',
            'SDR_WEB_REQUEST_PATH':root/'request.json','SDR_WEB_RESULT_DB_PATH':root/'results.sqlite3',
            'SDR_WEB_CAPTURE_ROOT':root/'captures','SDR_WEB_CORPUS_ROOT':root/'corpus'}
    (root/'web.env').write_text(''.join(f'{k}={v}\n' for k,v in fields.items())); (root/'web.env').chmod(0o600)
    overlay='[Service]\nEnvironmentFile='+str(root/'web.env')+'\nBindPaths='+str(root)+'\nReadWritePaths='+str(root)+'\n'
    (root/'overlay.conf').write_text(overlay)
    original_recovery = command('systemctl','is-active','sdrharness-p201-sdrd-recovery.timer')
    switched = False
    pending = None
    def restored():
        wait(lambda: h.rf.ssh(h.rf.STATE) == radio)
    try:
        command('sudo','-n','systemctl','stop','sdrharness-p201-sdrd-recovery.timer')
        stop_web()
        command('sudo','-n','install','-m','644',root/'overlay.conf',OVERLAY)
        switched = True
        start_web()
        assert api('/api/state')['sessions'] == [] and api('/api/results') == [] and api('/api/corpus') == []
        audit['health_before_rx'] = health_snapshot()
        from playwright.sync_api import sync_playwright
        env=dict(os.environ,TMPDIR=str(root/'tmp'),XDG_CACHE_HOME=str(root/'cache'))
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,env=env)
            page=browser.new_page(viewport={'width':1440,'height':900})
            page.on('pageerror',lambda e:audit['browser_errors'].append(str(e)))
            def trace(req):
                if req.method != 'GET':
                    # Only route/method, never provider request payload or key.
                    audit['requests'].append({'method':req.method,'path':req.url.removeprefix(BASE)})
            page.on('request',trace)
            with page.expect_response(lambda r:r.url==BASE+'/api/state' and r.ok):page.goto(BASE)
            page.locator('#new-session').wait_for(state='visible')
            for index,plan in enumerate(audit['plans']):
                assert time.time()*1000-audit['started_at_ms'] < 300000
                page.locator('#settings-entry').click()
                section=page.locator('.survey-settings')
                if not section.evaluate('(e)=>e.open'):section.locator('summary').click()
                page.locator('input[name="survey-mode"][value="custom_band"]').check()
                for key,selector,divisor in [('start_hz','#survey-start-mhz',1000000),('stop_hz','#survey-stop-mhz',1000000),('step_hz','#survey-step-mhz',1000000),('dwell_ms','#survey-dwell-ms',1),('gain_db','#survey-gain-db',1)]:
                    page.locator(selector).fill(str(plan[key]/divisor))
                assert page.locator('#survey-budget').get_attribute('data-state')=='ready'
                with page.expect_response(lambda r:r.url==BASE+'/api/provider' and r.request.method=='PUT' and r.ok):page.locator('#save-settings').click()
                assert api('/api/provider')['initial_survey']=={k:plan[k] for k in ('start_hz','stop_hz','step_hz','dwell_ms','gain_db')}|{'mode':'custom_band'}
                page.locator('#settings-back').click()
                floor=json.loads((root/'state.json').read_text()).get('controller_generation',0) if (root/'state.json').exists() else 0
                generation=max(floor,request['session_generation'])+1
                audit['generations'].append({'generation':generation,'paths':[f'/tmp/sdr-agent-dev/agx-sweep-{generation}-{i}' for i in range(plan['points'])]})
                (root/'paths-before-rx.json').write_text(json.dumps(audit['generations'],indent=2)+'\n')
                pending=generation
                page.locator('#new-session').click()
                page.locator('#confirm-dialog').wait_for(state='visible')
                # Cancel first, verify no RF/session effect, then explicitly create.
                if index==0:
                    page.locator('#confirm-cancel').click();assert api('/api/state')['sessions']==[];restored()
                    page.locator('#new-session').click()
                old_id=api('/api/state')['active_session_id']
                page.locator('#confirm-accept').click()
                wait(lambda: active()['id']!=old_id)
                wait(lambda: (root/'runtime-request.json').exists())
                assert json.loads((root/'runtime-request.json').read_text())['session_generation']==generation
                row={'name':plan['name'],'session_id':active()['id'],'generation':generation,'maximum_bytes':plan['maximum_bytes']}
                if plan['name']=='stop':
                    wait(lambda: h.rf.ssh('cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency').strip()=='2455000000')
                    assert active()['initial_survey_status']=='running'
                    page.wait_for_function("document.querySelector('#session-survey').textContent==='首次扫描进行中'")
                    row['visible_running_label']=page.locator('#session-survey').inner_text()
                    row['health_during_rx']=health_snapshot()
                    page.screenshot(path=str(root/'receiving.png'))
                    stopped_at=time.monotonic()
                    page.locator('.emergency-stop').click()
                    wait(lambda:any('会话已停止' in e['text'] for e in active()['events']))
                    restored();row['stop_and_restore_ms']=round((time.monotonic()-stopped_at)*1000)
                    page.wait_for_function("document.querySelector('#session-survey').textContent==='首次扫描已取消'")
                    assert page.locator('#receive-status').get_attribute('data-state')=='cancelled'
                    row['visible_stopped_label']=page.locator('#session-survey').inner_text()
                    page.screenshot(path=str(root/'cancelled.png'))
                    row['stop_events']=[e['text'] for e in active()['events'] if '取消' in e['text'] or '停止' in e['text']]
                    assert len(api('/api/results'))==3
                else:
                    wait(lambda:active()['initial_survey_status'] in ('complete','failed'))
                    assert active()['initial_survey_status']=='complete',active()
                    restored()
                    results=api('/api/results');assert len(results)==index+1
                    current=next(x for x in results if x['session_id']==row['session_id'])
                    detail=api('/api/results/'+str(current['id']));plot=detail['sweep_plot']
                    assert len(plot['points'])==plan['points'] and plot['gain_db']==plan['gain_db'] and not plot.get('dataset')
                    assert [x[0] for x in plot['points']]==list(range(plan['start_hz'],plan['stop_hz']+1,plan['step_hz']))
                    assert all(math.isfinite(x[1]) for x in plot['points']) and math.isfinite(plot['noise_floor_dbfs'])
                    assert active()['observation']['health']['recognizer_available'] is False
                    page.locator('#sweep-results-entry').click();page.locator('#result-content').wait_for(state='visible')
                    assert page.locator('#result-title').inner_text()==plot['sweep_id']
                    assert str(plan['points']) in page.locator('#result-points').inner_text()
                    page.locator('.spectrum-data-panel summary').click();assert page.locator('#spectrum-data tr').count()==plan['points']
                    page.screenshot(path=str(root/(plan['name']+'.png')),full_page=True)
                    if index==2:
                        page.set_viewport_size({'width':390,'height':844})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(root/'mobile-results.png'),full_page=True)
                        page.set_viewport_size({'width':1440,'height':900})
                    page.locator('#results-back').click()
                    row.update(result_id=current['id'],detail=detail,observation=active()['observation'])
                restored();pending=None;row['radio_restored']=True
                audit['cases'].append(row);print(plan['name']+': passed',flush=True)
            # Existing test results survive Web restart without another RX request.
            results=api('/api/results');old_sessions=[x['id'] for x in api('/api/state')['sessions']]
            stop_web();start_web();wait(lambda:active()['status']=='connected');restored()
            assert api('/api/results')==results and [x['id'] for x in api('/api/state')['sessions']]==old_sessions
            with page.expect_response(lambda r:r.url==BASE+'/api/state' and r.ok):page.reload()
            page.locator('#sweep-results-entry').click();page.locator('#delete-result').wait_for(state='visible')
            page.locator('#delete-result').click();page.locator('#confirm-cancel').click();assert api('/api/results')==results
            for _ in range(3):
                page.locator('#delete-result').wait_for(state='visible');page.locator('#delete-result').click()
                with page.expect_response(lambda r:r.request.method=='DELETE' and '/api/results/' in r.url and r.ok):page.locator('#confirm-accept').click()
            wait(lambda:api('/api/results')==[])
            audit['restart_and_manual_delete']={'preserved_results':3,'cancel_kept_results':True,'deleted_test_results':3,'remaining':0}
            assert audit['browser_errors']==[]
            assert not list((root/'captures').rglob('*.sigmf-data'))
            browser.close()
        audit['status']='passed'
    except Exception as error:
        audit['failure_type']=type(error).__name__
        raise
    finally:
        if pending is not None:
            command(BIN/'sdr-agent','--mode','cancel','--sdrd','192.168.1.10:43110','--session-generation',pending,check=False)
        if switched:
            try:stop_web()
            finally:
                command('sudo','-n','systemctl','stop','sdrharness-web.service')
                assert OVERLAY.read_text()==overlay
                command('sudo','-n','rm','--',OVERLAY)
                start_web();wait(lambda:active()['status']=='connected')
        elif command('systemctl','show','sdrharness-web.service','-p','MainPID','--value')=='0':
            start_web();wait(lambda:active()['status']=='connected')
        if original_recovery=='active':command('sudo','-n','systemctl','start','sdrharness-p201-sdrd-recovery.timer')
        restored()
        audit['health_after']=health_snapshot()
        audit['radio_after']=h.rf.ssh(h.rf.STATE)
        audit['sdrd_pid_after']=h.rf.ssh('pidof sdrd').strip()
        audit['protected_results_unchanged']=all(api(p)==before[p] for p in ('/api/results','/api/corpus'))
        original=api('/api/state')
        audit['protected_sessions_restored']=sorted(s['id'] for s in original['sessions'])==sorted(audit['protected_session_ids']) and all(s['initial_survey_status']=='complete' for s in original['sessions'])
        audit['config_binary_hashes_unchanged']=all(h.digest(Path(p))==v for p,v in audit['protected_config_hashes'].items())
        paths=[p for g in audit['generations'] for p in g['paths']]
        audit['p201_paths_absent']=not paths or h.rf.ssh('for p in '+' '.join(paths)+'; do test ! -e "$p" || echo "$p"; done')==''
        audit['overlay_removed']=not OVERLAY.exists()
        audit['final_web_pid']=command('systemctl','show','sdrharness-web.service','-p','MainPID','--value')
        for key in ('protected_results_unchanged','protected_sessions_restored','config_binary_hashes_unchanged','p201_paths_absent','overlay_removed'):
            if not audit[key]:audit['status']='failed'
        (root/'audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
        print('final state: '+audit['status'],flush=True)
    assert audit['status']=='passed'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);args=p.parse_args()
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,lambda signum,_frame:(_ for _ in ()).throw(InterruptedError(f'signal {signum}')))
    run(args.root)
