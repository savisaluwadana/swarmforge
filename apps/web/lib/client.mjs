import {decodeFrame} from "./model.mjs";
export async function request(token,path,{method="GET",body,key,signal,raw=false}={}){
 const headers={Authorization:"Bearer "+token};
 if(body!==undefined)headers["Content-Type"]="application/json";
 if(key)headers["Idempotency-Key"]=key;
 const r=await fetch("/api/control"+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),signal,cache:"no-store"});
 if(!r.ok){const j=await r.json().catch(()=>({}));const e=Error(j.message||"Request failed ("+r.status+")");e.status=r.status;throw e}
 return raw?r:r.json();
}
export async function stream(token,path,cursor,signal,onEvent){
 const r=await request(token,path+"?after_seq="+cursor,{signal,raw:true});
 const reader=r.body.getReader(),decoder=new TextDecoder();let buf="";
 try{while(true){const {value,done}=await reader.read();if(done)break;buf+=decoder.decode(value,{stream:true});if(buf.length>2000000)throw Error("Stream frame too large");let i;while((i=buf.indexOf("\n\n"))>=0){const frame=decodeFrame(buf.slice(0,i));buf=buf.slice(i+2);if(frame){if(frame.type==="stream.closed")return;onEvent(frame.data)}}}}finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
}
export async function download(token,path,name){const r=await request(token,path,{raw:true});const url=URL.createObjectURL(await r.blob());const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
