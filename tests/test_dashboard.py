import csv
import json
import os
from pathlib import Path
import pty
import queue
import select
import sys
import tempfile
import time
import tkinter as tk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host/sensor-dashboard'))
from core import parse_packet, CsvRecorder, build_rgb_command, validate_rgb_config, build_servo_command, SerialReader
from app import Dashboard

COLOR = dict(type='color', status='ok', id=77, c=1000, r=400, g=300, b=200, ok=1, fail=0)
RGB = dict(type='rgb',status='ok',mode='multi',frequency=.25,brightness=35,colors=['#FF0000','#0000FF'],request=0,pixel=[0,0,0],revision=1)
SERVO = dict(type='servo',status='ok',mode='single',enabled=False,target=90.,low=60.,high=120.,period=4.,speed=60.,pwm_frequency=50,hold=True,request=0,applied=True,moving=False,angle=90.,pulse_us=0,gpio=14,owner='serial')
DHT = dict(type='dht', status='ok', temperature=23.5, humidity=51., ok=1, fail=0)


class ProtocolTests(unittest.TestCase):
    def test_ignores_logs_and_rejects_invalid_measurements(self):
        self.assertIsNone(parse_packet('I (1) COLOR: boot log'))
        self.assertIsNone(parse_packet('SENSOR_JSON:{bad'))
        for patch in ({'temperature': float('nan')}, {'humidity': 101}, {'temperature': True}):
            self.assertIsNone(parse_packet('SENSOR_JSON:'+json.dumps(DHT | patch)))
        self.assertIsNone(parse_packet('SENSOR_JSON:'+json.dumps(COLOR | {'r': -1})))
        self.assertEqual(parse_packet('SENSOR_JSON:'+json.dumps(COLOR)), COLOR)

    def test_servo_validation_and_stop_preempts_queued_motion(self):
        self.assertEqual(parse_packet('SENSOR_JSON:'+json.dumps(SERVO)),SERVO)
        for patch in ({'target':181},{'low':130,'high':120},{'pwm_frequency':500},{'delta':0},{'delta':31},{'period':0},{'speed':False}):
            with self.assertRaises(ValueError):build_servo_command(SERVO|patch)
        reader=SerialReader('/not-open',queue.Queue(),1)
        self.assertTrue(reader.send(build_servo_command(SERVO|dict(enabled=True))))
        self.assertTrue(reader.send('LED ON'))
        self.assertTrue(reader.send('SERVO STOP 123'))
        self.assertEqual(reader.urgent_command,'SERVO STOP 123')
        self.assertEqual(list(reader.commands.queue),['LED ON'])
        self.assertFalse(reader.send('NET WIFI {"ssid":"x","password":"x","device_key":"not allowed"}'))

    def test_rgb_validation_command_and_csv(self):
        self.assertEqual(parse_packet('SENSOR_JSON:'+json.dumps(RGB)),RGB)
        cmd=build_rgb_command(RGB)
        self.assertEqual(json.loads(cmd[8:])['colors'],['#FF0000','#0000FF'])
        for patch in ({'frequency':0},{'frequency':float('nan')},{'frequency':2.1},{'brightness':True},{'brightness':101},{'colors':[]},{'colors':['#ZZ0000']},{'colors':['#000000']*9},{'request':-1},{'mode':'unknown'}):
            with self.assertRaises(ValueError):build_rgb_command(RGB|patch)
            self.assertIsNone(parse_packet('SENSOR_JSON:'+json.dumps(RGB|patch)))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'rgb.csv';r=CsvRecorder(p);r.write(RGB);r.close()
            with p.open(encoding='utf-8-sig') as f: row=next(csv.DictReader(f))
            self.assertEqual(row['rgb_mode'],'multi')
            self.assertEqual(row['rgb_colors'],'#FF0000;#0000FF')

    def test_led_packet_requires_boolean_and_correct_gpio(self):
        good = dict(type='led', status='ok', on=False, gpio=10)
        self.assertEqual(parse_packet('SENSOR_JSON:'+json.dumps(good)), good)
        for patch in ({'on': 1}, {'gpio': 14}, {'status': 'error'}):
            self.assertIsNone(parse_packet('SENSOR_JSON:'+json.dumps(good | patch)))

    def test_csv_errors_have_no_fabricated_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'data.csv'
            recorder = CsvRecorder(p)
            recorder.write(DHT)
            recorder.write(dict(type='dht', status='error', error='timeout'))
            recorder.close()
            with p.open(encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]['temperature_C'], '23.5')
            self.assertEqual(rows[1]['temperature_C'], '')
            self.assertEqual(rows[1]['error'], 'timeout')


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = pty.openpty()
        self.path = os.ttyname(self.slave)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = Dashboard(self.root)
        self.app.port.set(self.path)

    def tearDown(self):
        self.app.close()
        for fd in (self.master, self.slave):
            try: os.close(fd)
            except OSError: pass

    def pump(self, condition, timeout=3):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            self.root.update()
            if condition():
                return
            time.sleep(.015)
        self.fail('UI condition timed out')

    def send(self, obj):
        os.write(self.master, ('SENSOR_JSON:'+json.dumps(obj)+'\r\n').encode())

    def test_servo_ui_ack_and_stop_bypasses_invalid_input(self):
        self.app.connect();self.pump(lambda:self.app.connected)
        self.send(SERVO);self.pump(lambda:self.app.servo_controls.synced)
        ui=self.app.servo_controls;ui.vars['target'].set('95');ui.apply()
        self.assertIsNotNone(ui.pending);rid=ui.pending[0]
        self.send(SERVO|dict(request=rid,applied=False));self.root.update();self.assertIsNotNone(ui.pending)
        self.send(SERVO|dict(request=rid,applied=True,enabled=True,target=95.,angle=95.,pulse_us=1556))
        self.pump(lambda:ui.pending is None);self.assertIn('95.0',ui.status.get())
        ui.vars['pwm_frequency'].set('invalid');ui.stop()
        self.assertIsNotNone(ui.pending)
        stop_rid=ui.pending[0]
        self.send(SERVO|dict(request=stop_rid,enabled=False))
        self.pump(lambda:ui.pending is None);self.assertIn('PWM已停止',ui.status.get())

    def test_rgb_settings_ack_preserves_unsent_edits_and_handles_timeout(self):
        self.app.connect();self.pump(lambda:self.app.connected)
        self.send(RGB);self.pump(lambda:self.app.rgb_controls.synced)
        ui=self.app.rgb_controls
        ui.mode.set('单色呼吸');ui.frequency.set('1.00');ui.brightness.set(50);ui.palette=['#123456']
        self.send(RGB);self.root.update()
        self.assertEqual(ui.mode.get(),'单色呼吸')
        ui.apply();self.assertIsNotNone(ui.pending)
        requested=ui.pending[0]
        self.send(RGB);self.root.update();self.assertIsNotNone(ui.pending)
        self.send(RGB|requested|dict(revision=2))
        self.pump(lambda:ui.pending is None)
        self.assertEqual(ui.actual['colors'],['#123456'])
        self.assertIn('1.00 Hz',ui.status.get())
        ui.pending=(dict(request=999),time.monotonic()-5);ui.tick()
        self.assertIsNone(ui.pending);self.assertIn('超时',ui.status.get())
        self.app.disconnect();self.assertFalse(ui.connected)

    def test_led_command_waits_for_matching_device_ack_and_times_out(self):
        self.app.connect()
        self.pump(lambda:self.app.connected)
        self.send(dict(type='led', status='ok', on=False, gpio=10))
        self.pump(lambda:self.app.led_state is False)
        self.app.set_led(True)
        self.assertIsNotNone(self.app.led_pending)
        self.assertIn('等待', self.app.led_text.get())
        commands=b''
        end=time.monotonic()+2
        while time.monotonic()<end and b'LED ON\n' not in commands:
            if select.select([self.master],[],[],.1)[0]:
                commands+=os.read(self.master,1024)
            self.root.update()
        self.assertIn(b'LED ON\n',commands)
        self.send(dict(type='led', status='ok', on=False, gpio=10))
        self.pump(lambda:self.app.events.empty())
        self.assertIsNotNone(self.app.led_pending)
        self.send(dict(type='led', status='ok', on=True, gpio=10))
        self.pump(lambda:self.app.led_state is True and self.app.led_pending is None)
        self.assertIn('已开',self.app.led_text.get())
        self.app.led_pending=(False,time.monotonic()-4)
        self.app.update_status()
        self.assertIsNone(self.app.led_state)
        self.assertIn('超时',self.app.led_text.get())
        self.app.disconnect()
        self.assertIn('未确认',self.app.led_text.get())

    def test_serial_to_cards_csv_errors_disconnect_and_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'capture.csv'
            self.app.recorder=CsvRecorder(p)
            self.app.connect()
            self.pump(lambda:self.app.connected)
            # Partial serial lines must be reassembled without losing a packet.
            data=('SENSOR_JSON:'+json.dumps(COLOR)+'\n').encode()
            os.write(self.master,data[:20]);os.write(self.master,data[20:])
            self.send(DHT)
            self.pump(lambda:self.app.total==2)
            self.assertEqual(self.app.values['temperature'].get(),'23.5')
            self.assertEqual(self.app.values['clear'].get(),'1000')
            self.send(dict(type='dht',status='error',error='ESP_ERR_TIMEOUT'))
            self.pump(lambda:self.app.values['temperature'].get()=='—')
            self.assertEqual(self.app.values['clear'].get(),'1000')
            self.app.seen['color']=time.monotonic()-4
            self.app.update_status()
            self.assertEqual(self.app.values['clear'].get(),'—')
            self.app.stop_csv()
            with p.open(encoding='utf-8-sig') as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),3)
            self.assertEqual(rows[0]['red'],'400')
            self.assertEqual(rows[1]['humidity_pct'],'51.0')
            self.assertEqual(rows[2]['temperature_C'],'')
            self.app.disconnect()
            self.assertFalse(self.app.connected)
            self.app.connect()
            self.pump(lambda:self.app.connected)
            self.send(COLOR)
            self.pump(lambda:self.app.total==1)
            self.assertEqual(self.app.values['C'].get(),'1000')
            os.close(self.master)
            self.pump(lambda:not self.app.connected)
            self.assertEqual(self.app.values['clear'].get(),'—')


if __name__=='__main__':
    unittest.main()
