#!/usr/bin/env python3
"""Exercise the isolated Web monitor with synthetic multi-frequency SigMF; no SDR access."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import numpy as np
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--web', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    assert root == args.root and root.parent == Path('/var/tmp/sdrharness-dev') and not root.exists()
    root.mkdir(mode=0o700)
    capture = root / 'captures' / 'session-synthetic'
    capture.mkdir(parents=True)
    state = {'controller_generation': 0, 'active_session_id': None, 'sessions': [{
        'id': 'session-synthetic', 'title': '合成验证', 'created_at_ms': 1,
        'last_used_at_ms': 1, 'generation': 1, 'status': 'stored',
        'compacted_summary': '', 'summary_pending': False, 'events_since_compaction': 0,
        'monitor_threshold_db': 15, 'events': []}]}
    (root / 'state.json').write_text(json.dumps(state))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'SDR_WEB_LISTEN_HOST': '127.0.0.1', 'SDR_WEB_LISTEN_PORT': str(port),
           'SDR_WEB_STATE_PATH': str(root/'state.json'), 'SDR_WEB_AGENT_BINARY': '/bin/false',
           'SDR_WEB_REQUEST_PATH': str(root/'absent-request.json'),
           'SDR_WEB_PROVIDER_CONFIG_PATH': str(root/'absent-provider.json'),
           'SDR_WEB_RESULT_DB_PATH': str(root/'results.sqlite3'),
           'SDR_WEB_CAPTURE_ROOT': str(root/'captures'), 'SDR_WEB_CORPUS_ROOT': str(root/'corpus'),
           'SDR_WEB_SDRD_ADDRESS': '127.0.0.1:9', 'SDR_WEB_SESSION_SOCKET': str(root/'unused.sock')}
    proc = subprocess.Popen([str(args.web)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                with urlopen(base+'/api/health', timeout=.5):
                    break
            except (URLError, TimeoutError):
                if proc.poll() is not None:
                    raise RuntimeError(proc.stderr.read().decode())
                time.sleep(.1)
        else:
            raise RuntimeError('isolated Web did not start')
        rate = 1_000_000
        n = np.arange(4096)
        def iq(tone):
            z = .4*np.exp(2j*np.pi*tone*n/rate)
            return np.column_stack((np.rint(z.real*32767),np.rint(z.imag*32767))).astype('<i2').tobytes()
        data = capture/'test.sigmf-data'
        meta = capture/'test.sigmf-meta'
        data.write_bytes(iq(125_000)+iq(-125_000))
        meta_data = {'global': {'core:datatype': 'ci16_le', 'core:sample_rate': rate}, 'captures': [
            {'core:sample_start': 0, 'core:frequency': 100_000_000, 'sdrharness:point_index': 0},
            {'core:sample_start': 4096, 'core:frequency': 101_000_000, 'sdrharness:point_index': 1}]}
        meta.write_text(json.dumps(meta_data))
        def detail(center, snr):
            return {'center_hz':center,'sample_rate_hz':rate,'rf_bandwidth_hz':800000,'captured_samples':4096,'clipped_samples':0,
                    'spectral':{'schema_version':1,'algorithm_id':'agx_welch_hann_dc_reject_obw99_v1','fft_size':1024,
                      'segment_count':4,'bin_width_hz':976.5625,'peak_frequency_hz':center,'peak_power_dbfs':-60+snr,
                      'noise_floor_dbfs':-60.,'measured_snr_db':snr,'estimated_center_hz':center,
                      'occupied_start_hz':center-500,'occupied_stop_hz':center+500,'occupied_bandwidth_hz':1953}}
        def plot(snr, sweep):
            return {'schema_version':1,'sweep_id':sweep,'kind':'planned','elapsed_ms':1,'gain_db':20,
                    'noise_floor_dbfs':-55.,'points':[[100000000,-50.],[101000000,-50.]],'candidates':[],
                    'point_analysis':[detail(100000000,snr),detail(101000000,5.)],
                    'dataset':{'format':'sigmf','datatype':'ci16_le','data_path':str(data),'metadata_path':str(meta),'bytes':data.stat().st_size}}
        with sqlite3.connect(root/'results.sqlite3') as db:
            for idx, snr in enumerate((5.,20.),1):
                p=plot(snr, f'synthetic-{idx}')
                db.execute('INSERT INTO capture_results(session_id,sweep_id,kind,created_at_ms,point_count,candidate_count,elapsed_ms,gain_db,noise_floor_dbfs,iq_bytes,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           ('session-synthetic',p['sweep_id'],'planned',idx,2,0,1,20,-55.,data.stat().st_size,json.dumps(p)))
        def get(path):
            with urlopen(base+path,timeout=20) as response:
                return json.load(response)
        report=get('/api/monitoring?session_id=session-synthetic')
        assert report['threshold_db']==15 and len(report['groups'])==2 and len(report['alerts'])==1
        assert report['groups'][0]['observations']==2 and report['groups'][0]['above_threshold']==1
        for idx, expected in ((0,125_000),(1,-125_000)):
            result=get(f'/api/results/2/spectrogram/{idx}')
            bins=np.asarray(result['grid_db']).mean(axis=0)
            peak=result['frequency_offsets_hz'][int(bins.argmax())]
            assert abs(peak-expected)<4_000,(idx,peak)
        broken=json.loads(json.dumps(meta_data));broken['captures'][1]['core:sample_start']+=1
        meta.write_text(json.dumps(broken))
        try:
            get('/api/results/2/spectrogram/1')
            raise AssertionError('mismatched segment accepted')
        except HTTPError as error:
            assert error.code == 400
        meta.write_text(json.dumps(meta_data))
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='/home/jetson/.cache/ms-playwright/chromium-1234/chrome-linux/chrome',args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':900})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/monitoring',wait_until='networkidle')
            page.wait_for_selector('#stat-rows tr')
            assert page.locator('#threshold').input_value() == '15'
            assert page.locator('#alert-rows tr').count()==1
            page.locator('#stat-rows button').first.click()
            page.wait_for_function("document.getElementById('analysis-status').textContent.includes('RFObserver')",timeout=20000)
            assert '100.125' in page.locator('#analysis-axis').inner_text() or '100.' in page.locator('#analysis-axis').inner_text()
            page.screenshot(path=str(root/'monitor.png'),full_page=True)
            assert not errors,errors
            browser.close()
        print(json.dumps({'status':'pass','rf':False,'scans':2,'groups':2,'alerts':1,'spectrograms':2,'mismatched_segment_rejected':True,'browser':True}))
    finally:
        proc.send_signal(signal.SIGTERM)
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait(timeout=5)


if __name__ == '__main__':
    main()
