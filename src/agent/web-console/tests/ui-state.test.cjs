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


test('survey presentation distinguishes explicit cancellation without hiding failures',()=>{
 const h=harness();
 const present=(status,events)=>{
  h.context.sample={initial_survey_status:status,events};
  return vm.runInContext('initialSurveyLabel(initialSurveyState(sample))',h.context);
 };
 const cancelled={kind:'sweep',text:'首次扫频已取消并完成恢复：capture_failed_restored'};
 assert.equal(present('running',[]),'首次扫描进行中');
 assert.equal(present('failed',[cancelled]),'首次扫描已取消');
 assert.equal(h.context.sample.initial_survey_status,'failed');
 assert.equal(present('failed',[cancelled,{kind:'sweep',text:'首次扫频失败：timeout'}]),'首次扫频失败');
 assert.equal(present('failed',[{kind:'system',text:'会话已停止；旧计划已失效。'}]),'首次扫频失败');
 assert.equal(present('failed',[{...cancelled,kind:'operator'}]),'首次扫频失败');
 assert.equal(present('complete',[cancelled]),'首次频谱已建立');
 assert.equal(present('failed',[]),'首次扫频失败');
});


test('confirmed cancellation is readable while the full diagnostic stays intact',()=>{
 const h=harness();
 h.context.event={kind:'sweep',text:'首次扫频已取消并完成恢复：remote_error metadata={"request_id":5}'};
 const original=h.context.event.text;
 assert.match(vm.runInContext('operatorEventText(event)',h.context),/完整记录可在诊断中查看/);
 assert.equal(h.context.event.text,original);
 h.context.event.kind='operator';
 assert.equal(vm.runInContext('operatorEventText(event)',h.context),original);
 h.context.event={kind:'sweep',text:'首次扫频失败：timeout'};
 assert.equal(vm.runInContext('operatorEventText(event)',h.context),'首次扫频失败：timeout');
});

test('frequency display keeps Hz precision and does not rewrite persisted sweep evidence',()=>{
 const h=harness();
 assert.equal(h.context.formatFrequencyRange(2400000000,2483500000),'2.4–2.4835 GHz');
 assert.equal(h.context.formatFrequency(433920000),'433.92 MHz');
 assert.equal(h.context.formatFrequency(2400000001),'2.400000001 GHz');
 const event={kind:'sweep',text:'首次扫频已开始：2400000000–2483500000 Hz，12 个点，步进 8000000 Hz'};
 assert.equal(h.context.operatorEventText(event),'首次扫频已开始：2.4–2.4835 GHz，12 个点，步进 8 MHz');
 assert.match(event.text,/2400000000/);
});
test('mixed survey selection sends null only for AI fields and drops late suggestions',async()=>{
 const h=harness();h.context.surveyMode=()=> 'custom_band';
 h.node('#survey-start-mhz').value='2400';h.node('#survey-stop-mhz').value='2483.5';h.node('#survey-step-mhz').value='1';h.node('#survey-dwell-ms').value='5';h.node('#survey-gain-db').value='20';
 h.node('#survey-step-source').value='manual';h.node('#survey-dwell-source').value='ai';h.node('#survey-gain-source').value='ai';
 const req=h.context.surveySuggestionPayload();assert.equal(req.step_hz,1000000);assert.equal(req.dwell_ms,null);assert.equal(req.gain_db,null);
 const pending=deferred();h.context.api=()=>pending.promise;
 const run=h.context.suggestSurveyParameters();h.view.settingsRevision++;h.node('#survey-step-mhz').value='2';
 pending.resolve({initial_survey:{step_hz:1000000,dwell_ms:10,gain_db:30},planner:{model:'test'}});await run;
 assert.equal(h.node('#survey-step-mhz').value,'2');assert.equal(h.node('#survey-gain-db').value,'20');assert.match(h.node('#survey-assistant-status').textContent,/迟到/);
 assert.equal(h.context.surveySuggestionCurrent(),false);
});

test('ordinary hold reply appears once while original plan and notice stay in the audit',()=>{
 const h=harness();const events=[{kind:'operator',text:'你好'},
 {kind:'plan',text:'已验证计划：保持当前状态：你好，不操作硬件。'},
 {kind:'decision',text:'validated request=1'},
 {kind:'qwen',text:'Agent> 你好，不操作硬件。'},
 {kind:'system',text:'该计划当前没有生产执行器，仅记录建议，不会操作硬件。'}];
 const original=JSON.stringify(events);const hidden=h.context.redundantHoldEvents(events);
 assert.deepEqual(events.filter(e=>hidden.has(e)),[events[1],events[4]]);
 assert.equal(JSON.stringify(events),original);
 assert.equal(h.context.redundantHoldEvents(events.slice(0,3)).size,0);
});
test('hold presentation never hides hardware plans, unmatched replies, warnings or later turns',()=>{
 const h=harness();const plan={kind:'plan',text:'已验证计划：保持当前状态：你好'};
 const reply={kind:'qwen',text:'Agent> 你好'};
 for (const events of [[plan,{kind:'operator',text:'新问题'},reply],
 [plan,{...reply,text:'Agent> 不同回复'}],
 [{kind:'plan',text:'已验证计划：扫描频段'},reply],
 [{...plan,kind:'operator'},reply]]) assert.equal(h.context.redundantHoldEvents(events).size,0);
 const warning={kind:'system',text:'设备连接失败'};
 assert.equal(h.context.redundantHoldEvents([plan,reply,warning]).has(warning),false);
 const later={kind:'system',text:'该计划当前没有生产执行器，仅记录建议，不会操作硬件。'};
 assert.equal(h.context.redundantHoldEvents([plan,reply,{kind:'operator',text:'继续'},later]).has(later),false);
});
