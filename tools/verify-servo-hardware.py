#!/usr/bin/env python3
"""Bounded servo protocol verification; always finish with PWM disabled."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host/sensor-dashboard'))
import serial
from core import parse_packet
s=serial.Serial(port=None,baudrate=115200,timeout=.15);s.dtr=False;s.rts=False;s.port='/dev/ttyACM0';s.open()
results=[];latest={}
def send(c):s.write((c+'\n').encode());s.flush()
def wait(predicate,timeout=5,ping=True):
 end=time.monotonic()+timeout;lastping=0
 while time.monotonic()<end:
  if ping and time.monotonic()-lastping>1:send('SERVO PING');lastping=time.monotonic()
  p=parse_packet(s.readline().decode(errors='replace'))
  if p:
   latest[p['type']]=p
   if predicate(p):return p
 raise AssertionError('Device state not confirmed')
def command(request,**kw):
 p=dict(mode='single',enabled=True,target=90,low=60,high=120,period=4,speed=60,pwm_frequency=50,hold=True,request=request);p.update(kw)
 send('SERVO SET '+json.dumps(p,separators=(',',':')))
 return wait(lambda x:x['type']=='servo' and x.get('request')==request and x.get('applied'))
def record(name,p):results.append({'test':name,'state':p});print(name,'PASS',json.dumps(p,ensure_ascii=False),flush=True)
try:
 send('SERVO STOP 7100');wait(lambda p:p['type']=='servo' and not p['enabled'])
 command(7101,target=95);record('single',wait(lambda p:p['type']=='servo' and abs(p.get('angle',0)-95)<1))
 command(7102,delta=-5);record('step',wait(lambda p:p['type']=='servo' and abs(p.get('angle',0)-90)<1))
 command(7103,mode='continuous',low=75,high=105,period=4)
 start=time.monotonic();angles=[]
 while time.monotonic()-start<4.5:
  p=wait(lambda p:p['type']=='servo',timeout=2);angles.append(p['angle'])
 assert max(angles)-min(angles)>20
 record('continuous',{'min_commanded_angle':min(angles),'max_commanded_angle':max(angles)})
 send('SERVO STOP 7104');record('stop',wait(lambda p:p['type']=='servo' and p.get('request')==7104 and not p['enabled']))
 command(7105,target=90,pwm_frequency=55);record('pwm_frequency',wait(lambda p:p['type']=='servo' and p.get('pwm_frequency')==55 and p.get('enabled')))
 record('lost_contact_timeout',wait(lambda p:p['type']=='servo' and not p['enabled'] and p.get('link_timeout'),timeout=8,ping=False))
 print('Wi-Fi observation:',json.dumps(latest.get('wifi',{})),flush=True)
finally:
 send('SERVO STOP 7199');s.close()
 Path('logs/servo-hardware-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
