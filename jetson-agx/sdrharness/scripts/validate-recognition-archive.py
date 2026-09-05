#!/usr/bin/env python3
"""Finite S6a native Web/HTTP/CLI/browser archive verification; no RF or inference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[3]
CLIENT=Path(__file__).with_name('recognition-results.py')


def validate(feature,binary):
    assert feature.resolve()==feature and feature.parent==Path('/var/tmp/sdrharness-dev')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env={**os.environ,'TMPDIR':str(feature/'tmp'),'PYTHONDONTWRITEBYTECODE':'1','SDR_WEB_LISTEN_HOST':'127.0.0.1','SDR_WEB_LISTEN_PORT':str(port),
         'SDR_WEB_STATE_PATH':str(feature/'state.json'),'SDR_WEB_AGENT_BINARY':'/bin/false','SDR_WEB_REQUEST_PATH':str(feature/'disabled-request.json'),
         'SDR_WEB_SESSION_SOCKET':str(feature/'disabled-session.sock'),'SDR_WEB_SDRD_ADDRESS':'127.0.0.1:9',
         'SDR_WEB_PROVIDER_CONFIG_PATH':str(feature/'provider.json'),'SDR_WEB_RESULT_DB_PATH':str(feature/'results.sqlite3'),
         'SDR_WEB_CAPTURE_ROOT':str(feature/'captures'),'SDR_WEB_CORPUS_ROOT':str(feature/'corpus')}
    processes=[];checks=[]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def http(route='',method='GET',body=None,expected=200,mime='application/json'):
        req=urllib.request.Request(base+'/api/recognition-results'+route,data=body,method=method,headers={'Content-Type':mime})
        try:
            with opener.open(req,timeout=5) as r:status,data=r.status,r.read(512*1024+1)
        except urllib.error.HTTPError as e:status,data=e.code,e.read(512*1024+1)
        assert status==expected,(status,expected,data[:200])
        assert len(data)<=512*1024
        return json.loads(data)
    def start():
        with (feature/f'web-{len(processes)}.log').open('w') as log:
            proc=subprocess.Popen([str(binary)],env=env,stdout=log,stderr=subprocess.STDOUT)
        processes.append(proc)
        for _ in range(100):
            assert proc.poll() is None
            try:http();return proc
            except OSError:time.sleep(.05)
        raise AssertionError('web startup timeout')
    def stop(proc):
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=9)
            except subprocess.TimeoutExpired:proc.kill();proc.wait();raise
        assert proc.returncode==0
    def cli(*args,json_output=True):
        command=[sys.executable,str(CLIENT),'--endpoint',base]+(['--json'] if json_output else [])+list(args)
        result=subprocess.run(command,env=env,capture_output=True,timeout=12)
        assert result.returncode==0,result.stderr.decode()
        return json.loads(result.stdout) if json_output else result.stdout.decode()
    try:
        proc=start();assert http()==[]
        print('importing retained RF-v1 report and four inert states',flush=True)
        records={name:cli('import',str(feature/f'{name}.json')) for name in ('experimental','Classified','Rejected','Unavailable','Error')}
        assert len(http())==5
        assert cli('import',str(feature/'experimental.json'))['id']==records['experimental']['id']
        terminal=cli('show',str(records['experimental']['id']),json_output=False)
        assert '非生产结果' in terminal and '未校准实验概率' in terminal and 'provisional' in terminal
        checks+=['five_metadata_imports','idempotent_retry','terminal_summary']
        bad=json.loads((feature/'experimental.json').read_text());bad['result']['experimental_batch']['windows'][0]['recognition']['rf_v1']['logits'][0]=99
        http(method='POST',body=json.dumps(bad).encode(),expected=400)
        bad=json.loads((feature/'Classified.json').read_text());bad['origin']='experimental_replay'
        http(method='POST',body=json.dumps(bad).encode(),expected=400)
        bad=json.loads((feature/'experimental.json').read_text());bad['result']['observation']['observed_at_unix_ms']+=1
        http(method='POST',body=json.dumps(bad).encode(),expected=409)
        body=(feature/'experimental.json').read_bytes()
        http(method='POST',body=body,expected=415,mime='text/plain')
        http(method='POST',body=body.replace(b'"schema_version":1',b'"schema_version":1,"schema_version":1',1),expected=400)
        http(method='POST',body=b' '*66561,expected=400)
        http('/-1',expected=400);http('/999999',method='DELETE',expected=404)
        assert len(http())==5
        checks+=['tamper_rejected','production_forgery_rejected','conflict_no_overwrite','content_type_duplicate_bound_rejected','missing_delete']
        with sqlite3.connect(feature/'results.sqlite3') as db:
            stored=json.loads(db.execute('SELECT payload_json FROM recognition_results WHERE id=?',(records['experimental']['id'],)).fetchone()[0])
            assert 'experimental_batch' in stored['result'] and len(stored['result']['experimental_batch']['windows'])==4
        stop(proc);proc=start();assert {v['id'] for v in http()}=={v['id'] for v in records.values()}
        checks+=['full_internal_record_retained','native_restart_restore']
        print('checking actual browser states and manual deletion',flush=True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                # The real console holds /api/events open (SSE), so networkidle
                # never occurs. Wait for loaded state and the real connection UI.
                page.goto(base,wait_until='domcontentloaded')
                page.wait_for_function("view.state !== null && document.querySelector('.connection').classList.contains('online')")
                page.locator('#sweep-results-entry').click()
                page.locator('#archive-recognitions').click()
                page.locator('#recognition-list button').first.wait_for()
                for name,record in records.items():
                    candidate=record['observation']['candidate_id']
                    page.locator('#recognition-list button').filter(has_text=candidate).click()
                    page.wait_for_function('(expected)=>document.querySelector("#recognition-candidate").textContent===expected',arg=candidate)
                    assert record['observation']['status'] in page.locator('#recognition-status').inner_text()
                    assert ('实验回放' if name=='experimental' else '合成演示') in page.locator('#recognition-origin').inner_text()
                page.locator('.recognition-evidence summary').click()
                assert 'profile_sha256' in page.locator('#recognition-evidence').inner_text()
                page.locator('.recognition-evidence summary').click()
                page.screenshot(path=str(feature/'archive-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(feature/'archive-mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'horizontal overflow'
                page.once('dialog',lambda dialog:dialog.dismiss());page.locator('#recognition-delete').click();assert len(http())==5
                page.once('dialog',lambda dialog:dialog.accept());page.locator('#recognition-delete').click()
                page.wait_for_function('document.querySelectorAll("#recognition-list button").length===4')
                assert len(http())==4 and not errors,errors
                checks+=['browser_four_states_and_replay','mobile_no_overflow','delete_dismiss_preserves','browser_delete_confirmed','no_browser_errors']
            finally:browser.close()
        for record in http():cli('delete',str(record['id']))
        assert http()==[]
        stop(proc);proc=start();assert http()==[]
        assert not list((feature/'captures').iterdir()) and not list((feature/'corpus').iterdir())
        checks+=['terminal_manual_delete','deleted_after_restart','no_iq_files']
        summary={'schema_version':1,'status':'pass','checks':checks,'port':port,'web_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'recognizer_available':False,'rx_bytes':0,'inference_calls':0}
    finally:
        for proc in processes:stop(proc)
    summary['cleanup']={'web_pids':[p.pid for p in processes],'exit_codes':[p.returncode for p in processes],'archive_rows':0,'iq_files':0}
    (feature/'live-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('S6a native archive/browser verification passed',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--feature-directory',type=Path,required=True);p.add_argument('--web-binary',type=Path,required=True);a=p.parse_args();validate(a.feature_directory,a.web_binary)
