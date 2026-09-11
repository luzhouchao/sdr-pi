#!/usr/bin/env python3
"""Fixed P201 network RX health entry; never imports UHD or accesses B210 USB."""
import argparse
import os
from pathlib import Path

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['health']);parser.parse_args()
    binary=Path('/home/jetson/.local/lib/sdrharness/bin/sdr-agent')
    os.execv(str(binary),[str(binary),'--mode','health','--sdrd','192.168.1.10:43110'])
