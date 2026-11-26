export const POLICIES=["centralized_greedy","local_auction","scoped_lease"];
export const LABELS={centralized_greedy:"Centralized greedy",local_auction:"Peer auction",scoped_lease:"Scoped lease"};
export const terminal=s=>["succeeded","failed","cancelled"].includes(s);
export function preset(kind="warehouse"){
 const robots=Array.from({length:10},(_,i)=>({id:"r"+String(i).padStart(2,"0"),start:{x:i<5?2:14,y:2+2*(i%5)},zone:i<5?"west":"east"}));
 const tasks=Array.from({length:20},(_,i)=>({id:"t"+String(i).padStart(2,"0"),pickup:{x:i%2===0?1:13,y:1+2*(i%5)},dropoff:{x:i%2===0?4:16,y:1+2*(i%5)},release_tick:i*3,priority:3,due_tick:i*3+35}));
 return {schema_version:1,width:24,height:12,obstacles:[2,4,6,8,10].map(y=>({x:6,y})),robots,zones:[{id:"west",min_x:0,max_x:11,min_y:0,max_y:11,leader:"r00"},{id:"east",min_x:12,max_x:23,min_y:0,max_y:11,leader:"r05"}],tasks,network:{default_delay_ticks:1,default_drop_rate:0,links:[]},faults:kind==="healthy"?[]:[{type:"controller_outage",start_tick:15,end_tick:30}],duration_ticks:100,tick_ms:1000,scope_lease_ticks:40};
}
export function initial(config){return {seq:0,tick:0,robots:config.robots.map(r=>({id:r.id,position:{...r.start},mode:"idle",zone:r.zone,task_id:null})),tasks:config.tasks.map(t=>({id:t.id,status:"pending",released:false,deferred:false,holder:null,epoch:0,expires_tick:null})),network:{active_faults:[],failed_nodes:[]},authority:[]}}
export function applyEvent(s,e){
 if(e.seq!==s.seq+1)throw Error("Event cursor gap");
 const p=e.payload,k=e.type;
 let next={...s,seq:e.seq,tick:e.tick};
 const robot=(id,patch)=>{next.robots=next.robots.map(r=>r.id===id?{...r,...patch,...(r.mode==="failed"?{mode:"failed"}:{})}:r)};
 const task=(id,patch)=>{next.tasks=next.tasks.map(t=>t.id===id?{...t,...patch}:t)};
 if(k==="robot.moved")robot(p.robot_id,{position:p.to});
 if(k==="robot.failed"){robot(p.robot_id,{mode:"failed"});next.network={...s.network,failed_nodes:[...new Set([...s.network.failed_nodes,p.robot_id])]} }
 if(k==="robot.waiting")robot(p.robot_id,{mode:"waiting"});
 if(k==="task.released")task(p.task_id,{released:true});
 if(k==="task.assigned"){task(p.task_id,{status:"assigned",holder:p.robot_id,epoch:p.epoch,expires_tick:p.expires_tick,deferred:false});robot(p.robot_id,{task_id:p.task_id,mode:"assigned"})}
 if(k==="task.picked"){task(p.task_id,{status:"picked"});robot(p.robot_id,{task_id:p.task_id,mode:"carrying"})}
 if(k==="task.completed"){task(p.task_id,{status:"completed"});robot(p.robot_id,{task_id:null,mode:"idle"})}
 if(k==="task.stranded")task(p.task_id,{status:"stranded"});
 if(k==="task.deferred")task(p.task_id,{deferred:true});
 if(k==="task.released_assignment"){task(p.task_id,{status:"pending",holder:null,expires_tick:null,deferred:true});robot(p.robot_id,{task_id:null,mode:"idle"})}
 if(k==="network.fault_started")next.network={...s.network,active_faults:[...new Set([...s.network.active_faults,p.fault_id])]};
 if(k==="network.fault_ended")next.network={...s.network,active_faults:s.network.active_faults.filter(x=>x!==p.fault_id)};
 if(k==="authority.granted"&&p.scope_id)next.authority=[...s.authority.filter(a=>a.scope_id!==p.scope_id),p];
 if(k==="authority.expired"&&p.scope_id)next.authority=s.authority.filter(a=>a.scope_id!==p.scope_id);
 return next;
}
export function parseSeeds(s){const a=s.split(",").map(x=>x.trim());if(!a.length||a.some(x=>!/^\d+$/.test(x)||Number(x)>2147483647))throw Error("Enter comma-separated nonnegative integer seeds.");const n=a.map(Number);if(n.length>60||new Set(n).size!==n.length)throw Error("Use 1–60 distinct seeds.");return n}
export function decodeFrame(frame){let id=null,type="",data=[];for(const l of frame.split(/\r?\n/)){if(l.startsWith("id:"))id=Number(l.slice(3).trim());if(l.startsWith("event:"))type=l.slice(6).trim();if(l.startsWith("data:"))data.push(l.slice(5).trimStart())}return data.length?{id,type,data:JSON.parse(data.join("\n"))}:null}
