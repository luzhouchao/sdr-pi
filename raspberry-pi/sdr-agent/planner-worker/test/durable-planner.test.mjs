import assert from 'node:assert/strict';
import test from 'node:test';
import { fork } from 'node:child_process';
import { once } from 'node:events';
import { openDurableStore } from '../src/durable-store.mjs';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createModels, createProvider } from '@earendil-works/pi-ai';
import { fauxProvider, fauxAssistantMessage, fauxToolCall } from '@earendil-works/pi-ai/providers/faux';
import { DurablePlanner } from '../src/durable-planner.mjs';
import { RunLease } from '../src/run-lease.mjs';
import { AgentDoc, configure } from '@earendil-works/pi-durable';
import { BACKGROUND_CONTEXT } from '@earendil-works/chord/context';
import { PLANNER_SYSTEM_PROMPT } from '../src/system-prompt.mjs';

const request = JSON.parse(await readFile(new URL('../../../../jetson-agx/sdrharness/config/request.json', import.meta.url)));
const hold = () => fauxAssistantMessage(fauxToolCall('submit_plan', {action:'hold', reason:'isolated verification'}), {stopReason:'toolUse'});
async function fixture(t, extra = {}) {
  const root = await mkdtemp(join(tmpdir(), 'durable-'));
  const faux = fauxProvider({provider:'durable-test',models:[{id:'test',contextWindow:32768,maxTokens:512}],tokensPerSecond:100000});
  const models = createModels(); models.setProvider(faux.provider);
  const deliveries = []; const lease = new RunLease();
  const options = {path:join(root,'state.sqlite'),models,model:{provider:'durable-test',modelId:'test'},providerIdentity:{provider:'durable-test',model:'test'},runLease:lease,
    deliver:async p => {deliveries.push(p); return {planId:p.planId,hash:p.hash,state:'accepted'};}, ...extra};
  let engine = await DurablePlanner.open(options);
  t.after(async () => {await engine.close(); await rm(root,{recursive:true,force:true});});
  return {get engine(){return engine;},faux,deliveries,lease,options, async reopen(){await engine.close();engine=await DurablePlanner.open(options);return engine;}};
}
const identity = {appSessionId:'session_a',controllerEpoch:'epoch_a',sessionGeneration:3};
const input = (id=9) => ({...structuredClone(request),request_id:id,session_generation:3});

test('disk Harness records one proposal and preserves it across reopen', {timeout:10000}, async t => {
  const f=await fixture(t); f.faux.setResponses([hold()]);
  await f.engine.attach(identity);
  const id=await f.engine.submit('session_a',input());
  await f.engine.idle();
  assert.equal(f.deliveries.length,1);
  assert.equal(f.faux.state.callCount,1);
  assert.equal(f.lease.state().busy,false);
  const state=await f.engine.state('session_a');
  assert.equal(state.requests['epoch_a:3:9'].proposal.state,'accepted');
  assert.equal(await f.engine.submit('session_a',input()),id);
  await f.engine.idle(); assert.equal(f.deliveries.length,1);
  await f.reopen();
  assert.equal((await f.engine.state('session_a')).requests['epoch_a:3:9'].enabled,false);
  await f.engine.attach(identity);
  await assert.rejects(f.engine.recover('session_a',[9]),/reconciliation/);
  assert.equal(f.deliveries.length,1);
});

const deferred = () => {let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
test('concurrent duplicate input deduplicates; conflicting content rejects; sessions stay independent', {timeout:10000}, async t => {
  const f=await fixture(t);f.faux.setResponses([hold(),hold()]);
  await f.engine.attach(identity);
  const ids=await Promise.all([f.engine.submit('session_a',input()),f.engine.submit('session_a',input())]);
  assert.equal(ids[0],ids[1]);await f.engine.idle();
  await assert.rejects(f.engine.submit('session_a',{...input(),instruction:'changed'}),/different content/);
  await f.engine.idle();
  await f.engine.attach({...identity,appSessionId:'session_b'});
  await f.engine.submit('session_b',input());await f.engine.idle();
  assert.deepEqual(f.deliveries.map(p=>p.appSessionId),['session_a','session_b']);
  assert.equal(f.faux.state.callCount,2);
});

test('abort blocks a late tool and holds the shared lease until cleanup completes', {timeout:10000}, async t => {
  const entered=deferred(), release=deferred();
  const f=await fixture(t,{beforeDelivery:async()=>{entered.resolve();await release.promise;}});
  f.faux.setResponses([hold()]);await f.engine.attach(identity);
  await f.engine.submit('session_a',input());await entered.promise;
  await assert.rejects(f.engine.closeSession('session_a'),/abort active/);
  const aborted=f.engine.abort('session_a');
  assert.equal(f.lease.acquire('one-shot'),undefined);
  release.resolve();await aborted;
  assert.equal(f.deliveries.length,0);assert.equal(f.lease.state().busy,false);
  await f.reopen();await f.engine.attach(identity);
  await assert.rejects(f.engine.recover('session_a',[9]),/reconciliation/);
  assert.equal(f.deliveries.length,0);
});

test('deadline expires during tool preparation: zero deliveries', {timeout:10000}, async t => {
  let now=Date.now();
  const f=await fixture(t,{now:()=>now,beforeDelivery:async()=>{now+=2000;}});
  f.faux.setResponses([hold()]);await f.engine.attach(identity);
  await f.engine.submit('session_a',input(),{deadline:now+1000});await f.engine.idle();
  assert.equal(f.deliveries.length,0);
});

test('lost ACK remains unknown and never automatically resends', {timeout:10000}, async t => {
  let attempts=0;
  const f=await fixture(t,{deliver:async()=>{attempts++;throw new Error('lost acknowledgement');}});
  f.faux.setResponses([hold()]);await f.engine.attach(identity);
  const id=await f.engine.submit('session_a',input());await f.engine.idle();
  assert.equal((await f.engine.state('session_a')).requests['epoch_a:3:9'].proposal.state,'unknown');
  assert.equal(await f.engine.submit('session_a',input()),id);await f.engine.idle();
  await f.reopen();await f.engine.attach({...identity,controllerEpoch:'epoch_b'});
  await assert.rejects(f.engine.recover('session_a',[9]),/reconciliation/);
  assert.equal(attempts,1);assert.equal(f.faux.state.callCount,1);
});

test('busy prompt rejects; queue is bounded and can be withdrawn without delivering', {timeout:10000}, async t => {
  const entered=deferred(),release=deferred();
  const f=await fixture(t);f.faux.setResponses([async()=>{entered.resolve();await release.promise;return hold();}]);
  await f.engine.attach(identity);await f.engine.submit('session_a',input());await entered.promise;
  await assert.rejects(f.engine.submit('session_a',input(10)),/busy/);
  for(let id=10;id<14;id++) await f.engine.submit('session_a',input(id),{mode:'follow_up'});
  await assert.rejects(f.engine.submit('session_a',input(14),{mode:'follow_up'}),/queue limit/);
  assert.equal(await f.engine.clearQueue('session_a'),4);
  release.resolve();await f.engine.idle();
  assert.equal(f.faux.state.callCount,1);assert.equal(f.deliveries.length,1);
  const state=await f.engine.state('session_a');
  for(let id=10;id<14;id++) assert.equal(state.requests[`epoch_a:3:${id}`].reason,'queue_withdrawn');
});

test('storage capacity failure closes the delivery gate', {timeout:10000}, async t => {
  const f=await fixture(t);await f.engine.attach(identity);f.engine.maxBytes=1;
  await assert.rejects(f.engine.submit('session_a',input()),/storage budget/);
  await assert.rejects(f.engine.attach({...identity,appSessionId:'other'}),/unavailable/);
  assert.equal(f.deliveries.length,0);assert.equal(f.faux.state.callCount,0);
});

async function crashAt(t,path,stage) {
  const child=fork(new URL('../test-support/durable-crash-child.mjs',import.meta.url),[path,stage],{stdio:['ignore','ignore','pipe','ipc']});
  let stderr='';child.stderr.on('data',b=>stderr+=b);
  t.after(()=>{if(child.exitCode===null)child.kill('SIGKILL');});
  const message=await Promise.race([once(child,'message').then(([m])=>m),once(child,'exit').then(()=>{throw new Error(`child exited before fault: ${stderr}`);})]);
  assert.equal(message.stage,stage==='lock'?'locked':stage);
  return child;
}
async function kill(child){const exited=once(child,'exit');child.kill('SIGKILL');await exited;}

test('cross-process lifetime owner rejects second writer and SIGKILL releases the lock', {timeout:10000}, async t => {
  const root=await mkdtemp(join(tmpdir(),'owner-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const path=join(root,'state.sqlite');const child=await crashAt(t,path,'lock');
  await assert.rejects(openDurableStore(path),/already owned/);
  await kill(child);const store=await openDurableStore(path);await store.close();
});

for(const stage of ['prepared','attempted']) test(`SIGKILL at ${stage}: reopen never resends an interrupted tool`,{timeout:15000},async t=>{
  const root=await mkdtemp(join(tmpdir(),'crash-'));
  const path=join(root,'state.sqlite');await kill(await crashAt(t,path,stage));
  const f=await fixture(t,{path});t.after(()=>rm(root,{recursive:true,force:true}));f.faux.setResponses([hold()]);
  await f.engine.attach(identity);
  const state=await f.engine.state('session_a');
  assert.equal(state.requests['epoch_a:3:9'].proposal.state,stage==='attempted'?'unknown':'prepared');
  await assert.rejects(f.engine.recover('session_a',[9]),/reconciliation/);
  // New input enables the global scheduler, including recovery of old tasks.
  await f.engine.submit('session_a',input(10),{mode:'follow_up'});await f.engine.idle();
  assert.equal(f.deliveries.length,0); // failed recovered run withdraws queued inputs
  await f.engine.submit('session_a',input(11));await f.engine.idle();
  assert.deepEqual(f.deliveries.map(p=>p.key),['epoch_a:3:11']);
  assert.equal(f.faux.state.callCount,1);
});

for(const changed of [false,true]) test(`SIGKILL mid-model: ${changed?'new epoch rejects':'explicit same-epoch recovery permits'} old work`,{timeout:15000},async t=>{
  const root=await mkdtemp(join(tmpdir(),'model-crash-'));
  const path=join(root,'state.sqlite');await kill(await crashAt(t,path,'model'));
  const f=await fixture(t,{path});t.after(()=>rm(root,{recursive:true,force:true}));f.faux.setResponses([hold()]);
  await f.engine.attach({...identity,controllerEpoch:changed?'epoch_new':'epoch_a'});
  if(changed){
    await assert.rejects(f.engine.recover('session_a',[9]),/reconciliation/);
    await f.engine.submit('session_a',input(10),{mode:'follow_up'});await f.engine.idle();
    assert.equal(f.deliveries.length,0);
    await f.engine.submit('session_a',input(11));await f.engine.idle();
    assert.deepEqual(f.deliveries.map(p=>p.key),['epoch_new:3:11']);
  }else{
    await f.engine.recover('session_a',[9]);await f.engine.idle();
    assert.deepEqual(f.deliveries.map(p=>p.key),['epoch_a:3:9']);
  }
  assert.equal(f.faux.state.callCount,1);
});

test('durable write failure during prepared tool fails closed', {timeout:10000},async t=>{
  const f=await fixture(t,{beforeDelivery:async()=>{
    f.engine.store.storage.commit=async()=>{throw new Error('injected disk write failure');};
  }});
  f.faux.setResponses([hold()]);await f.engine.attach(identity);
  await f.engine.submit('session_a',input());
  await f.engine.idle().catch(()=>{});
  assert.equal(f.deliveries.length,0);
  await assert.rejects(f.engine.submit('session_a',input(10)),/unavailable|failed|storage/i);
});

for(const options of [{},{spark:true},{api:'openai-responses'}]) test(`disk Harness streaming parity ${JSON.stringify(options)}`,{timeout:10000},async t=>{
  const {planningUpstream}=await import('../test-support/planning-upstream.mjs');
  const {openAICompletionsApi}=await import('@earendil-works/pi-ai/api/openai-completions.lazy');
  const {openAIResponsesApi}=await import('@earendil-works/pi-ai/api/openai-responses.lazy');
  const {createSparkJsonPlanningStream}=await import('../src/spark-stream.mjs');
  const {upstream,requests}=await planningUpstream(options);
  t.after(async()=>{upstream.closeAllConnections();await new Promise(r=>upstream.close(r));});
  const api=options.api??'openai-completions';
  const model={id:'test-model',name:'test-model',api,provider:'http-test',baseUrl:`http://127.0.0.1:${upstream.address().port}/v1`,reasoning:false,input:['text'],contextWindow:32768,maxTokens:512,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
  const models=createModels();
  models.setProvider(createProvider({id:model.provider,name:'isolated upstream',baseUrl:model.baseUrl,models:[model],api:api==='openai-responses'?openAIResponsesApi():openAICompletionsApi(),
    auth:{apiKey:{name:'test',resolve:async()=>({auth:{apiKey:'test-only-key'},source:'test'})}}}));
  const f=await fixture(t,{models,model:{provider:model.provider,modelId:model.id},streamAdapter:options.spark?createSparkJsonPlanningStream:undefined});
  await f.engine.attach(identity);await f.engine.submit('session_a',input());await f.engine.idle();
  assert.equal(f.deliveries.length,1);assert.equal(f.deliveries[0].action.kind,'hold');assert.equal(requests.length,1);
  const {payload}=requests[0];
  if(options.spark){assert.equal(payload.tools,undefined);assert.equal(payload.response_format.type,'json_schema');}
  else {assert.equal(payload.tools.length,1);assert.equal(payload.tool_choice.type,'function');}
  const db=await readFile(f.options.path);assert.equal(db.includes(Buffer.from('test-only-key')),false);
});

test('bounded repeated sessions measure RSS, heap and SQLite growth', {timeout:15000},async t=>{
  const {stat}=await import('node:fs/promises');
  const f=await fixture(t);f.faux.setResponses(Array.from({length:32},hold));
  await f.engine.attach(identity);
  const start=process.memoryUsage();let peakRss=start.rss,peakHeap=start.heapUsed;
  for(let id=100;id<132;id++){
    await f.engine.submit('session_a',input(id));await f.engine.idle();
    const usage=process.memoryUsage();peakRss=Math.max(peakRss,usage.rss);peakHeap=Math.max(peakHeap,usage.heapUsed);
  }
  const sizes=await Promise.all([f.options.path,`${f.options.path}-wal`,`${f.options.path}-shm`].map(p=>stat(p).then(v=>v.size).catch(()=>0)));
  assert.equal(f.deliveries.length,32);assert.ok(peakRss<384*1024*1024);assert.ok(peakHeap<192*1024*1024);
  assert.ok(sizes.reduce((a,b)=>a+b,0)<64*1024*1024);
  t.diagnostic(JSON.stringify({iterations:32,peakRss,peakHeap,sqliteBytes:sizes.reduce((a,b)=>a+b,0)}));
});

test('generation mismatch and stale generation after restart produce zero old deliveries',{timeout:10000},async t=>{
  const f=await fixture(t);await f.engine.attach(identity);
  await assert.rejects(f.engine.submit('session_a',{...input(),session_generation:2}),/stale generation/);
  f.faux.setResponses([hold()]);await f.engine.submit('session_a',input());await f.engine.idle();
  await f.reopen();await f.engine.attach({...identity,sessionGeneration:4});
  await assert.rejects(f.engine.recover('session_a',[9]),/reconciliation/);
  assert.equal(f.deliveries.length,1);assert.equal(f.faux.state.callCount,1);
});

for(const expire of [false,true]) test(`Spark search turns recheck durable provider fence; expire=${expire}`,{timeout:10000},async t=>{
  const {createSparkJsonPlanningStream}=await import('../src/spark-stream.mjs');let now=Date.now();
  const f=await fixture(t,{now:()=>now,streamAdapter:base=>createSparkJsonPlanningStream(base,{webSearch:async query=>{
    if(expire)now+=60000;return {query,sources:[],truncated:false};
  }})});
  f.faux.setResponses([
    fauxAssistantMessage(JSON.stringify({adapter_action:'web_search',query:'bounded check'})),
    fauxAssistantMessage(JSON.stringify({adapter_action:'submit_plan',plan:{action:'hold',reason:'safe'}})),
  ]);
  await f.engine.attach(identity);await f.engine.submit('session_a',input());await f.engine.idle();
  assert.equal(f.faux.state.callCount,expire?1:2);assert.equal(f.deliveries.length,expire?0:1);
});

test('archived Planner history reopens with old execution eligibility revoked',{timeout:10000},async t=>{
 const {openDurableServiceState}=await import('../src/durable-service-state.mjs');
 const {maintainDurableState}=await import('../src/durable-maintenance.mjs');
 const base=await mkdtemp(join(tmpdir(),'pd-restore-'));const root=join(base,'state');
 let service=await openDurableServiceState(root);const path=service.databasePath('session_a');
 const f=await fixture(t,{path});f.faux.setResponses([hold()]);await f.engine.attach(identity);await f.engine.submit('session_a',input());await f.engine.idle();
 await f.engine.close();await service.close();
 const output=join(base,'history.sqlite');await maintainDurableState({operation:'archive',root,sessionId:'session_a',output});
 let restored;
 try {
  restored=await DurablePlanner.open({...f.options,path:output});
  assert.equal((await restored.state('session_a')).requests['epoch_a:3:9'].enabled,false);
  await restored.attach({...identity,controllerEpoch:'new_epoch'});
  await assert.rejects(restored.recover('session_a',[9]),/reconciliation/);
  await restored.idle();assert.equal(f.deliveries.length,1);assert.equal(f.faux.state.callCount,1);
 }finally{await restored?.close();await rm(base,{recursive:true,force:true});}
});

test('DeepSeek structured request preserves thinking with compatible automatic tool choice',{timeout:10000},async t=>{
 const {openAICompletionsApi}=await import('@earendil-works/pi-ai/api/openai-completions.lazy');
 const {resolveModelProfile}=await import('../src/model-profile.mjs');
 const {planningUpstream}=await import('../test-support/planning-upstream.mjs');
 const {upstream,requests}=await planningUpstream();
 t.after(async()=>{upstream.closeAllConnections();await new Promise(r=>upstream.close(r));});
 const model=resolveModelProfile({provider:'opencode-go',model:'deepseek-v4.1-flash',api:'openai-completions',baseUrl:'https://opencode.ai/inference/go/v1',contextWindow:500000},4096);
 assert.equal(model.compat.thinkingFormat,'deepseek');model.baseUrl=`http://127.0.0.1:${upstream.address().port}/v1`;
 const models=createModels();models.setProvider(createProvider({id:model.provider,baseUrl:model.baseUrl,auth:{apiKey:{name:'test',resolve:async()=>({auth:{apiKey:'test-only'},source:'test'})}},models:[model],api:openAICompletionsApi()}));
 const f=await fixture(t,{models,thinkingLevel:"low",model:{provider:model.provider,modelId:model.id}});
 await f.engine.attach(identity);await f.engine.submit('session_a',input());await f.engine.idle();
 assert.equal(requests.length,1);assert.equal(f.deliveries.length,1);
 assert.deepEqual(requests[0].payload.thinking,{type:'enabled'});
 assert.equal(requests[0].payload.tool_choice,'auto');
 assert.deepEqual(requests[0].payload.tools.map(tool=>tool.function.name),['submit_plan']);
});


test('reattaching a persisted conversation refreshes policy/model/thinking before the next provider call', {timeout:10000}, async t => {
  const contexts=[];
  const f=await fixture(t,{thinkingLevel:'low',streamAdapter:base=>(model,context,options)=>{
    contexts.push(structuredClone(context));return base(model,context,options);
  }});
  f.faux.setResponses([hold(),hold()]);
  const conversationId=await f.engine.attach(identity);
  await f.engine.submit('session_a',input());await f.engine.idle();
  // Reproduce an existing conversation created by a previous installed policy.
  await f.engine.harness.commit(tx=>configure(tx,conversationId,{
    instructions:'obsolete policy without cruise progress rules',
    model:{provider:'obsolete',modelId:'obsolete'},thinkingLevel:'off',tools:[],
  }),BACKGROUND_CONTEXT);
  await f.reopen();
  const reopenedId=await f.engine.attach({...identity,controllerEpoch:'epoch_b'});
  assert.equal(reopenedId,conversationId);
  const agent=await f.engine.harness.snapshot(AgentDoc,conversationId,BACKGROUND_CONTEXT);
  assert.equal(agent.instructions,PLANNER_SYSTEM_PROMPT);
  assert.deepEqual(agent.model,f.options.model);
  assert.equal(agent.thinkingLevel,'low');
  assert.deepEqual(agent.tools,['submit_plan']);
  assert.equal(f.deliveries.length,1); // attach must not replay the old request
  const state=await f.engine.state('session_a');
  assert.equal(state.requests['epoch_a:3:9'].enabled,false);
  const next=input(10);
  next.cruise={remaining_steps:6,remaining_ms:90000,remaining_iq_bytes:917504,
    local_sweep_limit:3,empty_sweep_limit:3,consecutive_empty_sweeps:2,
    recent_sweeps:[{start_hz:2450000000,stop_hz:2460000000,candidate_count:0},
      {start_hz:2460000000,stop_hz:2465000000,candidate_count:0}],history_truncated:false};
  await f.engine.submit('session_a',next);await f.engine.idle();
  assert.equal(f.deliveries.length,2);assert.equal(contexts.length,2);
  const wire=JSON.stringify(contexts[1]);
  assert.ok(wire.includes('[AUTOMATIC CRUISE PROGRESS]'));
  assert.ok(wire.includes('start_task: interpret an operator'));
  assert.ok(wire.includes('Do not require a special command'));
  assert.ok(wire.includes('NOT independent measured noise'));
  assert.ok(!wire.includes('obsolete policy'));
  const user=contexts[1].messages.findLast(x=>x.role==='user');
  const text=typeof user.content==='string'?user.content:user.content.filter(x=>x.type==='text').map(x=>x.text).join('');
  assert.deepEqual(JSON.parse(text).context.cruise,next.cruise);
});
