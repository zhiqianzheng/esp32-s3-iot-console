"""Serial protocol and acquisition; independent of the desktop UI."""
import csv
import json
import math
import queue
import re
import threading
from datetime import datetime

import serial

PREFIX = 'SENSOR_JSON:'



def validate_rgb_config(obj):
    if not isinstance(obj, dict) or obj.get('mode') not in ('single', 'multi', 'rainbow', 'off'):
        raise ValueError('Invalid RGB mode')
    f, b, colors, request = (obj.get(k) for k in ('frequency','brightness','colors','request'))
    if isinstance(f,bool) or not isinstance(f,(int,float)) or not math.isfinite(f) or not .05 <= f <= 2:
        raise ValueError('Invalid frequency')
    if type(b) is not int or not 0 <= b <= 100:
        raise ValueError('Invalid brightness')
    if not isinstance(colors,list) or not 1 <= len(colors) <= 8 or any(not isinstance(c,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',c) for c in colors):
        raise ValueError('Invalid palette')
    if type(request) is not int or not 0 <= request <= 2147483647:
        raise ValueError('Invalid request')
    return obj


def build_rgb_command(obj):
    validate_rgb_config(obj)
    return 'RGB SET '+json.dumps({k:obj[k] for k in ('mode','frequency','brightness','colors','request')},separators=(',',':'))


def validate_servo_config(o):
    if not isinstance(o,dict) or o.get('mode') not in ('single','continuous') or type(o.get('enabled')) is not bool or type(o.get('hold')) is not bool:raise ValueError('Invalid servo mode')
    for k,lo,hi in [('target',0,180),('low',0,180),('high',0,180),('period',2,60),('speed',5,180)]:
        n=o.get(k)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not lo<=n<=hi:raise ValueError('Invalid servo '+k)
    if o['low']>=o['high'] or type(o.get('pwm_frequency')) is not int or not 40<=o['pwm_frequency']<=60:raise ValueError('Invalid servo range/frequency')
    if type(o.get('request')) is not int or not 0<=o['request']<=2147483647:raise ValueError('Invalid servo request')
    if 'delta' in o:
        d=o['delta']
        if isinstance(d,bool) or not isinstance(d,(int,float)) or not math.isfinite(d) or not .1<=abs(d)<=30:raise ValueError('Invalid step')
    return o


def build_servo_command(o):
    validate_servo_config(o)
    keys=('mode','enabled','target','low','high','period','speed','pwm_frequency','hold','request','delta')
    return 'SERVO SET '+json.dumps({k:o[k] for k in keys if k in o},separators=(',',':'))

def parse_packet(line):
    if PREFIX not in line:
        return None
    try:
        obj = json.loads(line.split(PREFIX, 1)[1])
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or obj.get('type') not in ('color', 'dht', 'led', 'rgb', 'servo', 'wifi'):
        return None
    if obj.get('status') not in ('ok', 'error'):
        return None
    if obj['type']=='wifi':
        return obj if isinstance(obj.get('state'),str) and isinstance(obj.get('rssi'),(int,float)) else None
    if obj['type']=='servo':
        if obj['status']=='error':return obj if type(obj.get('request')) is int and isinstance(obj.get('error'),str) else None
        try:validate_servo_config(obj)
        except ValueError:return None
        if type(obj.get('applied')) is not bool or type(obj.get('moving')) is not bool or not isinstance(obj.get('angle'),(int,float)) or not 0<=obj['angle']<=180 or type(obj.get('pulse_us')) is not int:return None
        return obj
    if obj['type'] == 'rgb':
        if obj['status']=='error':
            return obj if type(obj.get('request')) is int and isinstance(obj.get('error'),str) else None
        try:
            validate_rgb_config(obj)
        except ValueError:
            return None
        pixel=obj.get('pixel')
        if pixel is not None and (not isinstance(pixel,list) or len(pixel)!=3 or any(type(n) is not int or not 0<=n<=255 for n in pixel)):
            return None
        return obj
    if obj['type'] == 'led':
        return obj if obj['status'] == 'ok' and isinstance(obj.get('on'), bool) and obj.get('gpio') == 10 else None
    if obj['status'] == 'ok':
        fields = ('c', 'r', 'g', 'b') if obj['type'] == 'color' else ('temperature', 'humidity')
        for key in fields:
            n = obj.get(key)
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n):
                return None
        if obj['type'] == 'color':
            if any(not isinstance(obj[k], int) or not 0 <= obj[k] <= 65535 for k in fields):
                return None
        elif not (-40 <= obj['temperature'] <= 80 and 0 <= obj['humidity'] <= 100):
            return None
    return obj


class SerialReader(threading.Thread):
    def __init__(self, port, events, token):
        super().__init__(daemon=True, name='sensor-serial')
        self.port, self.events, self.token = port, events, token
        self.stopping = threading.Event()
        self.commands = queue.Queue(maxsize=16)
        self.command_lock = threading.Lock()
        self.urgent_command = None
        self.servo_owner = None

    def emit(self, kind, value):
        try:
            self.events.put_nowait((self.token, kind, value))
        except queue.Full:
            # Keep acquisition bounded if the UI is temporarily busy.
            try:
                self.events.get_nowait()
                self.events.put_nowait((self.token, kind, value))
            except (queue.Empty, queue.Full):
                pass

    def run(self):
        connection = None
        try:
            connection = serial.Serial(port=None, baudrate=115200, timeout=.25, exclusive=True)
            connection.dtr = False
            connection.rts = False
            connection.port = self.port
            connection.open()
            self.emit('connected', self.port)
            pending = b''
            while not self.stopping.is_set():
                with self.command_lock:
                    if self.urgent_command is not None:
                        command=self.urgent_command;self.urgent_command=None
                    else:
                        try:command=self.commands.get_nowait()
                        except queue.Empty:command=None
                if command is not None:
                    connection.write((command + '\n').encode('utf-8'))
                    connection.flush()
                chunk = connection.read(connection.in_waiting or 1)
                pending += chunk
                while b'\n' in pending:
                    raw, pending = pending.split(b'\n', 1)
                    line = raw.decode('utf-8', errors='replace').strip()
                    packet = parse_packet(line)
                    if packet is not None:
                        if packet['type']=='servo' and packet['status']=='ok':self.servo_owner=packet.get('owner')
                        self.emit('packet', packet)
                    elif line:
                        self.emit('log', line[:1000])
                if len(pending) > 8192:
                    pending = b''
                    self.emit('log', '丢弃过长或不完整的串口数据')
        except (serial.SerialException, OSError, ValueError) as exc:
            if not self.stopping.is_set():
                self.emit('error', str(exc))
        finally:
            if connection is not None:
                if self.servo_owner=="serial":
                    try:connection.write(b"SERVO STOP 0\n");connection.flush()
                    except (serial.SerialException,OSError):pass
                connection.close()
            self.emit('closed', None)

    def send(self, command):
        if self.stopping.is_set():return False
        if command.startswith('SERVO STOP '):
            if not re.fullmatch(r'SERVO STOP [0-9]{1,10}',command) or int(command[11:])>2147483647:return False
            with self.command_lock:
                keep=[]
                while not self.commands.empty():
                    try:c=self.commands.get_nowait()
                    except queue.Empty:break
                    if not c.startswith('SERVO SET '):keep.append(c)
                for c in keep:self.commands.put_nowait(c)
                self.urgent_command=command
            return True
        try:
            if command.startswith('RGB SET '):validate_rgb_config(json.loads(command[8:]))
            elif command.startswith('SERVO SET '):validate_servo_config(json.loads(command[10:]))
            elif command.startswith('NET WIFI '):
                o=json.loads(command[9:])
                if set(o)!={'ssid','password'} or not isinstance(o['ssid'],str) or not isinstance(o['password'],str) or not 1<=len(o['ssid'].encode())<=32 or len(o['password'].encode())>64:return False
            elif command not in ('LED ON','LED OFF','LED STATUS','RGB STATUS','SERVO STATUS','SERVO PING','NET STATUS'):return False
        except (ValueError,TypeError):return False
        with self.command_lock:
            try:self.commands.put_nowait(command);return True
            except queue.Full:return False

    def stop(self):
        self.stopping.set()
        self.join(timeout=1)


class CsvRecorder:
    columns = ('time', 'sensor', 'status', 'temperature_C', 'humidity_pct',
               'clear', 'red', 'green', 'blue', 'chip_id', 'saturated', 'ok', 'fail', 'error', 'led_on', 'rgb_mode', 'rgb_frequency_Hz', 'rgb_brightness_pct', 'rgb_colors', 'servo_angle', 'servo_enabled', 'servo_mode', 'servo_pwm_Hz', 'wifi_state')

    def __init__(self, path):
        self.file = open(path, 'w', newline='', encoding='utf-8-sig')
        self.writer = csv.DictWriter(self.file, fieldnames=self.columns)
        self.writer.writeheader()
        self.rows = 0
        self.file.flush()

    def write(self, obj):
        row = dict(time=datetime.now().astimezone().isoformat(timespec='milliseconds'),
                   sensor=obj['type'], status=obj['status'])
        for key in ('ok', 'fail', 'error'):
            if key in obj:
                row[key] = obj[key]
        if obj['status'] == 'ok':
            if obj['type']=='servo':row.update(servo_angle=obj['angle'],servo_enabled=obj['enabled'],servo_mode=obj['mode'],servo_pwm_Hz=obj['pwm_frequency'])
            elif obj['type']=='wifi':row['wifi_state']=obj['state']
            elif obj['type'] == 'rgb':
                row.update(rgb_mode=obj['mode'],rgb_frequency_Hz=obj['frequency'],rgb_brightness_pct=obj['brightness'],rgb_colors=';'.join(obj['colors']))
            elif obj['type'] == 'led':
                row['led_on'] = obj['on']
            elif obj['type'] == 'dht':
                row.update(temperature_C=obj['temperature'], humidity_pct=obj['humidity'])
            else:
                row.update(clear=obj['c'], red=obj['r'], green=obj['g'], blue=obj['b'],
                           chip_id=obj.get('id', ''), saturated=obj.get('saturated', False))
        self.writer.writerow(row)
        self.file.flush()
        self.rows += 1

    def close(self):
        self.file.close()
