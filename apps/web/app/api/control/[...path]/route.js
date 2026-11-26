// Fixed upstream, no user-supplied origin. Forward only contract resource paths.
export const dynamic="force-dynamic";
export const runtime="nodejs";
async function proxy(request,{params}){
 const {path}=await params;
 if(!Array.isArray(path)||path.some(p=>!/^[-_a-zA-Z0-9]+$/.test(p))||!((path[0]==="api"&&path[1]==="v1")||(path[0]==="health"&&path.length===2)))return new Response("Not found",{status:404});
 const url=new URL("/"+path.join("/"),process.env.SWARMFORGE_API_URL||"http://127.0.0.1:8000");
 url.search=new URL(request.url).search;
 const headers=new Headers();
 for(const k of ["authorization","content-type","idempotency-key","last-event-id","accept","x-approval-secret"]){const v=request.headers.get(k);if(v)headers.set(k,v)}
 let body;
 if(request.method==="POST"){
  const reader=request.body?.getReader();let length=0;const chunks=[];
  if(reader){try{while(true){const {done,value}=await reader.read();if(done)break;length+=value.byteLength;if(length>262144){await reader.cancel();return new Response("Request too large",{status:413})}chunks.push(value)}}finally{reader.releaseLock()}}
  body=Buffer.concat(chunks);
 }
 try{
  const upstream=await fetch(url,{method:request.method,headers,body,signal:request.signal,cache:"no-store",redirect:"manual"});
  const out=new Headers({"Cache-Control":"no-store"});
  for(const k of ["content-type","content-disposition","www-authenticate","x-request-id","x-accel-buffering"]){const v=upstream.headers.get(k);if(v)out.set(k,v)}
  return new Response(upstream.body,{status:upstream.status,headers:out});
 }catch{return Response.json({code:"unavailable",message:"Control plane unavailable"},{status:503})}
}
export const GET=proxy;
export const POST=proxy;
