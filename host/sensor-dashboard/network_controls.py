import json
import tkinter as tk
from tkinter import ttk
class NetworkControls(tk.Frame):
    def __init__(self,parent,sender):
        super().__init__(parent,bg='white',padx=15,pady=10);self.sender=sender;self.connected=False;self.actual=None
        self.ssid=tk.StringVar(value='');self.password=tk.StringVar();self.status=tk.StringVar(value='等待设备联网状态')
        tk.Label(self,text='Wi-Fi 与云端连接',bg='white',font=('Noto Sans CJK SC',12,'bold'),fg='#172b4d').pack(anchor='w')
        row=tk.Frame(self,bg='white');row.pack(fill='x',pady=12)
        tk.Label(row,text='2.4GHz Wi-Fi 名称',bg='white').pack(side='left');ttk.Entry(row,textvariable=self.ssid,width=25).pack(side='left',padx=8)
        tk.Label(row,text='Wi-Fi 密码',bg='white').pack(side='left');ttk.Entry(row,textvariable=self.password,show='•',width=25).pack(side='left',padx=8)
        self.save=ttk.Button(row,text='保存Wi-Fi并重启',command=self.apply,state='disabled');self.save.pack(side='left',padx=8)
        tk.Label(self,textvariable=self.status,bg='white',fg='#2563eb',font=('Noto Sans CJK SC',10),anchor='w').pack(fill='x',pady=6)
        tk.Label(self,text='当前云端连接经本机TLS Wi-Fi网关，电脑需保持开机联网。ESP32仅支持2.4GHz；密码经USB保存到设备。',bg='white',fg='#64748b',font=('Noto Sans CJK SC',9),anchor='w').pack(fill='x')
    def set_connected(self,value):self.connected=value;self.save.configure(state='normal' if value else 'disabled')
    def apply(self):
        s,p=self.ssid.get(),self.password.get()
        if not 1<=len(s.encode())<=32 or len(p.encode())>64:self.status.set('Wi-Fi名称或密码长度无效');return
        if self.connected and self.sender('NET WIFI '+json.dumps(dict(ssid=s,password=p),separators=(',',':'),ensure_ascii=False)):
            self.password.set('');self.status.set('正在保存网络配置，设备随后重启…')
    def handle_packet(self,o):
        self.actual=o
        names={'online':'云端已连接','connecting':'正在连接Wi-Fi','time_sync':'正在同步时间','cloud_error':'云端连接异常','unconfigured':'设备尚未配置云端','saved':'配置已保存，正在重启','config_error':'配置失败','configured':'已保存联网配置'}
        self.status.set(names.get(o.get('state'),o.get('state','未知'))+f" · 信号 {o.get('rssi',0)} dBm"+((' · '+o['error']) if o.get('error') else ''))
