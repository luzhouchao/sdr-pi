#!/usr/bin/env python3
"""AGX-local B210 identity/runtime checks. No RF stream or P201 access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPO=Path(__file__).resolve().parents[2]
MANIFEST=Path(__file__).with_name('runtime-manifest.json')
SERIAL='2508504'


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime():
    m=json.loads(MANIFEST.read_text())
    require(m['schema']=='b210-agx-runtime-v1' and m['serial']==SERIAL and m['fpga']=='A7-100T','B210 manifest identity')
    root=(REPO/m['runtime_relative']).resolve(strict=True)
    require(root==REPO/'local-assets/devices/b210/uhd-4.1.0.5-3-a7-100t','B210 runtime root')
    require(sha(root/'images/usrp_b210_fpga.bin')=='ee03a9e38c83a1f6f327e7b560522c2a96629e7de574196092c1b830d05fcf9b','verified A7-100T image required')
    require(sha(root/'images/usrp_b200_fw.hex')=='cc8e4bc968d91d1a67c63871ce5b2c1613c49676fe363bf2f6e336059899ae5c','verified FX3 firmware required')
    for item in m['files']:
        p=root/item['path']
        require(p.resolve()==p and p.is_file() and p.stat().st_size==item['bytes'] and sha(p)==item['sha256'],'B210 runtime changed: '+item['path'])
    require(sha(m['system_library']['path'])==m['system_library']['sha256'],'UHD library changed')
    return root


def environment():
    env=os.environ.copy();env['UHD_IMAGES_DIR']=str(runtime()/'images')
    env['SDRHARNESS_B210_TX_BINARY']=str(runtime()/'bin/tx_samples_from_file')
    env['PYTHONDONTWRITEBYTECODE']='1'
    return env


def usb_devices():
    rows=[]
    for p in Path('/sys/bus/usb/devices').iterdir():
        if not (p/'idVendor').exists():continue
        if (p/'idVendor').read_text().strip()!='2500' or (p/'idProduct').read_text().strip()!='0020':continue
        row={key:(p/key).read_text().strip() for key in ('serial','speed','busnum','devnum')}
        row['node']=f"/dev/bus/usb/{int(row['busnum']):03d}/{int(row['devnum']):03d}"
        row['sysfs']=str(p.resolve());rows.append(row)
    return rows


def idle(*,ready=True):
    runtime();rows=usb_devices();require(len(rows)==1,'exactly one B210 USB device required')
    row=rows[0]
    if ready:require(row['serial']==SERIAL and float(row['speed'])>=5000,'B210 runtime serial/USB3 not ready; run device probe')
    p=subprocess.run(['sudo','-n','fuser',row['node']],capture_output=True,text=True,timeout=5)
    require(p.returncode==1 and not p.stdout.strip(),'B210 USB busy or ownership check failed')
    return dict(host='agx',serial=row['serial'],usb_speed_mbps=float(row['speed']),usb_node=row['node'],usb_holder_pids=[])


def probe(output):
    require(output.is_absolute() and output.resolve()==output and output.parent==Path('/var/tmp/sdrharness-dev') and
            output.name.startswith('b210-agx-') and not output.exists(),'new bounded B210 probe root required')
    before=idle(ready=False);output.mkdir(mode=0o700)
    record=dict(before=before,rf_streams=0,p201_operations=0,eeprom_or_flash_writes=0,
                images_dir=str(runtime()/'images'),maximum_command_seconds=[35,70],status='failed')
    try:
        for name,args,timeout in [('discover',['uhd_find_devices','--args','type=b200'],35),
            ('probe',['uhd_usrp_probe','--args','type=b200,serial='+SERIAL],70)]:
            command=[str(runtime()/'bin'/args[0]),*args[1:]]
            p=subprocess.run(command,env=environment(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
            (output/(name+'.log')).write_text(p.stdout)
            require(p.returncode==0,name+' failed; see bounded log')
            require(('serial: '+SERIAL) in p.stdout if name=='discover' else
                    'Operating over USB 3' in p.stdout and p.stdout.count('Register loopback test passed')>=2,'B210 identity/USB3/loopback gate')
        record.update(after=idle(),status='passed')
    except BaseException as e:
        record['error']=f'{type(e).__name__}: {e}';raise
    finally:
        (output/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['status','probe'])
    p.add_argument('--output',type=Path);args=p.parse_args()
    if args.command=='probe':
        require(args.output is not None,'probe requires --output');probe(args.output)
    else:print(json.dumps(dict(runtime=str(runtime()),usb=usb_devices(),dataset=str((REPO/'local-assets/amc-eval/datasets/rml2018a/RML2018a.hdf5').resolve()),rf_streams=0),indent=2))
