#!/usr/bin/env python3
"""Receive sensitive provisioning input on hidden stdin; never print credentials."""
import json
import subprocess
import sys
import termios
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host/sensor-dashboard'))
import serial
from core import parse_packet
old=None
if sys.stdin.isatty():
    old=termios.tcgetattr(sys.stdin);new=old.copy();new[3]&=~termios.ECHO;termios.tcsetattr(sys.stdin,termios.TCSANOW,new)
print('READY FOR HIDDEN PROVISIONING JSON',flush=True)
try:
    cfg=json.loads(sys.stdin.readline())
finally:
    if old:termios.tcsetattr(sys.stdin,termios.TCSANOW,old)
password=subprocess.check_output(['nmcli','--show-secrets','-g','802-11-wireless-security.psk','connection','show',cfg.pop('saved_profile')],text=True).strip()
assert len(password)>=8,'Saved Wi-Fi credential not available'
cfg['password']=password
command='NET CONFIG '+json.dumps(cfg,separators=(',',':'),ensure_ascii=False)+'\n'
assert len(command.encode())<500,'Provisioning input too long'
s=serial.Serial(port=None,baudrate=115200,timeout=.15);s.dtr=False;s.rts=False;s.port='/dev/ttyACM0';s.open()
end=time.monotonic()+1.2
while time.monotonic()<end:s.readline()
s.write(command.encode());s.flush()
password=None;cfg=None;command=None
print('Provisioning sent through USB; no credentials written to host files.',flush=True)
end=time.monotonic()+55;states=[];online=False
while time.monotonic()<end:
    line=s.readline().decode(errors='replace');p=parse_packet(line)
    if p and p['type']=='wifi':
        states.append(p);print('Network:',p.get('state'),p.get('error',''),'RSSI',p.get('rssi'),flush=True)
        if p.get('state')=='online':online=True;break
s.close()
root=Path(__file__).resolve().parents[1]
(root/'logs/wifi-provisioning-status.json').write_text(json.dumps({'online':online,'states':states},ensure_ascii=False,indent=2)+'\n')
if not online:raise SystemExit('Cloud connection not confirmed yet; inspect network state, do not assume success.')
