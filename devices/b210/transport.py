"""External B210 host transport; never owns the P201 connection."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

spec=importlib.util.spec_from_file_location('b210_device',Path(__file__).with_name('b210.py'))
device=importlib.util.module_from_spec(spec);spec.loader.exec_module(device)


def identity(host):
    device.require(host in ('agx','nx'),'TX host must be agx or nx')
    value=dict(host=host,transport_sha256=device.sha(__file__),device_helper_sha256=device.sha(device.__file__))
    if host=='agx':
        root=device.runtime()
        value.update(runtime=str(root),manifest_sha256=device.sha(device.MANIFEST))
    return value


class Transport:
    def __init__(self,host,bg):
        self.host=host;self.bg=bg;self.identity=identity(host)

    def preflight(self):
        return device.idle() if self.host=='agx' else self.bg.tx_preflight()

    def prefix(self):return ['bash','-c'] if self.host=='agx' else self.bg.NX

    def env(self):return device.environment() if self.host=='agx' else None

    def run(self,command,timeout=10):
        p=subprocess.run([*self.prefix(),command],env=self.env(),capture_output=True,text=True,timeout=timeout)
        device.require(p.returncode==0,'B210 host command failed: '+p.stderr[-1000:])
        return p.stdout

    def spawn(self,command):
        return subprocess.Popen([*self.prefix(),command],env=self.env(),stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)

    def put(self,paths,directory):
        if self.host=='agx':
            for source in map(Path,paths):
                target=Path(directory)/source.name
                device.require(not target.exists(),'B210 staging target exists')
                shutil.copyfile(source,target)
                device.require(device.sha(source)==device.sha(target),'B210 staging hash')
        else:self.bg.command(['scp','-F','/home/jetson/.ssh/config','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
            *map(str,paths),f'nx:{directory}/'],timeout=20)

    def get(self,paths,directory):
        if self.host=='agx':
            for source in map(Path,paths):
                target=Path(directory)/source.name
                device.require(not target.exists(),'B210 result target exists')
                shutil.copyfile(source,target)
                device.require(device.sha(source)==device.sha(target),'B210 result hash')
        else:self.bg.command(['scp','-F','/home/jetson/.ssh/config','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
            *[f'nx:{p}' for p in paths],str(directory)+'/'],timeout=15)
