#!/usr/bin/env python3
"""LAN TLS gateway for ESP32, forwarding exclusively to this project's cloud API.
No telemetry is fabricated; all data and acknowledgements originate on the board.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import threading
import urllib.error
import urllib.request

CLOUD='https://console.example.com'
TLS=Path.home()/'.local/share/esp32-wifi-gateway'
slots=threading.BoundedSemaphore(8)
class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass  # Never log authorization headers or request bodies.
    def setup(self):
        super().setup();self.connection.settimeout(12)
    def reply(self,status,body):
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers();self.wfile.write(body);self.close_connection=True
    def do_GET(self):
        self.reply(200 if self.path=='/health' else 404,b'{"service":"esp32-wifi-gateway","transport":"tls"}')
    def do_POST(self):
        if self.path!='/api/device/sync':self.reply(404,b'{"error":"Not found"}');return
        auth=self.headers.get('Authorization','')
        if not auth.startswith('Bearer ') or len(auth)>150:self.reply(401,b'{"error":"Device authentication required"}');return
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:length=0
        if not 0<length<=20000:self.reply(413,b'{"error":"Invalid payload size"}');return
        if not slots.acquire(blocking=False):self.reply(503,b'{"error":"Gateway busy"}');return
        try:
            payload=self.rfile.read(length)
            if len(payload)!=length:raise ValueError('incomplete request')
            obj=json.loads(payload)
            if not isinstance(obj,dict) or obj.get('device_id')!='esp32-demo':self.reply(400,b'{"error":"Unknown device"}');return
            # Actual cloud API verifies the device key. The gateway stores no key.
            req=urllib.request.Request(CLOUD+self.path,data=payload,headers={'Authorization':auth,'Content-Type':'application/json','User-Agent':'Mozilla/5.0 (compatible; ESP32WiFiGateway/1.0)'})
            try:response=urllib.request.urlopen(req,timeout=5)
            except urllib.error.HTTPError as err:response=err
            with response:
                body=response.read(16000);status=response.status
            self.reply(status,body)
        except (OSError,ValueError,urllib.error.URLError):
            try:self.reply(502,b'{"error":"Gateway could not reach cloud"}')
            except OSError:pass
        finally:slots.release()

if __name__=='__main__':
    server=ThreadingHTTPServer(('0.0.0.0',8743),Handler);server.daemon_threads=True
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2;ctx.load_cert_chain(TLS/'server-cert.pem',TLS/'server-key.pem');server.socket=ctx.wrap_socket(server.socket,server_side=True)
    print('ESP32 TLS Wi-Fi gateway listening on LAN port 8743; destination fixed to project cloud.',flush=True)
    server.serve_forever(poll_interval=.5)
