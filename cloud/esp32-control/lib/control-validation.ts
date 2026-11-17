export type Json=Record<string,any>;
export function finite(x:unknown,min:number,max:number){return typeof x==='number'&&Number.isFinite(x)&&x>=min&&x<=max;}
export function validateControl(obj:Json,request:number):{kind:string,command:string,payload:Json}{
 const kind=obj.kind;
 if(kind==='led'){
  if(typeof obj.on!=='boolean')throw Error('补光灯状态必须为开或关');
  return {kind,command:obj.on?'LED ON':'LED OFF',payload:{on:obj.on}};
 }
 if(kind==='servo_stop')return {kind,command:`SERVO STOP ${request}`,payload:{}};
 if(kind==='rgb'){
  const {mode,frequency,brightness,colors}=obj;
  if(!['single','multi','rainbow','off'].includes(mode)||!finite(frequency,.05,2)||!Number.isInteger(brightness)||!finite(brightness,0,100)||!Array.isArray(colors)||colors.length<1||colors.length>8||colors.some((c:any)=>typeof c!=='string'||!/^#[0-9a-f]{6}$/i.test(c)))throw Error('RGB参数无效：频率0.05～2Hz，亮度0～100%，1～8色');
  const payload={mode,frequency,brightness,colors:colors.map((c:string)=>c.toUpperCase()),request};
  return {kind,command:'RGB SET '+JSON.stringify(payload),payload};
 }
 if(kind==='servo'){
  const {mode,enabled,target,low,high,period,speed,pwm_frequency,hold,delta}=obj;
  if(!['single','continuous'].includes(mode)||typeof enabled!=='boolean'||typeof hold!=='boolean'||!finite(target,0,180)||!finite(low,0,180)||!finite(high,0,180)||low>=high||!finite(period,2,60)||!finite(speed,5,180)||!Number.isInteger(pwm_frequency)||!finite(pwm_frequency,40,60)||(delta!==undefined&&(!finite(delta,-30,30)||Math.abs(delta)<.1)))throw Error('舵机参数无效：角度0～180°、PWM40～60Hz、周期2～60秒');
  const payload:Json={mode,enabled,target,low,high,period,speed,pwm_frequency,hold,request};if(delta!==undefined)payload.delta=delta;
  return {kind,command:'SERVO SET '+JSON.stringify(payload),payload};
 }
 throw Error('未知控制类型');
}
