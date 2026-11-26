"use client";
import {createContext,useContext,useState,useEffect} from "react";
import Link from "next/link";
import {usePathname} from "next/navigation";
import {request} from "../lib/client.mjs";
const Context=createContext(null);
export const useSession=()=>useContext(Context);
export function Mark(){return <span className="mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M16 2 29 9v14l-13 7L3 23V9Z M3 9l13 7 13-7M16 16v14M9 6l13 7v7" fill="none" stroke="currentColor" strokeWidth="1.8"/></svg></span>}
export function Shell({children}){
 const [token,setToken]=useState(""),[me,setMe]=useState(null),[wid,setWid]=useState(""),[input,setInput]=useState(""),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 const path=usePathname();const home=path==="/";
 async function connect(e){e.preventDefault();setBusy(true);setError("");try{const m=await request(input.trim(),"/api/v1/me");setToken(input.trim());setInput("");setMe(m);setWid(m.workspaces[0]?.id||"")}catch(e){setError(e.message)}finally{setBusy(false)}}
 function signout(){setToken("");setMe(null);setWid("");setInput("")}
 const ws=me?.workspaces.find(x=>x.id===wid);
 return <Context.Provider value={{token,me,wid,ws,prefix:"/api/v1/workspaces/"+wid,editor:ws?.role==="owner"||ws?.role==="editor",signout}}>
 {home?<>{children}</>:<div className="app-shell">
 <aside className="sidebar"><Link href="/" className="brand"><Mark/><span>SWARMFORGE<small>RELIABILITY SYSTEMS</small></span></Link><div className="side-label">WORKSPACE</div>{me&&<label className="workspace-select"><span className="sr-only">Workspace</span><select value={wid} onChange={e=>setWid(e.target.value)}>{me.workspaces.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label>}<div className="side-label">LABORATORY</div>{[["/lab","▦","Control center"],["/lab/scenarios/new","◇","Scenario studio"],["/benchmarks","≋","Benchmark center"],["/agent","◇","Agent console"],["/settings","⚙","Settings"]].map(([href,icon,name])=><Link key={href} className={"nav "+(path===href?"active":"")} href={href}><span aria-hidden="true">{icon}</span>{name}</Link>)}<div className="side-bottom"><span className="dot"/> SIMULATION ONLY<p>Research environment<br/>No physical robot control.</p></div></aside>
 <div className="main-area"><header className="topbar"><span><span className="dot"/> RESEARCH LAB <span className="muted"> / </span> R6</span>{me?<div className="top-right"><span>{me.display_name||"Engineer"} · {ws?.role||"No workspace"}</span><button className="ghost" onClick={signout}>Disconnect</button></div>:<span className="muted">Not connected</span>}</header>
 <main className="content">{!token?<section className="login panel"><div className="eyebrow">AUTHORIZED ACCESS</div><h1>Connect to your lab.</h1><p>Enter a configured bearer access token. It is kept only in memory and discarded on reload or disconnect.</p><form onSubmit={connect}><label>Access token<input type="password" autoComplete="off" value={input} onChange={e=>setInput(e.target.value)} required/></label><button disabled={busy}>{busy?"Connecting…":"Connect workspace"}</button></form>{error&&<p role="alert" className="error">{error}</p>}<p className="muted small">Local setup: seed the workspace using the documented CLI. Never share your token.</p></section>:!wid?<p role="status">No workspace membership. Ask an administrator to provision access.</p>:<div key={wid}>{children}</div>}</main></div></div>}
 </Context.Provider>
}
