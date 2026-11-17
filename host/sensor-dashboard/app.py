#!/usr/bin/env python3
"""Local ESP32 sensor dashboard. No web server or cloud dependency."""
import argparse
import collections
import queue
import time
import tkinter as tk
from tkinter import ttk, filedialog

from serial.tools import list_ports
from core import SerialReader, CsvRecorder
from rgb_controls import RGBControls
from servo_controls import ServoControls
from network_controls import NetworkControls

BG = '#eef2f7'
INK = '#172b4d'
MUTED = '#64748b'
BLUE = '#2563eb'
COLORS = {'R': '#e55765', 'G': '#15a779', 'B': '#4285ee', 'C': '#9671cf',
          '温度 °C': '#ef8a32', '湿度 %RH': '#16a4ab'}
FONT = 'Noto Sans CJK SC'


class Chart(tk.Canvas):
    def __init__(self, parent, names, *, fixed_max=None):
        super().__init__(parent, bg='white', height=185, highlightthickness=0)
        self.names, self.fixed_max = names, fixed_max
        self.points = collections.deque(maxlen=240)
        self.bind('<Configure>', lambda _: self.draw())

    def add(self, timestamp, values):
        self.points.append((timestamp, values))
        self.draw()

    def draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80 or h < 80:
            return
        left, top, right, bottom = 53, 30, w - 15, h - 28
        maximum = self.fixed_max or max(10, max((max(v) for _, v in self.points), default=10) * 1.15)
        for i in range(5):
            y = bottom - (bottom - top) * i / 4
            self.create_line(left, y, right, y, fill='#e8eef5')
            self.create_text(left - 8, y, text=f'{maximum*i/4:.0f}', anchor='e', fill=MUTED, font=(FONT, 8))
        x = left
        for name in self.names:
            self.create_line(x, 13, x + 14, 13, fill=COLORS[name], width=3)
            self.create_text(x + 20, 13, text=name, anchor='w', fill=MUTED, font=(FONT, 8))
            x += 96 if len(self.names) == 2 else 60
        if not self.points:
            self.create_text((left + right)/2, (top + bottom)/2, text='等待实时数据', fill=MUTED, font=(FONT, 11))
        else:
            end = self.points[-1][0]
            start = end - 120
            for index, name in enumerate(self.names):
                segments, current, last_t = [], [], None
                for t, values in self.points:
                    if t < start:
                        continue
                    if last_t is not None and t - last_t > (8 if self.fixed_max else 3):
                        segments.append(current)
                        current = []
                    current.extend((left + (t-start)/120*(right-left), bottom-values[index]/maximum*(bottom-top)))
                    last_t = t
                segments.append(current)
                for segment in segments:
                    if len(segment) >= 4:
                        self.create_line(*segment, fill=COLORS[name], width=2)
            self.create_text(left, h-10, text='−120秒', anchor='w', fill=MUTED, font=(FONT, 8))
            self.create_text(right, h-10, text='最近采样', anchor='e', fill=MUTED, font=(FONT, 8))


class Dashboard:
    def __init__(self, root, auto_port=None, state_file=None):
        self.root, self.state_file = root, state_file
        self.reader = None
        self.closing = False
        self.token = 0
        self.events = queue.Queue(maxsize=2048)
        self.connected = False
        self.recorder = None
        self.last = {'color': None, 'dht': None}
        self.seen = {'color': 0., 'dht': 0.}
        self.total = 0
        self.state_snapshot = None
        self.connect_time = 0
        self.port = tk.StringVar()
        self.connection_text = tk.StringVar(value='未连接')
        self.color_text = tk.StringVar(value='等待颜色传感器')
        self.dht_text = tk.StringVar(value='等待温湿度传感器')
        self.foot = tk.StringVar(value='连接开发板 COM 接口后，选择串口并连接。')
        self.csv_text = tk.StringVar(value='开始 CSV 记录')
        self.led_text = tk.StringVar(value='补光灯：未确认')
        self.led_state = None
        self.led_seen = 0.
        self.led_pending = None
        self.values = {key: tk.StringVar(value='—') for key in ('temperature', 'humidity', 'clear', 'count', 'R', 'G', 'B', 'C')}
        self.build()
        self.refresh_ports()
        if auto_port:
            self.port.set(auto_port)
            self.root.after(250, self.connect)
        self.poll_id = self.root.after(80, self.poll)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def label(self, parent, text=None, variable=None, size=11, color=INK, bold=False, bg='white', **kw):
        return tk.Label(parent, text=text, textvariable=variable, bg=bg, fg=color,
                        font=(FONT, size, 'bold' if bold else 'normal'), **kw)

    def build(self):
        self.root.title('ESP32 传感器工作台')
        self.root.geometry('1260x1120')
        self.root.minsize(1100, 940)
        self.root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', font=(FONT, 10), padding=(12, 7))
        style.configure('TCombobox', padding=6)
        top = tk.Frame(self.root, bg=INK, padx=24, pady=17)
        top.pack(fill='x')
        self.label(top, 'ESP32  /  传感器工作台', size=19, bold=True, color='white', bg=INK).pack(side='left')
        self.label(top, '本地实时采集  ·  USB 实时采集与设备控制', size=10, color='#b4c7e1', bg=INK).pack(side='right')
        controls = tk.Frame(self.root, bg=BG, padx=24, pady=13)
        controls.pack(fill='x')
        self.label(controls, '串口', bg=BG, color=MUTED).pack(side='left', padx=(0, 10))
        self.combo = ttk.Combobox(controls, textvariable=self.port, width=27)
        self.combo.pack(side='left')
        ttk.Button(controls, text='刷新', command=self.refresh_ports).pack(side='left', padx=7)
        self.connect_button = ttk.Button(controls, text='连接设备', command=self.toggle)
        self.connect_button.pack(side='left')
        self.connection_label = self.label(controls, variable=self.connection_text, bg=BG, color=MUTED)
        self.connection_label.pack(side='left', padx=16)
        ttk.Button(controls, textvariable=self.csv_text, command=self.toggle_csv).pack(side='right')
        body = tk.Frame(self.root, bg=BG, padx=24)
        body.pack(fill='both', expand=True)
        cards = tk.Frame(body, bg=BG)
        cards.pack(fill='x', pady=(0, 13))
        for i, (key, title, unit, color) in enumerate((('temperature', '温度', '°C', '#dc7c2e'), ('humidity', '相对湿度', '%RH', '#15969d'), ('clear', '透明通道 C', '原始计数', '#8961b4'), ('count', '有效数据帧', '本次连接', BLUE))):
            cards.columnconfigure(i, weight=1, uniform='card')
            card = tk.Frame(cards, bg='white', padx=18, pady=10)
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
            self.label(card, title, color=MUTED, size=10).pack(anchor='w')
            line = tk.Frame(card, bg='white'); line.pack(fill='x')
            self.label(line, variable=self.values[key], size=27, bold=True, color=color).pack(side='left')
            self.label(line, unit, color=MUTED, size=9).pack(side='left', padx=9, pady=(15, 0))
        self.control_tabs=ttk.Notebook(body)
        self.control_tabs.pack(fill='x',pady=(0,13))
        sender=lambda command:bool(self.reader and self.reader.send(command))
        self.rgb_controls=RGBControls(self.control_tabs,sender)
        self.servo_controls=ServoControls(self.control_tabs,sender)
        self.network_controls=NetworkControls(self.control_tabs,sender)
        self.control_tabs.add(self.rgb_controls,text='板载RGB呼吸灯')
        self.control_tabs.add(self.servo_controls,text='舵机控制')
        self.control_tabs.add(self.network_controls,text='Wi-Fi与云端')
        panels = tk.Frame(body, bg=BG); panels.pack(fill='both', expand=True)
        panels.columnconfigure(0, weight=1); panels.columnconfigure(1, weight=1)
        panels.rowconfigure(0, weight=1)
        color_panel = tk.Frame(panels, bg='white', padx=17, pady=12)
        color_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 7))
        dht_panel = tk.Frame(panels, bg='white', padx=17, pady=12)
        dht_panel.grid(row=0, column=1, sticky='nsew', padx=(7, 0))
        self.label(color_panel, '颜色传感器', size=15, bold=True).pack(anchor='w')
        self.label(color_panel, variable=self.color_text, size=9, color=MUTED).pack(anchor='w', pady=(1, 10))
        led_controls = tk.Frame(color_panel, bg='white')
        led_controls.pack(fill='x', pady=(0, 10))
        self.label(led_controls, variable=self.led_text, size=10, color=BLUE).pack(side='left')
        self.led_off_button = ttk.Button(led_controls, text='关灯', command=lambda: self.set_led(False), state='disabled')
        self.led_off_button.pack(side='right')
        self.led_on_button = ttk.Button(led_controls, text='开灯', command=lambda: self.set_led(True), state='disabled')
        self.led_on_button.pack(side='right', padx=6)
        channels = tk.Frame(color_panel, bg='white'); channels.pack(fill='x')
        self.swatch = tk.Canvas(channels, width=115, height=103, bg='#e2e8f0', highlightthickness=0)
        self.swatch.pack(side='left', padx=(0, 13))
        nums = tk.Frame(channels, bg='white'); nums.pack(side='left', fill='x', expand=True)
        self.bars = {}
        for key in ('R', 'G', 'B', 'C'):
            row = tk.Frame(nums, bg='white'); row.pack(fill='x', pady=2)
            self.label(row, key, bold=True, color=COLORS[key], size=10, width=2).pack(side='left')
            bar = tk.Canvas(row, width=130, height=9, bg='#eef2f7', highlightthickness=0)
            bar.pack(side='left', padx=6)
            self.bars[key] = bar
            self.label(row, variable=self.values[key], size=10, width=7, anchor='e').pack(side='right')
        self.label(color_panel, '相对颜色预览 · 未做白平衡或颜色标定', size=9, color=MUTED).pack(anchor='w', pady=(7, 9))
        self.color_chart = Chart(color_panel, ('R', 'G', 'B', 'C'))
        self.color_chart.pack(fill='both', expand=True)
        self.label(dht_panel, '温湿度传感器', size=15, bold=True).pack(anchor='w')
        self.label(dht_panel, variable=self.dht_text, size=9, color=MUTED).pack(anchor='w', pady=(1, 10))
        info = tk.Frame(dht_panel, bg='#f1f7fd', padx=13, pady=15)
        info.pack(fill='x', pady=(0, 10))
        self.label(info, 'DHT11  ·  数据线 GPIO4', bg='#f1f7fd', color=BLUE, size=11, bold=True).pack(anchor='w')
        self.label(info, '每 2.5 秒采样；未连接或校验失败时显示离线。', bg='#f1f7fd', color=MUTED, size=9).pack(anchor='w', pady=(5, 0))
        self.label(info, '颜色：SDA GPIO9  /  SCL GPIO8', bg='#f1f7fd', color=MUTED, size=9).pack(anchor='w', pady=(5, 0))
        self.dht_chart = Chart(dht_panel, ('温度 °C', '湿度 %RH'), fixed_max=100)
        self.dht_chart.pack(fill='both', expand=True)
        log_frame = tk.Frame(body, bg='white', padx=14, pady=10)
        log_frame.pack(fill='x', pady=(13, 0))
        self.label(log_frame, '设备事件', size=10, bold=True).pack(anchor='w')
        self.logs = tk.Text(log_frame, height=4, bg='white', fg=MUTED, relief='flat', font=('DejaVu Sans Mono', 9), state='disabled', wrap='word')
        self.logs.pack(fill='x', pady=(5, 0))
        self.label(self.root, variable=self.foot, bg=BG, color=MUTED, size=9, anchor='w', padx=24, pady=10).pack(fill='x')

    def log(self, text):
        self.logs.configure(state='normal')
        self.logs.insert('end', time.strftime('%H:%M:%S')+'  '+text+'\n')
        if int(self.logs.index('end-1c').split('.')[0]) > 100:
            self.logs.delete('1.0', '20.0')
        self.logs.see('end'); self.logs.configure(state='disabled')

    def refresh_ports(self):
        ports = sorted(list_ports.comports(), key=lambda p: (p.vid != 0x1a86, p.device))
        self.combo['values'] = [p.device for p in ports]
        if not self.port.get() and ports:
            self.port.set(ports[0].device)

    def toggle(self):
        if self.reader:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        if self.reader or not self.port.get().strip():
            return
        self.token += 1
        self.total = 0
        self.values['count'].set('0')
        self.clear_live()
        self.color_chart.points.clear(); self.color_chart.draw()
        self.dht_chart.points.clear(); self.dht_chart.draw()
        self.reader = SerialReader(self.port.get().strip(), self.events, self.token)
        self.reader.start()
        self.connect_button.configure(text='断开连接')
        self.combo.configure(state='disabled')
        self.connection_text.set('正在连接…')

    def disconnect(self):
        if self.reader:
            self.token += 1
            self.reader.stop()
            self.reader = None
        self.connected = False
        self.clear_live()
        self.connection_text.set('未连接')
        self.connection_label.configure(fg=MUTED)
        self.connect_button.configure(text='连接设备')
        self.combo.configure(state='normal')
        self.log('串口已断开；实时读数已清除')

    def clear_live(self):
        self.last = {'color': None, 'dht': None}
        self.seen = {'color': 0., 'dht': 0.}
        self.led_state = None
        self.led_seen = 0.
        self.led_pending = None
        self.led_text.set('补光灯：未确认')
        self.rgb_controls.set_connected(False)
        self.servo_controls.set_connected(False)
        self.network_controls.set_connected(False)
        self.led_on_button.configure(state='disabled')
        self.led_off_button.configure(state='disabled')
        for key in ('temperature', 'humidity', 'clear', 'R', 'G', 'B', 'C'):
            self.values[key].set('—')
        self.swatch.configure(bg='#e2e8f0')
        for bar in self.bars.values():
            bar.delete('all')

    def set_led(self, on):
        if not self.connected or not self.reader or self.led_pending is not None:
            return
        if self.reader.send('LED ON' if on else 'LED OFF'):
            self.led_pending = (on, time.monotonic())
            self.led_text.set('补光灯：等待设备回执…')
            self.led_on_button.configure(state='disabled')
            self.led_off_button.configure(state='disabled')

    def toggle_csv(self):
        if self.recorder:
            self.stop_csv()
            return
        path = filedialog.asksaveasfilename(title='保存传感器记录', defaultextension='.csv', initialfile=time.strftime('sensors-%Y%m%d-%H%M%S.csv'), filetypes=[('CSV 文件', '*.csv')])
        if path:
            try:
                self.recorder = CsvRecorder(path)
                self.csv_text.set('停止 CSV 记录')
                self.log('开始记录：'+path)
            except OSError as exc:
                self.log('无法创建记录：'+str(exc))

    def stop_csv(self):
        if self.recorder:
            rows = self.recorder.rows
            self.recorder.close(); self.recorder = None
            self.csv_text.set('开始 CSV 记录')
            self.log(f'CSV 已保存，共 {rows} 行')

    def packet(self, obj):
        name, now = obj['type'], time.monotonic()
        if name in ('servo','wifi'):
            (self.servo_controls if name=='servo' else self.network_controls).handle_packet(obj)
            if self.recorder:
                try:self.recorder.write(obj)
                except OSError as exc:self.log('记录失败：'+str(exc));self.stop_csv()
            return
        if name == 'rgb':
            self.rgb_controls.handle_packet(obj)
            if self.recorder:
                try:self.recorder.write(obj)
                except OSError as exc:self.log('记录失败：'+str(exc));self.stop_csv()
            return
        if name == 'led':
            if self.recorder:
                try:
                    self.recorder.write(obj)
                except OSError as exc:
                    self.log('记录失败：'+str(exc)); self.stop_csv()
            changed = self.led_state is None or self.led_state != obj['on']
            self.led_state = obj['on']
            self.led_seen = now
            if self.led_pending is not None and self.led_pending[0] == obj['on']:
                self.led_pending = None
            if self.led_pending is None:
                self.led_text.set('补光灯：已开' if obj['on'] else '补光灯：已关')
            if changed:
                self.log('设备回执：补光灯' + ('开启' if obj['on'] else '关闭') + '（GPIO10）')
            return
        old = self.last[name]
        self.last[name], self.seen[name] = obj, now
        if self.recorder:
            try:
                self.recorder.write(obj)
            except OSError as exc:
                self.log('记录失败：'+str(exc)); self.stop_csv()
        if obj['status'] != 'ok':
            if not old or old.get('status') != 'error':
                self.log(('颜色' if name == 'color' else '温湿度')+'读取失败：'+obj.get('error', 'unknown'))
            return
        self.total += 1; self.values['count'].set(str(self.total))
        if name == 'dht':
            self.values['temperature'].set(f"{obj['temperature']:.1f}")
            self.values['humidity'].set(f"{obj['humidity']:.1f}")
            self.dht_chart.add(now, (obj['temperature'], obj['humidity']))
        else:
            self.values['clear'].set(str(obj['c']))
            maximum = max(obj[k] for k in ('r', 'g', 'b', 'c')) or 1
            for key in ('R', 'G', 'B', 'C'):
                value = obj[key.lower()]
                self.values[key].set(str(value))
                bar = self.bars[key]; bar.delete('all')
                bar.create_rectangle(0, 0, 130*value/maximum, 9, fill=COLORS[key], outline='')
            m = max(obj['r'], obj['g'], obj['b'])
            rgb = [round(255*obj[k]/m) if m else 0 for k in ('r', 'g', 'b')]
            self.swatch.configure(bg='#%02x%02x%02x' % tuple(rgb))
            self.color_chart.add(now, tuple(obj[k] for k in ('r', 'g', 'b', 'c')))

    def update_status(self):
        now = time.monotonic()
        self.rgb_controls.tick()
        self.servo_controls.tick()
        if self.led_pending is not None and now-self.led_pending[1] > 3:
            self.led_pending = None
            self.led_state = None
            self.led_text.set('补光灯：命令超时，状态未确认')
            self.log('补光灯未收到匹配回执，请检查串口后重试')
        elif self.connected and self.led_pending is None and now-self.led_seen > 5:
            self.led_state = None
            self.led_text.set('补光灯：未确认')
        can_control = self.connected and self.led_pending is None
        self.led_on_button.configure(state='normal' if can_control else 'disabled')
        self.led_off_button.configure(state='normal' if can_control else 'disabled')
        for name, textvar, ttl in (('color', self.color_text, 3), ('dht', self.dht_text, 8)):
            obj = self.last[name]
            healthy = self.connected and obj and obj['status'] == 'ok' and now-self.seen[name] < ttl
            if healthy:
                text = f"在线  ·  成功 {obj.get('ok', '—')} / 失败 {obj.get('fail', '—')}"
                if name == 'color':
                    text += f"  ·  ID 0x{obj.get('id', 0):02X}"
                    if obj.get('saturated'):
                        text += '  ·  光照饱和'
                textvar.set(text)
            else:
                reason = '未连接' if not self.connected else '等待数据' if not obj else '读取失败' if obj['status']=='error' else '数据超时'
                textvar.set(reason)
                for key in (('temperature', 'humidity') if name == 'dht' else ('clear', 'R', 'G', 'B', 'C')):
                    self.values[key].set('—')
                if name == 'color':
                    self.swatch.configure(bg='#e2e8f0')
                    for bar in self.bars.values():
                        bar.delete('all')
        if self.connected:
            csv = f'  ·  CSV {self.recorder.rows} 行' if self.recorder else ''
            self.foot.set(f'115200 baud  ·  本次连接 {int(now-self.connect_time)} 秒  ·  有效帧 {self.total}{csv}  ·  历史曲线保留最近120秒')

    def poll(self):
        for _ in range(300):
            try:
                token, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if token != self.token:
                continue
            if kind == 'connected':
                self.connected = True; self.connect_time = time.monotonic()
                self.connection_text.set('● 已连接'); self.connection_label.configure(fg='#15916a')
                self.log('串口连接成功：'+value)
                self.reader.send('LED STATUS')
                self.rgb_controls.set_connected(True)
                self.servo_controls.set_connected(True)
                self.network_controls.set_connected(True)
                self.reader.send("SERVO STATUS")
                self.reader.send("NET STATUS")
                self.reader.send('RGB STATUS')
            elif kind == 'packet':
                self.packet(value)
            elif kind == 'log':
                self.log(value)
            elif kind == 'error':
                self.log('串口错误：'+value)
                self.foot.set('连接失败或设备已拔出，请检查接线后重新连接。')
            elif kind == 'closed':
                self.disconnect()
        self.update_status()
        if self.state_file:
            import json
            from pathlib import Path
            snapshot = json.dumps(dict(connected=self.connected, frames=self.total, last=self.last, led_on=self.led_state, led_pending=self.led_pending, rgb=self.rgb_controls.actual, rgb_pending=self.rgb_controls.pending, servo=self.servo_controls.actual, servo_pending=self.servo_controls.pending, wifi=self.network_controls.actual, window_id=self.root.winfo_id()), ensure_ascii=False)
            if snapshot != self.state_snapshot:
                Path(self.state_file).write_text(snapshot)
                self.state_snapshot = snapshot
        self.poll_id = self.root.after(80, self.poll)

    def close(self):
        self.closing = True
        self.root.after_cancel(self.poll_id)
        self.disconnect()
        self.stop_csv()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port')
    parser.add_argument('--state-file', help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = tk.Tk()
    Dashboard(root, args.port, args.state_file)
    root.mainloop()


if __name__ == '__main__':
    main()
