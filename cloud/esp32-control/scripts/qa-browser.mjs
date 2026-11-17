import fs from 'node:fs/promises';
const config=Object.fromEntries((await fs.readFile(new URL('../.dev.vars',import.meta.url),'utf8')).trim().split('\n').map(l=>{const i=l.indexOf('=');return [l.slice(0,i),l.slice(i+1).replace(/^"|"$/g,'')]}));
const tabs=await (await fetch('http://127.0.0.1:9333/json')).json();const tab=tabs.find(t=>t.type==='page');
const ws=new WebSocket(tab.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let seq=0;const pending=new Map();const errors=[];
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);});
function send(method,params={}){return new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
await send('Runtime.enable');await send('Page.enable');await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});await send('Page.navigate',{url:'http://127.0.0.1:4173'});await sleep(1400);
await send('Runtime.evaluate',{expression:`(()=>{const i=document.querySelector('input[type=password]');if(!i)throw Error('Login form missing');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,${JSON.stringify(config.ADMIN_PASSWORD)});i.dispatchEvent(new Event('input',{bubbles:true}));})()`});await sleep(100);
await send('Runtime.evaluate',{expression:"document.querySelector('form').requestSubmit()"});await sleep(2200);
const check=await send('Runtime.evaluate',{expression:"document.body.innerText.includes('传感器与远程控制')",returnByValue:true});if(!check.result.value)throw Error('Dashboard login did not succeed');
await fs.writeFile('logs/cloud-desktop-preview.png',Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true})).data,'base64'));
await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await sleep(300);
const overflow=await send('Runtime.evaluate',{expression:'document.documentElement.scrollWidth > innerWidth+2',returnByValue:true});if(overflow.result.value)throw Error('Mobile layout overflows');
await fs.writeFile('logs/cloud-mobile-preview.png',Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true})).data,'base64'));
if(errors.length)throw Error(errors.join(';'));console.log('Browser QA passed: rendered login, authenticated dashboard, desktop and mobile layout; no runtime exceptions.');ws.close();
