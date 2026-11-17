import time
import tkinter as tk
from tkinter import ttk
from core import build_servo_command

DEFAULTS=dict(mode='single',enabled=True,target=90.,low=60.,high=120.,period=4.,speed=60.,pwm_frequency=50,hold=True)
class ServoControls(tk.Frame):
    def __init__(self,parent,sender):
        super().__init__(parent,bg='white',padx=15,pady=10)
        self.sender=sender;self.connected=False;self.actual=None;self.pending=None;self.synced=False;self.seen=0;self.ping_at=0
        self.mode=tk.StringVar(value='单次定位');self.hold=tk.BooleanVar(value=True)
        self.vars={k:tk.StringVar(value=str(v)) for k,v in DEFAULTS.items() if k not in ('mode','enabled','hold')}
        self.step=tk.StringVar(value='5');self.status=tk.StringVar(value='未连接 · PWM状态未确认')
        tk.Label(self,text='舵机控制 · GPIO14',bg='white',fg='#172b4d',font=('Noto Sans CJK SC',12,'bold')).pack(anchor='w')
        row=tk.Frame(self,bg='white');row.pack(fill='x',pady=(7,5))
        ttk.Combobox(row,textvariable=self.mode,values=['单次定位','持续往返'],state='readonly',width=12).pack(side='left',padx=(0,8))
        for title,key,lo,hi in [('目标角度°','target',0,180),('PWM Hz','pwm_frequency',40,60),('单次速度°/s','speed',5,180)]:
            tk.Label(row,text=title,bg='white').pack(side='left',padx=(7,3));ttk.Spinbox(row,textvariable=self.vars[key],from_=lo,to=hi,width=6).pack(side='left')
        self.stop_button=ttk.Button(row,text='停止输出',command=self.stop,state='disabled');self.stop_button.pack(side='right')
        self.run_button=ttk.Button(row,text='启用并执行',command=self.apply,state='disabled');self.run_button.pack(side='right',padx=7)
        row2=tk.Frame(self,bg='white');row2.pack(fill='x',pady=3)
        for title,key,lo,hi in [('往返下限°','low',0,180),('上限°','high',0,180),('往返周期秒','period',2,60)]:
            tk.Label(row2,text=title,bg='white').pack(side='left',padx=(0,3));ttk.Spinbox(row2,textvariable=self.vars[key],from_=lo,to=hi,width=6).pack(side='left',padx=(0,10))
        tk.Label(row2,text='单步角度°',bg='white').pack(side='left');ttk.Spinbox(row2,textvariable=self.step,from_=.1,to=30,increment=.5,width=5).pack(side='left',padx=5)
        self.minus=ttk.Button(row2,text='单步 −',command=lambda:self.apply(-1),state='disabled');self.minus.pack(side='left',padx=3)
        self.plus=ttk.Button(row2,text='单步 ＋',command=lambda:self.apply(1),state='disabled');self.plus.pack(side='left',padx=3)
        ttk.Checkbutton(row2,text='单次到位后保持',variable=self.hold).pack(side='right')
        tk.Label(self,textvariable=self.status,bg='white',fg='#2563eb',font=('Noto Sans CJK SC',10),anchor='w').pack(fill='x',pady=(5,2))
        tk.Label(self,text='显示为指令角度，非实测位置；PWM默认50Hz。通信中断5秒自动停止输出，停止不等于切断电源。',bg='white',fg='#64748b',font=('Noto Sans CJK SC',9),anchor='w').pack(fill='x')
    def update_buttons(self):
        self.stop_button.configure(state='normal' if self.connected else 'disabled')
        for button in (self.run_button,self.minus,self.plus):button.configure(state='normal' if self.connected and self.pending is None else 'disabled')
    def set_connected(self,connected):
        if self.connected!=connected:
            self.connected=connected;self.actual=None;self.pending=None;self.synced=False;self.seen=0;self.status.set('等待设备舵机状态' if connected else '未连接 · 输出状态未确认')
        self.update_buttons()
    def apply(self,direction=None):
        if not self.connected or self.pending is not None:return
        try:
            c={k:float(v.get()) for k,v in self.vars.items()};f=c['pwm_frequency']
            if not f.is_integer():raise ValueError()
            c['pwm_frequency']=int(f);c.update(mode='continuous' if self.mode.get()=='持续往返' else 'single',enabled=True,hold=self.hold.get(),request=time.monotonic_ns()%2147483647)
            if direction is not None:c['delta']=direction*float(self.step.get());c['mode']='single'
            command=build_servo_command(c)
        except (ValueError,tk.TclError):self.status.set('参数无效：角度0～180°，下限小于上限，PWM40～60Hz，周期2～60秒，单步0.1～30°');return
        if self.sender(command):self.pending=(c['request'],time.monotonic());self.status.set('等待舵机控制回执…');self.update_buttons()
    def stop(self):
        if not self.connected:return
        rid=time.monotonic_ns()%2147483647
        if self.sender(f'SERVO STOP {rid}'):self.pending=(rid,time.monotonic());self.status.set('正在停止输出…');self.update_buttons()
    def handle_packet(self,o):
        if o['status']=='error':
            if self.pending and self.pending[0]==o['request']:self.pending=None;self.status.set('设备拒绝设置：'+o['error']);self.update_buttons()
            return
        self.actual=o;self.seen=time.monotonic()
        matched=self.pending and self.pending[0]==o['request'] and o['applied']
        if matched:self.pending=None
        if (matched or not self.synced) and o['applied']:
            for k,v in self.vars.items():v.set(str(o[k]))
            self.mode.set('持续往返' if o['mode']=='continuous' else '单次定位');self.hold.set(o['hold']);self.synced=True
        if self.pending is None:
            state='运行中' if o['moving'] else '保持位置' if o['enabled'] else 'PWM已停止'
            if o.get('link_timeout'):state='通信超时，PWM已停止'
            owner='云端' if o.get('owner')=='cloud' else '本地'
            self.status.set(f"{state} · 指令角度 {o['angle']:.1f}° · {o['pwm_frequency']}Hz · 脉宽 {o['pulse_us']}µs · 控制来源 {owner}")
        self.update_buttons()
    def tick(self):
        now=time.monotonic()
        if self.connected and now-self.ping_at>=1:
            self.sender('SERVO PING');self.ping_at=now
        if self.pending and now-self.pending[1]>4:self.pending=None;self.status.set('命令未确认，请重试；可随时点击停止输出');self.update_buttons()
        elif self.connected and self.synced and now-self.seen>3:self.status.set('舵机状态超时，当前角度/输出状态未确认')
