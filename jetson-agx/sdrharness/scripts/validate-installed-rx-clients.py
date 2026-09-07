#!/usr/bin/env python3
"""Bounded RX compatibility audit of supplied native CLI or supplied Web artifacts.

No deployment, model requests, production session writes, or retained IQ. Run one
phase in a fresh direct child of /var/tmp/sdrharness-dev; preserve audit.json in
the delivery record before deleting that exact feature directory.
"""
import argparse
import hashlib
from http import server as http_server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import threading
import time
import urllib.request

REPO = Path(__file__).resolve().parents[3]
BIN = Path('/home/jetson/.local/lib/sdrharness/bin')
spec = importlib.util.spec_from_file_location('rx_ports', Path(__file__).with_name('validate-sdrd-rx-ports.py'))
rf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rf)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def http(base, route, method='GET', data=None):
    payload = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(base + route, data=payload, method=method,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3) as response:
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('HTTP audit response exceeds bound')
        return json.loads(raw)


def wait_for(check, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(.1)
    raise TimeoutError('bounded condition did not complete')


def validate(args):
    if not __debug__:
        raise RuntimeError('validation requires Python assertions')
    root = args.root
    assert root.resolve() == root and root.parent == Path('/var/tmp/sdrharness-dev')
    assert all(c.isalnum() or c == '-' for c in root.name)
    password = Path('/home/jetson/.config/sdrharness/p201-root.password')
    assert password.is_file() and not password.is_symlink()
    assert stat.S_IMODE(password.stat().st_mode) == 0o600
    root.mkdir(mode=0o700)  # Fresh directory only; never reuse failed evidence.
    (root / 'tmp').mkdir(mode=0o700)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('SDR_', 'SDRHARNESS_'))}
    env.update(TMPDIR=str(root / 'tmp'), XDG_CACHE_HOME=str(root / 'cache'), PYTHONDONTWRITEBYTECODE='1')
    before = rf.ssh(rf.STATE)
    values = dict(zip(before.splitlines()[::2], before.splitlines()[1::2]))
    assert all(v == '0' for p, v in values.items() if p.endswith('_en') or p.endswith('/enable'))
    assert all(values[f'/sys/bus/iio/devices/iio:device0/in_voltage{i}_gain_control_mode'] == 'manual' for i in (0, 1))
    assert not any(':43110 ' in line and 'ESTABLISHED' in line for line in rf.ssh('netstat -nt').splitlines())
    daemon = rf.ssh('pidof sdrd').strip()
    assert len(daemon.split()) == 1
    assert sum(':43110 ' in line for line in rf.ssh('netstat -lnt').splitlines()) == 1
    protected = {route: http('http://127.0.0.1:8787', route) for route in ('/api/results', '/api/corpus')}
    user_sessions = http('http://127.0.0.1:8787', '/api/state')
    audit = dict(schema_version=1, phase=args.phase, status='failed', feature_directory=str(root),
                 radio_before=before, sdrd_pid=daemon, cases=[], recognizer_available=False,
                 tx_operations=0, model_http_requests=0, generations=[])
    audit['artifacts'] = {str(p): digest(p) for p in (args.controller, args.web, BIN / 'sdr-agent', BIN / 'sdr-agent-web-console')}
    points = 19 if args.phase == 'cli' else (50 if args.recovery else 18)
    audit['budget'] = dict(maximum_points=points, maximum_rx_bytes=points * 4096 * 4,
        centers_hz=[2455000000, 2470000000], sample_rate_hz=10000000,
        rf_bandwidth_hz=10000000, frame_samples=4096, aggregate_frames=1, gain_db=20,
        success_points=2, cancel_maximum_points=16, maximum_dwell_ms=1000,
        maximum_point_timeout_ms=250, conservative_rx_duration_ms=points * 1251,
        free_bytes=shutil.disk_usage(root).free, save_iq=False,
        p201_paths='/tmp/sdr-agent-dev/agx-sweep-<recorded-generation>-<0..15>',
        stop='Web /stop or CLI --mode cancel --session-generation N; SIGINT/SIGTERM invokes cleanup')
    assert audit['budget']['free_bytes'] > audit['budget']['maximum_rx_bytes'] + 32 * 1024 * 1024
    print(json.dumps(audit['budget']), flush=True)
    (root / 'plan.json').write_text(json.dumps(audit, indent=2))
    procs, sockets, pending = [], [], set()
    sentinel = None
    def launch(name, command, environment=env, pipe=False):
        with (root / (name + '.log')).open('w') as log:
            proc = subprocess.Popen(list(map(str, command)), env=environment,
                stdin=subprocess.PIPE if pipe else subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True)
        procs.append(proc)
        return proc
    def ctl(mode, data=None, extra=()):
        return subprocess.run([str(args.controller), '--mode', mode, '--sdrd', '192.168.1.10:43110',
            '--sdrd-timeout-ms', '2000', *map(str, extra)], input=json.dumps(data) if data is not None else '',
            text=True, capture_output=True, timeout=8, env=env)
    def restore():
        wait_for(lambda: rf.ssh(rf.STATE) == before)
    def remember(generation):
        if generation not in audit['generations']:
            audit['generations'].append(generation)
        pending.add(generation)
    def check_case(name, row):
        restore()
        audit['cases'].append(dict(name=name, restored=True, result=row))
        print(name + ': passed', flush=True)
    try:
        observed = ctl('observe')
        assert observed.returncode == 0, observed.stderr
        observation = json.loads(observed.stdout)
        assert observation['online'] and observation['healthy'] and observation['can_capture_iq']
        check_case('native observe', observation)
        if args.phase == 'cli':
            generation = int(time.time() * 1000)
            plan = dict(sweep_id=root.name, session_generation=generation,
                frequencies=dict(kind='range', start_hz=2455000000, stop_hz=2456000000, step_hz=1000000),
                sample_rate_hz=10000000, rf_bandwidth_hz=10000000, gain_db=20,
                settle_ms=20, frame_samples=4096, aggregate_frames=1, point_timeout_ms=250,
                detection_threshold_db=12.)
            remember(generation)
            result = ctl('sweep', plan)
            assert result.returncode == 0, result.stderr
            report = json.loads(result.stdout)
            assert len(report['points']) == 2 and report['dataset'] is None
            for point in report['points']:
                identity = point['rx_input']
                assert identity['verified'] and identity['front_panel_port'] == 'RX1'
                assert identity['logical_channel'] == 'RX0' and identity['rf_port_select'] == 'A_BALANCED'
                assert point['captured_samples'] == 4096 and not point['overflow'] and point['dropped_samples'] == 0
            check_case('CLI two-point sweep', report)
            pending.clear()
            invalid = ctl('sweep', dict(plan, frequencies=dict(kind='centers', centers_hz=[1])))
            assert invalid.returncode != 0
            check_case('CLI invalid frequency rejected', invalid.stderr.strip())
            remember(generation + 1)
            timeout_plan = dict(plan, session_generation=generation + 1,
                frequencies=dict(kind='centers', centers_hz=[2455000000]), point_timeout_ms=1)
            timed = ctl('sweep', timeout_plan)
            assert timed.returncode != 0 and 'timeout' in timed.stderr.lower(), timed
            check_case('CLI forced timeout', timed.stderr.strip())
            pending.clear()
            generation += 2
            remember(generation)
            cancel_plan = dict(plan, session_generation=generation, settle_ms=1000,
                frequencies=dict(kind='range', start_hz=2455000000, stop_hz=2470000000, step_hz=1000000))
            proc = launch('cli-cancel', [args.controller, '--mode', 'sweep', '--sdrd', '192.168.1.10:43110'], pipe=True)
            proc.stdin.write(json.dumps(cancel_plan).encode()); proc.stdin.close()
            wait_for(lambda: rf.ssh('cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency').strip() == '2455000000')
            cancelled = ctl('cancel', extra=('--session-generation', generation))
            assert cancelled.returncode == 0, cancelled.stderr
            assert json.loads(cancelled.stdout)['cancel_requested']
            assert proc.wait(timeout=8) != 0
            check_case('CLI active cancellation', (root / 'cli-cancel.log').read_text())
            pending.clear()
        else:
            class Sink(http_server.BaseHTTPRequestHandler):
                def do_POST(self):
                    audit['model_http_requests'] += 1
                    self.send_error(503, 'model calls forbidden in RX compatibility audit')
                def log_message(self, *_args):
                    pass
            sentinel = http_server.ThreadingHTTPServer(('127.0.0.1', 0), Sink)
            threading.Thread(target=sentinel.serve_forever, daemon=True).start()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); web_port = sock.getsockname()[1]
            base = f'http://127.0.0.1:{web_port}'
            control = Path(f'/run/user/{os.getuid()}/sdrharness')
            control.mkdir(mode=0o700, exist_ok=True)
            sockets = [control / (root.name + suffix) for suffix in ('-planner.sock', '-session.sock')]
            assert all(not p.exists() for p in sockets)
            provider = dict(schema_version=1, api='openai-completions',
                base_url=f'http://127.0.0.1:{sentinel.server_port}/v1', provider='spark-local',
                model='spark-x2.5-4b', api_key='local-audit-no-model', context_window=32768,
                compression_threshold_percent=90,
                initial_survey=dict(mode='custom_band', start_hz=2455000000, stop_hz=2456000000,
                    step_hz=1000000, dwell_ms=20, gain_db=20), result_storage=dict(save_iq=False))
            provider_path = root / 'provider.json'
            provider_path.write_text(json.dumps(provider)); provider_path.chmod(0o600)
            request_template = json.loads((REPO / 'jetson-agx/sdrharness/config/request.json').read_text())
            first_generation = int(time.time() * 1000) + (86400000 if args.recovery else 0)
            request_template['session_generation'] = first_generation
            (root / 'request.json').write_text(json.dumps(request_template))
            nodeenv = dict(env, SDR_PLANNER_BASE_URL=provider['base_url'], SDR_PLANNER_API_KEY=provider['api_key'],
                SDR_PLANNER_PROVIDER_CONFIG=str(provider_path), SDR_PLANNER_PROVIDER=provider['provider'],
                SDR_PLANNER_MODEL=provider['model'], SDR_PLANNER_SOCKET=str(sockets[0]),
                SDR_SESSION_SOCKET=str(sockets[1]), SDR_PLANNER_WEB_SEARCH_URL='')
            launch('node', ['/home/jetson/.local/bin/node', REPO / 'raspberry-pi/sdr-agent/planner-worker/src/main.mjs'], nodeenv)
            wait_for(lambda: all(p.exists() for p in sockets))
            webenv = dict(env, SDR_WEB_LISTEN_HOST='127.0.0.1', SDR_WEB_LISTEN_PORT=str(web_port),
                SDR_WEB_STATE_PATH=str(root / 'state.json'), SDR_WEB_AGENT_BINARY=str(args.controller),
                SDR_WEB_REQUEST_PATH=str(root / 'request.json'), SDR_WEB_SESSION_SOCKET=str(sockets[1]),
                SDR_WEB_SDRD_ADDRESS='192.168.1.10:43110', SDR_WEB_PROVIDER_CONFIG_PATH=str(provider_path),
                SDR_WEB_RESULT_DB_PATH=str(root / 'results.sqlite3'), SDR_WEB_CAPTURE_ROOT=str(root / 'captures'),
                SDR_WEB_CORPUS_ROOT=str(root / 'corpus'))
            web = launch('web', [args.web], webenv)
            def ready():
                assert web.poll() is None, (root / 'web.log').read_text()
                try:
                    return http(base, '/api/state')
                except OSError:
                    return None
            wait_for(ready)
            from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, env=env)
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('dialog', lambda dialog: dialog.accept())
                with page.expect_response(lambda response: response.url == base + '/api/state' and response.ok):
                    page.goto(base)
                try:
                    page.wait_for_load_state('networkidle', timeout=2000)
                except BrowserTimeout:
                    # The installed UI holds an SSE connection open. Its state
                    # response and rendered controls are the readiness barrier.
                    audit['browser_readiness'] = 'state HTTP 200 + rendered controls; SSE keeps network busy'
                page.locator('#new-session').wait_for(state='visible')
                audit['buttons'] = page.locator('button').evaluate_all('(nodes) => nodes.map(n => ({id:n.id,text:n.textContent.trim()}))')
                if args.recovery:
                    first_generation += 1  # New Web allocates above the template.
                remember(first_generation)
                print(json.dumps(dict(web_generation=first_generation, p201_point_paths=[f'/tmp/sdr-agent-dev/agx-sweep-{first_generation}-{i}' for i in range(2)])), flush=True)
                page.locator('#new-session').click()
                def session():
                    state = http(base, '/api/state')
                    return next(s for s in state['sessions'] if s['id'] == state['active_session_id'])
                first = wait_for(lambda: http(base, '/api/state')['sessions'])[-1]
                wait_for(lambda: session()['initial_survey_status'] == 'complete')
                results = http(base, '/api/results')
                assert session()['observation']['health']['recognizer_available'] is False
                assert len(results) == 1 and results[0]['point_count'] == 2 and results[0]['iq_bytes'] == 0, results
                detail = http(base, f"/api/results/{results[0]['id']}")
                check_case('installed Web initial RX and archive', detail)
                pending.clear()
                page.locator('#sweep-results-entry').click()
                page.locator('#delete-result').wait_for(state='visible')
                page.screenshot(path=str(root / 'results.png'), full_page=True)
                if args.recovery:
                    old_generation = json.loads((root / 'runtime-request.json').read_text())['session_generation']
                    assert old_generation == first_generation
                    # Closing an SSE browser is a viewer disconnect, not an RX command.
                    page.close()
                    web.terminate(); assert web.wait(timeout=10) == 0
                    restore()
                    assert not (root / 'runtime-request.json').exists()
                    web = launch('web-resumed', [args.web], webenv)
                    wait_for(ready)
                    wait_for(lambda: (root / 'runtime-request.json').exists())
                    resumed = json.loads((root / 'runtime-request.json').read_text())
                    assert resumed['session_generation'] > old_generation
                    assert resumed['observation'].get('recognition') is None
                    assert resumed['observation']['health']['recognizer_available'] is False
                    assert session()['id'] == first['id'] and session()['initial_survey_status'] == 'complete'
                    assert http(base, '/api/results') == results
                    assert http(base, f"/api/results/{results[0]['id']}") == detail
                    page = browser.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    with page.expect_response(lambda response: response.url == base + '/api/state' and response.ok):
                        page.goto(base)
                    page.locator('#sweep-results-entry').click()
                    page.locator('#delete-result').wait_for(state='visible')
                    page.on('dialog', lambda dialog: dialog.accept())
                    check_case('restart preserves completed session and result without RX replay', dict(
                        session_id=first['id'], before_generation=old_generation,
                        after_generation=resumed['session_generation'], result_count=len(results)))
                page.locator('#delete-result').click()
                wait_for(lambda: http(base, '/api/results') == [])
                check_case('browser manual result deletion', {'remaining': 0})
                page.locator('#results-back').click()
                provider['initial_survey'].update(stop_hz=2470000000, dwell_ms=1000)
                provider_path.write_text(json.dumps(provider))
                second_generation = first_generation + 1
                if args.recovery:
                    second_generation = json.loads((root / 'state.json').read_text())['controller_generation'] + 1
                request_template['session_generation'] = second_generation - (1 if args.recovery else 0)
                (root / 'request.json').write_text(json.dumps(request_template))
                remember(second_generation)
                print(json.dumps(dict(web_generation=second_generation, p201_point_paths=[f'/tmp/sdr-agent-dev/agx-sweep-{second_generation}-{i}' for i in range(16)])), flush=True)
                page.locator('#new-session').click()
                wait_for(lambda: session()['id'] != first['id'])
                wait_for(lambda: rf.ssh('cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency').strip() == '2455000000')
                page.locator('[data-command="/stop"]').click()
                restore()
                wait_for(lambda: any('停止' in event['text'] for event in session()['events']))
                assert http(base, '/api/results') == []
                check_case('browser active stop', session())
                pending.clear()
                if args.recovery:
                    stopped = session()
                    # Commands to the inactive prior session must fail before reaching CLI.
                    import urllib.error
                    try:
                        http(base, f"/api/sessions/{first['id']}/command", 'POST', {'command': '/status'})
                        raise AssertionError('inactive command accepted')
                    except urllib.error.HTTPError as error:
                        assert error.code == 409
                    http(base, f"/api/sessions/{first['id']}/activate", 'POST', {})
                    wait_for(lambda: session()['id'] == first['id'] and session()['status'] == 'connected')
                    assert session()['initial_survey_status'] == 'complete'
                    assert http(base, '/api/results') == []
                    assert next(s for s in http(base, '/api/state')['sessions'] if s['id'] == stopped['id']).get('observation') == stopped.get('observation')
                    check_case('session switch rejects inactive commands and keeps results deleted', {'http_status': 409})
                    for fault in ('controller-disconnect', 'web-shutdown'):
                        generation = json.loads((root / 'state.json').read_text())['controller_generation'] + 1
                        remember(generation)
                        print(json.dumps(dict(case=fault, generation=generation, p201_point_paths=[
                            f'/tmp/sdr-agent-dev/agx-sweep-{generation}-{i}' for i in range(16)])), flush=True)
                        # Template stays below persisted floor; the new actor must use that floor.
                        page.locator('#new-session').click()
                        wait_for(lambda: rf.ssh('cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency').strip() == '2455000000')
                        assert json.loads((root / 'runtime-request.json').read_text())['session_generation'] == generation
                        if fault == 'controller-disconnect':
                            child_ids = subprocess.check_output(['ps', '-o', 'pid=', '--ppid', str(web.pid)], text=True).split()
                            assert len(child_ids) == 1
                            os.kill(int(child_ids[0]), signal.SIGKILL)
                            wait_for(lambda: session()['status'] == 'exited')
                        else:
                            web.terminate(); assert web.wait(timeout=10) == 0
                        restore()
                        if fault == 'controller-disconnect':
                            web.terminate(); assert web.wait(timeout=10) == 0
                        assert not (root / 'runtime-request.json').exists()
                        web = launch(f'web-after-{fault}', [args.web], webenv)
                        wait_for(ready)
                        wait_for(lambda: session()['status'] == 'connected')
                        assert session()['initial_survey_status'] == 'failed'
                        assert http(base, '/api/results') == []
                        check_case(f'{fault} restores RF; restart does not repeat interrupted sweep', {
                            'session_id': session()['id'], 'status': session()['initial_survey_status'],
                            'generation': generation, 'restored_generation': json.loads((root / 'runtime-request.json').read_text())['session_generation']})
                        pending.clear()
                        with page.expect_response(lambda response: response.url == base + '/api/state' and response.ok):
                            page.reload()
                        page.locator('#new-session').wait_for(state='visible')
                assert errors == [], errors
                audit['browser_errors'] = errors
                browser.close()
            assert not list((root / 'captures').rglob('*.sigmf-data'))
        assert audit['model_http_requests'] == 0
        audit['status'] = 'passed'
    finally:
        for generation in sorted(pending):
            ctl('cancel', extra=('--session-generation', generation))
        for proc in reversed(procs):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait(timeout=3)
        if sentinel:
            sentinel.shutdown(); sentinel.server_close()
        for path in sockets:
            if path.exists():
                assert path.is_socket(); path.unlink()
        audit['processes_stopped'] = all(p.poll() is not None for p in procs)
        try:
            restore()
        except TimeoutError:
            audit['status'] = 'failed'
        audit['radio_after'] = rf.ssh(rf.STATE)
        audit['sdrd_pid_after'] = rf.ssh('pidof sdrd').strip()
        paths = [f'/tmp/sdr-agent-dev/agx-sweep-{g}-{i}' for g in audit['generations'] for i in range(16)]
        audit['p201_paths_verified_absent'] = paths
        absent = not paths or rf.ssh('for p in ' + ' '.join(paths) + '; do test ! -e "$p" || echo "$p"; done') == ''
        audit['p201_cleanup_verified'] = absent
        audit['protected_results_unchanged'] = all(http('http://127.0.0.1:8787', route) == value for route, value in protected.items())
        audit['protected_sessions_unchanged'] = http('http://127.0.0.1:8787', '/api/state') == user_sessions
        audit['restored'] = audit['radio_after'] == before and audit['sdrd_pid_after'] == daemon
        if not all(audit[k] for k in ('processes_stopped', 'p201_cleanup_verified', 'protected_results_unchanged', 'protected_sessions_unchanged', 'restored')):
            audit['status'] = 'failed'
        (root / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
        assert audit['status'] == 'passed', str(root / 'audit.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--phase', choices=['cli', 'web'], required=True)
    parser.add_argument('--controller', type=Path, required=True)
    parser.add_argument('--web', type=Path, default=BIN / 'sdr-agent-web-console')
    parser.add_argument('--recovery', action='store_true', help='Validate current Web restart, isolation and disconnect paths')
    args = parser.parse_args()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, _frame: (_ for _ in ()).throw(InterruptedError(f'signal {signum}')))
    validate(args)
