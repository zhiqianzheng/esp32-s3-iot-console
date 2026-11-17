import {env} from 'cloudflare:workers';
import {validateControl} from '@/lib/control-validation';
export const dynamic='force-dynamic';
const json=(body:unknown,status=200,extra:Record<string,string>={})=>Response.json(body,{status,headers:{'Cache-Control':'no-store',...extra}});
const db=()=>{if(!env.DB)throw Error('Database unavailable');return env.DB;};
const hash=async(s:string)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))).map(n=>n.toString(16).padStart(2,'0')).join('');
async function equal(a:string,b:string){const x=await hash(a),y=await hash(b);let diff=0;for(let i=0;i<x.length;i++)diff|=x.charCodeAt(i)^y.charCodeAt(i);return diff===0;}
async function session(req:Request){const token=req.headers.get('Cookie')?.match(/(?:^|;\s*)esp_session=([a-f0-9]{64})/)?.[1];if(!token)return null;const h=await hash(token);return await db().prepare('SELECT hash FROM sessions WHERE hash=? AND expires_at>?').bind(h,Date.now()).first()?h:null;}
function sameOrigin(req:Request){return req.headers.get('Origin')===new URL(req.url).origin;}
async function body(req:Request){if(Number(req.headers.get('Content-Length')||0)>20000)throw Error('请求过大');const raw=await req.text();if(raw.length>20000)throw Error('请求过大');const o=JSON.parse(raw);if(!o||typeof o!=='object'||Array.isArray(o))throw Error('请求格式错误');return o;}
const randomToken=()=>Array.from(crypto.getRandomValues(new Uint8Array(32))).map(v=>v.toString(16).padStart(2,'0')).join('');
async function handler(req:Request){
 const path=new URL(req.url).pathname.replace(/^\/api\//,''),method=req.method,now=Date.now();
 const input=method==='POST'?await body(req):null;
 if(path==='session'&&method==='GET')return json({authenticated:!!await session(req)});
 if(path==='login'&&method==='POST'){
  if(!sameOrigin(req))return json({error:'跨站请求被拒绝'},403);
  const key=await hash(req.headers.get('CF-Connecting-IP')||'unknown');
  const attempt=await db().prepare('SELECT count,since FROM login_attempts WHERE key=?').bind(key).first<{count:number,since:number}>();
  if(attempt&&attempt.count>=8&&now-attempt.since<15*60000)return json({error:'尝试过于频繁，请15分钟后重试'},429);
  const o=input;
  if(typeof o.username!=='string'||typeof o.password!=='string'||!await equal(o.username,env.ADMIN_USERNAME)||!await equal(o.password,env.ADMIN_PASSWORD)){
   await db().prepare('INSERT INTO login_attempts(key,count,since) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN since<? THEN 1 ELSE count+1 END,since=CASE WHEN since<? THEN excluded.since ELSE since END').bind(key,now,now-900000,now-900000).run();
   return json({error:'账户或密码错误'},401);
  }
  const token=randomToken();await db().batch([db().prepare('DELETE FROM login_attempts WHERE key=?').bind(key),db().prepare('DELETE FROM sessions WHERE expires_at<?').bind(now),db().prepare('INSERT INTO sessions(hash,expires_at) VALUES(?,?)').bind(await hash(token),now+8*3600000)]);
  return json({ok:true},200,{'Set-Cookie':`esp_session=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800${new URL(req.url).protocol==='https:'?'; Secure':''}`});
 }
 if(path==='device/sync'&&method==='POST'){
  const token=req.headers.get('Authorization')?.replace(/^Bearer /,'')||'';
  if(!token||!await equal(token,env.DEVICE_KEY))return json({error:'Unauthorized device'},401);
  const o=input;
  if(o.device_id!==env.DEVICE_ID||typeof o.boot_id!=='string'||o.boot_id.length>64||typeof o.states!=='object'||!Number.isFinite(o.uptime))return json({error:'Invalid device payload'},400);
  const existing=await db().prepare('SELECT boot_id,last_seen,control_until,lease_owner FROM devices WHERE id=?').bind(o.device_id).first<any>();
  if(existing&&existing.boot_id!==o.boot_id)await db().batch([db().prepare("UPDATE commands SET status='expired' WHERE device_id=? AND status IN ('pending','sent')").bind(o.device_id),db().prepare('UPDATE devices SET control_until=0,lease_owner=NULL WHERE id=?').bind(o.device_id)]);
  await db().prepare('INSERT INTO devices(id,boot_id,last_seen,states,uptime,control_until) VALUES(?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET boot_id=excluded.boot_id,last_seen=excluded.last_seen,states=excluded.states,uptime=excluded.uptime').bind(o.device_id,o.boot_id,now,JSON.stringify(o.states),o.uptime).run();
  const recent=await db().prepare('SELECT ts FROM telemetry WHERE device_id=? ORDER BY ts DESC LIMIT 1').bind(o.device_id).first<{ts:number}>();
  if(!recent||now-recent.ts>=5000)await db().batch([db().prepare('INSERT INTO telemetry(device_id,ts,states) VALUES(?,?,?)').bind(o.device_id,now,JSON.stringify(o.states)),db().prepare('DELETE FROM telemetry WHERE id IN (SELECT id FROM telemetry WHERE device_id=? AND ts<? LIMIT 100)').bind(o.device_id,now-6*3600000)]);
  for(const ack of (Array.isArray(o.acks)?o.acks:[]).slice(0,12)){
   if(Number.isInteger(ack.id))await db().prepare("UPDATE commands SET status=?,ack=? WHERE id=? AND device_id=? AND boot_id=? AND status IN ('pending','sent')").bind(ack.ok?'ack':'error',JSON.stringify(ack).slice(0,4000),ack.id,o.device_id,o.boot_id).run();
  }
  await db().prepare("UPDATE commands SET status='expired' WHERE device_id=? AND expires_at<? AND status IN ('pending','sent')").bind(o.device_id,now).run();
  const pending=await db().prepare("SELECT id,kind,payload,request,expires_at FROM commands WHERE device_id=? AND boot_id=? AND status IN ('pending','sent') AND expires_at>? ORDER BY CASE WHEN kind='servo_stop' THEN 0 ELSE 1 END,id LIMIT 6").bind(o.device_id,o.boot_id,now).all<any>();
  if(pending.results.length)await db().batch(pending.results.map(c=>db().prepare("UPDATE commands SET status='sent' WHERE id=? AND status='pending'").bind(c.id)));
  const lease=await db().prepare('SELECT control_until FROM devices WHERE id=?').bind(o.device_id).first<{control_until:number}>();
  return json({ok:true,commands:pending.results.map(c=>({id:c.id,kind:c.kind,command:c.payload,request:c.request,expires_at:c.expires_at})),servo_keepalive:!!lease&&lease.control_until>now,server_time:now});
 }
 const user=await session(req);if(!user)return json({error:'请先登录'},401);
 if(method==='POST'&&!sameOrigin(req))return json({error:'跨站请求被拒绝'},403);
 if(path==='logout'&&method==='POST'){await db().prepare('DELETE FROM sessions WHERE hash=?').bind(user).run();return json({ok:true},200,{'Set-Cookie':'esp_session=; HttpOnly; SameSite=Strict; Secure; Path=/; Max-Age=0'});}
 if(path==='snapshot'&&method==='GET'){
  const row=await db().prepare('SELECT * FROM devices WHERE id=?').bind(env.DEVICE_ID).first<any>();
  const history=await db().prepare('SELECT ts,states FROM telemetry WHERE device_id=? ORDER BY ts DESC LIMIT 240').bind(env.DEVICE_ID).all<any>();
  const commands=await db().prepare('SELECT id,kind,status,created_at,expires_at,ack FROM commands WHERE device_id=? ORDER BY id DESC LIMIT 20').bind(env.DEVICE_ID).all<any>();
  return json({device:row?{...row,states:JSON.parse(row.states),online:now-row.last_seen<10000}:null,history:history.results.reverse().map(p=>({ts:p.ts,states:JSON.parse(p.states)})),commands:commands.results.map(c=>({...c,ack:c.ack?JSON.parse(c.ack):null})),server_time:now,device_id:env.DEVICE_ID});
 }
 if(path==='command'&&method==='POST'){
  const o=input,device=await db().prepare('SELECT boot_id,last_seen FROM devices WHERE id=?').bind(env.DEVICE_ID).first<any>();
  if(!device)return json({error:'设备尚未连接'},409);
  if(now-device.last_seen>10000&&o.kind!=='servo_stop')return json({error:'设备离线，不会排队执行动作'},409);
  const request=crypto.getRandomValues(new Uint32Array(1))[0]&0x7fffffff;
  let c;try{c=validateControl(o,request);}catch(e){return json({error:(e as Error).message},400);}
  if(c.kind==='servo'||c.kind==='servo_stop')await db().prepare("UPDATE commands SET status='superseded' WHERE device_id=? AND kind IN ('servo','servo_stop') AND status IN ('pending','sent')").bind(env.DEVICE_ID).run();
  const result=await db().prepare('INSERT INTO commands(device_id,boot_id,kind,payload,request,status,created_at,expires_at) VALUES(?,?,?,?,?,\'pending\',?,?)').bind(env.DEVICE_ID,device.boot_id,c.kind,c.command,request,now,now+(c.kind==='servo_stop'?30000:15000)).run();
  if(c.kind==='servo')await db().prepare('UPDATE devices SET control_until=?,lease_owner=? WHERE id=?').bind(now+6000,user,env.DEVICE_ID).run();
  if(c.kind==='servo_stop')await db().prepare('UPDATE devices SET control_until=0,lease_owner=NULL WHERE id=?').bind(env.DEVICE_ID).run();
  return json({ok:true,id:result.meta.last_row_id,request});
 }
 if(path==='control/heartbeat'&&method==='POST'){
  await db().prepare('UPDATE devices SET control_until=? WHERE id=? AND lease_owner=?').bind(now+6000,env.DEVICE_ID,user).run();return json({ok:true});
 }
 return json({error:'Not found'},404);
}
export async function GET(req:Request){try{return await handler(req);}catch(e){console.error('API GET failed',(e as Error).message);return json({error:'服务暂不可用'},500);}}
export async function POST(req:Request){try{return await handler(req);}catch(e){console.error('API POST failed',(e as Error).message);return json({error:'请求失败，请检查格式或稍后重试'},400);}}
