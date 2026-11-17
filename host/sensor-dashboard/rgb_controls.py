"""Board WS2812 controls; independent from the color-module white LED."""
import time
import tkinter as tk
from tkinter import ttk, colorchooser
from core import build_rgb_command

MODES = {'单色呼吸': 'single', '多色渐变呼吸': 'multi', '彩虹呼吸': 'rainbow', '关闭': 'off'}
DEFAULT_COLORS = ['#FF1E3C', '#FF8C00', '#FFDC00', '#00E682', '#1E78FF', '#B428FF']


class RGBControls(tk.Frame):
    def __init__(self, parent, sender):
        super().__init__(parent, bg='white', padx=15, pady=10)
        self.sender = sender
        self.connected = False
        self.pending = None
        self.actual = None
        self.seen = 0
        self.synced = False
        self.palette = DEFAULT_COLORS.copy()
        self.mode = tk.StringVar(value='多色渐变呼吸')
        self.frequency = tk.StringVar(value='0.25')
        self.brightness = tk.IntVar(value=35)
        self.period = tk.StringVar(value='周期 4.00 秒')
        self.status = tk.StringVar(value='未连接 · 等待设备状态')
        self.mode_text = tk.StringVar(value='点击色块修改颜色；多色模式按顺序平滑循环')
        tk.Label(self, text='板载 RGB 呼吸灯  ·  GPIO48', bg='white', fg='#172b4d', font=('Noto Sans CJK SC', 12, 'bold')).pack(anchor='w')
        row = tk.Frame(self, bg='white'); row.pack(fill='x', pady=(7, 4))
        ttk.Combobox(row, values=list(MODES), textvariable=self.mode, width=15, state='readonly').pack(side='left', padx=(0, 12))
        tk.Label(row, text='频率 Hz', bg='white').pack(side='left')
        self.freq_spin = ttk.Spinbox(row, from_=.05, to=2, increment=.05, textvariable=self.frequency, width=7)
        self.freq_spin.pack(side='left', padx=6)
        tk.Label(row, textvariable=self.period, bg='white', fg='#64748b', width=15, anchor='w').pack(side='left')
        tk.Label(row, text='峰值亮度 %', bg='white').pack(side='left')
        self.bright_spin = ttk.Spinbox(row, from_=0, to=100, increment=5, textvariable=self.brightness, width=5)
        self.bright_spin.pack(side='left', padx=6)
        self.apply_button = ttk.Button(row, text='应用到开发板', command=self.apply, state='disabled')
        self.apply_button.pack(side='right')
        self.stop_button = ttk.Button(row, text='关闭彩灯', command=lambda:self.apply('off'), state='disabled')
        self.stop_button.pack(side='right', padx=6)
        row2 = tk.Frame(self, bg='white'); row2.pack(fill='x')
        self.chips = tk.Frame(row2, bg='white'); self.chips.pack(side='left')
        ttk.Button(row2, text='＋颜色', command=self.add_color).pack(side='left', padx=5)
        ttk.Button(row2, text='−末色', command=self.remove_color).pack(side='left')
        tk.Label(row2, text='单色使用第1色；多色最多8色', bg='white', fg='#64748b', font=('Noto Sans CJK SC', 9)).pack(side='left', padx=12)
        self.state_label = tk.Label(self, textvariable=self.status, bg='white', fg='#2563eb', anchor='w', font=('Noto Sans CJK SC', 9))
        self.state_label.pack(fill='x', pady=(6, 0))
        self.frequency.trace_add('write', lambda *_:self.update_period())
        self.draw_palette()

    def update_period(self):
        try:
            f=float(self.frequency.get())
            self.period.set(f'周期 {1/f:.2f} 秒' if .05 <= f <= 2 else '范围 0.05～2 Hz')
        except (ValueError, ZeroDivisionError):
            self.period.set('请输入有效频率')

    def draw_palette(self):
        for child in self.chips.winfo_children(): child.destroy()
        for i, color in enumerate(self.palette):
            value=int(color[1:3],16)*.299+int(color[3:5],16)*.587+int(color[5:7],16)*.114
            tk.Button(self.chips, text=str(i+1), bg=color, fg='black' if value > 150 else 'white', width=3, relief='flat', command=lambda idx=i:self.choose_color(idx)).pack(side='left', padx=(0, 5))

    def choose_color(self, index):
        _, color=colorchooser.askcolor(self.palette[index], title=f'选择第{index+1}种颜色', parent=self)
        if color:
            self.palette[index]=color.upper();self.draw_palette()

    def add_color(self):
        if len(self.palette)<8:
            _, color=colorchooser.askcolor('#FFFFFF', title='添加渐变颜色', parent=self)
            if color:self.palette.append(color.upper());self.draw_palette()
        else:self.status.set('最多支持8种颜色')

    def remove_color(self):
        if len(self.palette)>1:self.palette.pop();self.draw_palette()
        else:self.status.set('至少保留1种颜色')

    def set_connected(self, connected):
        if self.connected != connected:
            self.connected=connected;self.pending=None;self.actual=None;self.synced=False;self.seen=0
            self.status.set('等待开发板 RGB 状态' if connected else '未连接 · 状态未确认')
        self.update_buttons()

    def update_buttons(self):
        state='normal' if self.connected and self.pending is None else 'disabled'
        self.apply_button.configure(state=state);self.stop_button.configure(state=state)

    def apply(self, mode_override=None):
        if not self.connected or self.pending is not None:return
        try:
            config=dict(mode=mode_override or MODES[self.mode.get()], frequency=float(self.frequency.get()), brightness=self.brightness.get(), colors=self.palette.copy(), request=time.monotonic_ns()%2147483647)
            command=build_rgb_command(config)
        except (ValueError, tk.TclError, KeyError) as exc:
            self.status.set('设置无效：频率0.05～2Hz，亮度0～100%，颜色1～8种');return
        if self.sender(command):
            self.pending=(config,time.monotonic())
            self.status.set('正在发送，等待开发板确认…');self.update_buttons()
        else:self.status.set('发送失败，请检查串口连接')

    def handle_packet(self, obj):
        now=time.monotonic()
        if obj['status']=='error':
            if self.pending and obj.get('request')==self.pending[0]['request']:
                self.pending=None;self.status.set('设备拒绝设置：'+obj.get('error','unknown'));self.update_buttons()
            return
        self.actual=obj;self.seen=now
        matched=self.pending and obj['request']==self.pending[0]['request']
        if matched:self.pending=None
        if matched or not self.synced:
            self.mode.set(next(label for label,code in MODES.items() if code==obj['mode']))
            self.frequency.set(f"{obj['frequency']:.3f}".rstrip('0').rstrip('.'))
            self.brightness.set(obj['brightness']);self.palette=obj['colors'].copy();self.draw_palette();self.synced=True
        if self.pending is None:
            label=next(label for label,code in MODES.items() if code==obj['mode'])
            self.status.set(f"设备已确认：{label} · {obj['frequency']:.2f} Hz · 周期 {1/obj['frequency']:.2f} 秒 · 峰值 {obj['brightness']}%")
        self.update_buttons()

    def tick(self):
        now=time.monotonic()
        if self.pending and now-self.pending[1]>4:
            self.pending=None;self.status.set('命令超时，未确认生效；请重试');self.update_buttons()
        elif self.connected and self.pending is None and self.synced and now-self.seen>6:
            self.status.set('设备 RGB 状态超时，最后设置尚未重新确认')
