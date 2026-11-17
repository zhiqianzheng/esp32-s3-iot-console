#!/usr/bin/env python3
"""Provision official Sites service access over USB, without logging the token."""
import json,sys,termios,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host/sensor-dashboard'))
import serial
from core import parse_packet
old=termios.tcgetattr(sys.stdin);new=old.copy();new[3]&=~termios.ECHO;termios.tcsetattr(sys.stdin,termios.TCSANOW,new)
print('READY FOR HIDDEN SERVICE JSON',flush=True)
try:cfg=json.loads(sys.stdin.readline())
finally:termios.tcsetattr(sys.stdin,termios.TCSANOW,old)
s=serial.Serial(port=None,baudrate=115200,timeout=.2);s.dtr=False;s.rts=False;s.port='/dev/ttyACM0';s.open()
end=time.monotonic()+1.5
while time.monotonic()<end:s.readline()
s.write(('NET SERVICE '+json.dumps(cfg,separators=(',',':'))+'\n').encode());s.flush();cfg=None
print('Service credential sent through USB.',flush=True)
end=time.monotonic()+55;states=[]
while time.monotonic()<end:
 p=parse_packet(s.readline().decode(errors='replace'))
 if p and p['type']=='wifi':
  states.append(p);print('Network:',p.get('state'),p.get('error',''),flush=True)
  if p.get('state')=='online':break
s.close()
Path('logs/site-service-provisioning-status.json').write_text(json.dumps(states,ensure_ascii=False,indent=2)+'\n')
