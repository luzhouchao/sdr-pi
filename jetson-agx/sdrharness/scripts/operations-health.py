#!/usr/bin/env python3
"""Bounded read-only local health snapshots; state changes only, no external alerts/actions."""
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import socket
import stat
import time
import urllib.parse

LIMIT = 16384


def decode(raw):
    if len(raw) > LIMIT:raise ValueError('frame_limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:raise ValueError('duplicate_key')
            result[key] = value
        return result
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))


def private_read(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        m=os.fstat(f.fileno())
        if not stat.S_ISREG(m.st_mode) or m.st_nlink!=1 or m.st_uid!=os.geteuid() or m.st_mode&0o077:raise ValueError('private_file')
        data=f.read(LIMIT+1)
    if len(data)>LIMIT:raise ValueError('file_limit')
    return data


def validate_config(config):
    if set(config)!={'schema_version','probes','disk_path','minimum_free_bytes'} or type(config['schema_version']) is not int or config['schema_version']!=1:raise ValueError('config')
    if not isinstance(config['probes'],list) or not 1<=len(config['probes'])<=8:raise ValueError('probes')
    if type(config['minimum_free_bytes']) is not int or config['minimum_free_bytes']<0:raise ValueError('space_limit')
    if not Path(config['disk_path']).is_absolute():raise ValueError('disk_path')
    names=set()
    for p in config['probes']:
        if set(p)-{'name','kind','endpoint','key_file'} or not {'name','kind','endpoint'}<=set(p):raise ValueError('probe_fields')
        if p['name'] in names or p['name'] not in ('web','planner','mamba','spark'):raise ValueError('probe_name')
        names.add(p['name'])
        if p['kind']=='http':
            u=urllib.parse.urlsplit(p['endpoint'])
            if u.scheme!='http' or u.hostname not in ('127.0.0.1','::1') or u.username or u.password or u.query or u.fragment or u.path not in ('/health','/api/health'):raise ValueError('local_health_url')
            if p['name'] not in ('web','spark'):raise ValueError('http_service')
        elif p['kind']=='unix':
            if p['name'] not in ('planner','mamba') or not Path(p['endpoint']).is_absolute() or 'key_file' in p:raise ValueError('unix_service')
        else:raise ValueError('probe_kind')
    return config


async def http_health(endpoint,key):
    u=urllib.parse.urlsplit(endpoint)
    reader,writer=await asyncio.open_connection(u.hostname,u.port or 80,limit=8192)
    try:
        auth='' if key is None else 'Authorization: Bearer '+key+'\r\n'
        writer.write((f'GET {u.path} HTTP/1.1\r\nHost: {u.hostname}\r\n'+auth+'Connection: close\r\n\r\n').encode())
        await writer.drain()
        raw=await reader.readuntil(b'\r\n\r\n')
        if len(raw)>8192:raise ValueError('header_limit')
        lines=raw.decode('ascii').split('\r\n')
        if len(lines[0].split())<2 or lines[0].split()[0] not in ('HTTP/1.0','HTTP/1.1') or lines[0].split()[1]!='200':raise ValueError('http_status')
        headers={}
        for line in lines[1:-2]:
            k,v=line.split(':',1);k=k.lower()
            if k in headers:raise ValueError('duplicate_header')
            headers[k]=v.strip()
        if 'transfer-encoding' in headers:raise ValueError('framing')
        length=int(headers['content-length'])
        if not 0<length<=LIMIT:raise ValueError('body_limit')
        return decode(await reader.readexactly(length))
    finally:
        writer.close()
        await writer.wait_closed()


def probe(p):
    # Do not include exception strings, URLs, response bodies or credentials in alerts.
    try:
        if p['kind']=='http':
            key=None
            if p.get('key_file'):
                key=private_read(p['key_file']).decode().strip()
                if not 16<=len(key)<=128 or not key.isalnum():raise ValueError('key')
            value=asyncio.run(asyncio.wait_for(http_health(p['endpoint'],key),2))
        else:
            payload=(b'{"protocol_version":1,"operation":"health"}\n' if p['name']=='planner' else b'{"schema_version":1,"operation":"health"}\n')
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(1);client.connect(p['endpoint']);client.sendall(payload)
                raw=b'';deadline=time.monotonic()+1
                while not raw.endswith(b'\n'):
                    client.settimeout(max(.001,deadline-time.monotonic()))
                    chunk=client.recv(min(4096,LIMIT+1-len(raw)))
                    if not chunk:raise ValueError('truncated')
                    raw+=chunk
                    if len(raw)>LIMIT:raise ValueError('frame_limit')
                value=decode(raw)
        if not isinstance(value,dict) or type(value.get('schema_version')) is not int or value.get('schema_version')!=1 or value.get('recognizer_available') is not False or type(value.get('ready')) is not bool:raise ValueError('health_contract')
        if p['name'] in ('web','planner') and value.get('service')!=p['name']:raise ValueError('service_identity')
        if p['name']=='mamba' and (value.get('operation')!='health' or type(value.get('queue_depth')) is not int or value.get('queue_capacity')!=1 or not 0<=value['queue_depth']<=1):raise ValueError('queue_contract')
        return {'name':p['name'],'status':'healthy' if value['ready'] and not value.get('fault') else 'unavailable'}
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,RecursionError,asyncio.TimeoutError,asyncio.IncompleteReadError,asyncio.LimitOverrunError):
        return {'name':p['name'],'status':'unavailable'}


def transitions(previous,current):
    events=[]
    for name,status in sorted(current.items()):
        old=previous.get(name)
        if status!=old:
            events.append({'service':name,'status':status,'event':'recovered' if status=='healthy' and old is not None else ('healthy' if status=='healthy' else 'alert')})
    for name in sorted(previous.keys()-current.keys()):events.append({'service':name,'event':'probe_removed','status':'unmonitored'})
    return events


def snapshot(config,state_path):
    # A private permanent flock serializes snapshot/transition/state replacement.
    parent=state_path.parent.resolve(strict=True)
    if state_path.parent!=parent:raise ValueError('state_parent')
    lock_path=Path(str(state_path)+'.lock')
    fd=os.open(lock_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a+b') as lock:
        m=os.fstat(lock.fileno())
        if not stat.S_ISREG(m.st_mode) or m.st_nlink!=1 or m.st_uid!=os.geteuid() or m.st_mode&0o077:raise ValueError('state_lock')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        previous=decode(private_read(state_path)) if state_path.exists() else {'schema_version':1,'statuses':{}}
        if set(previous)!={'schema_version','statuses'} or type(previous['schema_version']) is not int or previous['schema_version']!=1 or not isinstance(previous['statuses'],dict):raise ValueError('state_contract')
        if not set(previous['statuses'])<={'web','planner','mamba','spark','disk'} or any(s not in ('healthy','unavailable','low_space') for s in previous['statuses'].values()):raise ValueError('state_statuses')
        current={p['name']:probe(p)['status'] for p in config['probes']}
        disk=os.statvfs(config['disk_path']);free=disk.f_bavail*disk.f_frsize
        current['disk']='healthy' if free>=config['minimum_free_bytes'] else 'low_space'
        events=transitions(previous['statuses'],current)
        temporary=Path(str(state_path)+f'.tmp-{os.getpid()}')
        created=False
        try:
            raw=json.dumps({'schema_version':1,'statuses':current}).encode()
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            created=True
            with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
            os.replace(temporary,state_path)
        finally:
            if created and temporary.exists():temporary.unlink()
        return {'schema_version':1,'observed_at_unix_ms':time.time_ns()//1000000,'recognizer_available':False,'statuses':current,'events':events,'free_bytes':free}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--state',type=Path,required=True)
    args=parser.parse_args()
    try:
        config=validate_config(decode(private_read(args.config)))
        result=snapshot(config,args.state)
        print(json.dumps(result,sort_keys=True))
        return 0 if all(s=='healthy' for s in result['statuses'].values()) else 2
    except (OSError,ValueError,TypeError,KeyError,RecursionError):
        print(json.dumps({'schema_version':1,'error':'health_monitor_failed','recognizer_available':False}))
        return 3


if __name__=='__main__':raise SystemExit(main())
