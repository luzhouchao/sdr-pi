const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync(process.env.SDR_UI_SOURCE || __dirname+'/../public/app.js','utf8');
function harness(){
 const nodes=new Map();
 const node=id=>{if(!nodes.has(id))nodes.set(id,{id,textContent:'',value:'',hidden:false,disabled:false,scrollHeight:0,scrollTop:0,clientHeight:0,dataset:{},classList:{add(){},remove(){},toggle(){}},focus(){},setAttribute(){}});return nodes.get(id);};
 const context=vm.createContext({document:{querySelector:node,querySelectorAll:()=>[]},window:{confirm:()=>false,scrollTo(){}},AbortSignal,TextEncoder,Date,Map,JSON,Boolean,String,Number,Promise,console,setTimeout:()=>1,clearTimeout(){},EventSource:class{constructor(){context.eventSources=(context.eventSources||0)+1;}}});
 vm.runInContext(source.slice(0,source.indexOf("document.querySelector('#new-session').addEventListener")),context);
 vm.runInContext('render=()=>{};renderResultDetail=()=>{};renderResultsList=()=>{};globalThis.subject={view,loadState,send,navigate,selectResult,retryConnection};',context);
 return {context,...context.subject,nodes,node};
}
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const snapshot=id=>({active_session_id:id,sessions:[{id,title:id,events:[],status:'connected'}]});
test('late state cannot replace a newer session snapshot',async()=>{
 const h=harness(),a=deferred(),b=deferred();let n=0;h.context.api=()=>++n===1?a.promise:b.promise;
 const first=h.loadState(),second=h.loadState();b.resolve(snapshot('new'));await second;a.resolve(snapshot('old'));await first;
 assert.equal(h.view.active.id,'new');
});
test('stop bypasses a pending command and late acknowledgement preserves new draft',async()=>{
 const h=harness(),pending=deferred(),calls=[];h.view.active={id:'a'};h.view.input.value='initial';
 h.context.loadState=async()=>{};
 h.context.api=async(path,options)=>{const c=JSON.parse(options.body).command;calls.push(c);if(c!=='/stop')await pending.promise;return {};};
 const send=h.send('initial',{fromInput:true});h.view.input.value='new draft';
 await h.send('/stop');assert.deepEqual(calls,['initial','/stop']);pending.resolve();await send;
 assert.equal(h.view.input.value,'new draft');assert.equal(h.view.commandPending,false);
 assert.match(h.node('#command-feedback').textContent,/停止请求已送达/);
});
test('acknowledgement for old session cannot clear current session input',async()=>{
 const h=harness(),d=deferred();h.view.active={id:'a'};h.view.input.value='same text';h.context.api=()=>d.promise;h.context.loadState=async()=>{};
 const p=h.send('same text',{fromInput:true});h.view.active={id:'b'};d.resolve({});await p;assert.equal(h.view.input.value,'same text');
});
test('late result detail cannot replace the selected result',async()=>{
 const h=harness(),a=deferred();h.context.api=path=>path.endsWith('/1')?a.promise:Promise.resolve({summary:{id:2}});
 const first=h.selectResult(1);await h.selectResult(2);a.resolve({summary:{id:1}});await first;
 assert.equal(h.view.selectedResult.summary.id,2);
});
test('unsaved navigation cancel retains local settings and page',async()=>{
 const h=harness();h.view.settingsDirty=true;h.view.settingsOpen=true;h.context.confirmAction=async()=>false;
 assert.equal(await h.navigate('results'),false);assert.equal(h.view.settingsDirty,true);assert.equal(h.view.settingsOpen,true);
});
test('provider failure does not prevent SSE connection or loaded state',async()=>{
 const h=harness();h.context.loadState=async()=>{h.view.state=snapshot('a');};
 h.context.loadProvider=async()=>{throw new Error('unavailable');};h.context.refreshCorpusCount=async()=>[];
 await h.retryConnection();assert.equal(h.context.eventSources,1);assert.equal(h.view.online,true);
});
test('oversized UTF-8 command rejected without API write',async()=>{
 const h=harness();h.view.active={id:'a'};let writes=0;h.context.api=async()=>{writes++;};
 await h.send('接收'.repeat(200));assert.equal(writes,0);
});

test('malformed successful HTTP response is an explicit error',async()=>{
 const h=harness();h.context.fetch=async()=>({ok:true,json:async()=>{throw new Error('json');}});
 await assert.rejects(vm.runInContext("api('/api/state')",h.context),/无法读取/);
});

test('SSE coalesces bursts while state is loading instead of starving rendering',async()=>{
 const h=harness(),pending=deferred();let requests=0;
 h.context.loadState=async()=>{requests++;await pending.promise;};h.context.setTimeout=()=>1;
 vm.runInContext('connectEvents()',h.context);
 const first=h.view.eventSource.onopen();
 for(let i=0;i<20;i++)h.view.eventSource.onmessage();
 assert.equal(requests,1);pending.resolve();await first;assert.equal(h.view.online,true);
});

test('narrow-band spectrum axes keep adjacent tick labels distinct',()=>{
 const h=harness();const labels=vm.runInContext('Array.from({length:7},(_,i)=>formatAxisFrequency(2420000000+i*20000000/6,20000000))',h.context);
 assert.equal(new Set(labels).size,7);assert.equal(labels[0],'2420.0 MHz');assert.equal(labels[6],'2440.0 MHz');
});
