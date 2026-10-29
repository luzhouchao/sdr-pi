import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createModels} from '@earendil-works/pi-ai';
import {fauxProvider,fauxAssistantMessage,fauxToolCall} from '@earendil-works/pi-ai/providers/faux';
import {DurablePlanner} from '../src/durable-planner.mjs';
import {DurableSessionRuntime} from '../src/durable-session-runtime.mjs';
import {parseSessionCommand} from '../src/session-protocol.mjs';
import {RunLease} from '../src/run-lease.mjs';
const req=JSON.parse(await readFile(new URL('../../../../deploy/agx/config/request.json',import.meta.url)));
const open={protocol_version:2,command_id:1,type:'open_session',session_generation:1,app_session_id:'app',controller_epoch:'epoch'};
const command=(type,extra={})=>parseSessionCommand(JSON.stringify({protocol_version:2,command_id:2,type,session_generation:1,...extra}));
async function fixture(t,{ack=true}={}){
 const root=await mkdtemp(join(tmpdir(),'durable-session-'));const frames=[];let engine;
 const faux=fauxProvider({provider:'session-test',models:[{id:'test',contextWindow:32768,maxTokens:512}],tokensPerSecond:100000});
 faux.setResponses([fauxAssistantMessage(fauxToolCall('submit_plan',{action:'hold',reason:'safe'}),{stopReason:'toolUse'})]);
 const models=createModels();models.setProvider(faux.provider);const lease=new RunLease();
 const runtime=new DurableSessionRuntime({createEngine:async callbacks=>{
  engine=await DurablePlanner.open({path:join(root,'state.sqlite'),models,model:{provider:'session-test',modelId:'test'},providerIdentity:{provider:'session-test'},runLease:lease,...callbacks});
  return {engine,plannerMeta:{provider:'session-test',model:'test'}};
 }});
 const emit=frame=>{frames.push(frame);if(ack && frame.event==='plan_proposed'){
   void runtime.dispatch(command('plan_ack',{plan_id:frame.delivery.plan_id,hash:frame.delivery.hash,state:'accepted'}),emit);
 }};
 t.after(async()=>{await runtime.dispose();await rm(root,{recursive:true,force:true});});
 const dispatch=c=>runtime.dispatch(c,emit);
 assert.equal((await dispatch(parseSessionCommand(JSON.stringify(open)))).success,true);
 return {runtime,dispatch,frames,faux,lease,get engine(){return engine;}};
}
test('v2 runtime requires a persisted Controller ACK and preserves strict PlanResponse',{timeout:10000},async t=>{
 const f=await fixture(t);assert.equal((await f.dispatch(command('prompt',{context:req}))).success,true);
 await f.runtime.monitor;
 const proposed=f.frames.filter(v=>v.event==='plan_proposed');assert.equal(proposed.length,1);
 assert.equal(proposed[0].delivery.controller_epoch,'epoch');assert.equal(proposed[0].data.action.kind,'hold');
 assert.equal(proposed[0].data.plan_id,undefined);
 const state=await f.engine.state('app');assert.equal(state.requests[`epoch:1:${req.request_id}`].proposal.state,'accepted');
 assert.equal(f.lease.state().busy,false);assert.equal((await f.dispatch(command('close_session'))).success,true);
});
test('disconnect while waiting for ACK revokes and joins; unknown proposal cannot resume',{timeout:10000},async t=>{
 const f=await fixture(t,{ack:false});
 await f.dispatch(command('prompt',{context:req}));
 while(!f.frames.some(v=>v.event==='plan_proposed'))await new Promise(r=>setImmediate(r));
 await f.runtime.dispose();assert.equal(f.lease.state().busy,false);assert.equal(f.faux.state.callCount,1);
 assert.equal(f.frames.filter(v=>v.event==='plan_proposed').length,1);
});
test('abort awaiting ACK permits idle close and next generation open',{timeout:10000},async t=>{
 const f=await fixture(t,{ack:false});await f.dispatch(command('prompt',{context:req}));
 while(!f.frames.some(v=>v.event==='plan_proposed'))await new Promise(r=>setImmediate(r));
 assert.equal((await f.dispatch(command('abort'))).success,true);
 assert.equal(f.lease.state().busy,false);assert.equal((await f.dispatch(command('close_session'))).success,true);
 assert.equal((await f.dispatch({...open,command_id:3,session_generation:2})).success,true);
 assert.equal(f.frames.filter(v=>v.event==='plan_proposed').length,1);
});
test('strict v2 parser rejects missing identity, invalid ACK and extra keys',()=>{
 for(const c of [{...open,controller_epoch:undefined},{...open,app_session_id:'../x'},{...open,extra:1},
 {protocol_version:1,command_id:1,session_generation:1,type:'plan_ack'},
 {protocol_version:2,command_id:1,session_generation:1,type:'plan_ack',plan_id:'x',hash:'z',state:'accepted'}])assert.throws(()=>parseSessionCommand(JSON.stringify(c)));
});

test('blocked missing task is visible; abort joins before releasing the lease',{timeout:10000},async t=>{
 const {defineTask}=await import('@earendil-works/pi-durable');
 const {BACKGROUND_CONTEXT}=await import('@earendil-works/chord/context');
 const f=await fixture(t);
 const token=defineTask({name:'test.unregistered',version:1,initial:()=>({phase:'initial'}),phases:{initial:async()=>{throw new Error('must never run');}},abort:async()=>{throw new Error('must never run');}});
 const conversationId=f.engine.attachments.get('app').conversationId;
 await f.engine.harness.commit(tx=>tx.createTask(token,{}, {conversationId,ownership:{kind:'conversation'}}),BACKGROUND_CONTEXT);
 assert.equal((await f.dispatch(command('prompt',{context:req}))).success,false);
 const state=await f.dispatch(command('get_state'));
 assert.deepEqual(state.data.blocked,[{reason:'missing_task'}]);
 assert.equal(f.lease.acquire('one-shot'),undefined);
 assert.equal((await f.dispatch(command('abort'))).success,true);
 assert.equal(f.lease.state().busy,false);assert.equal(f.faux.state.callCount,0);
});

test('duplicate persisted ACK is idempotent, changed decision rejects',{timeout:10000},async t=>{
 const f=await fixture(t);await f.dispatch(command('prompt',{context:req}));await f.runtime.monitor;
 const plan=f.frames.find(v=>v.event==='plan_proposed').delivery;
 const ack=command('plan_ack',{plan_id:plan.plan_id,hash:plan.hash,state:'accepted'});
 assert.equal((await f.dispatch(ack)).success,true);
 assert.equal((await f.dispatch({...ack,state:'rejected'})).success,false);
 assert.equal(f.frames.filter(v=>v.event==='plan_proposed').length,1);
});

test('text without submit_plan reports failure and sends zero proposals',{timeout:10000},async t=>{
 const f=await fixture(t);f.faux.setResponses([fauxAssistantMessage('Hold without a tool call.')]);
 await f.dispatch(command('prompt',{context:req}));await f.runtime.monitor;
 assert.equal(f.frames.filter(v=>v.event==='plan_proposed').length,0);
 assert.ok(f.frames.some(v=>v.event==='agent_error' && v.data.error.includes('No valid proposal')));
 assert.equal(f.faux.state.callCount,1);assert.equal(f.lease.state().busy,false);
});

test('abort after natural completion does not emit a duplicate agent_end',{timeout:10000},async t=>{
 const f=await fixture(t);await f.dispatch(command('prompt',{context:req}));await f.runtime.monitor;
 assert.equal(f.frames.filter(v=>v.event==='agent_end').length,1);
 assert.equal((await f.dispatch(command('abort'))).success,true);
 assert.equal(f.frames.filter(v=>v.event==='agent_end').length,1,'duplicate end would make cruise count a successful plan as missing');
});

test('abort of an active run emits exactly one agent_end',{timeout:10000},async t=>{
 const f=await fixture(t,{ack:false});await f.dispatch(command('prompt',{context:req}));
 while(!f.frames.some(v=>v.event==='plan_proposed'))await new Promise(r=>setImmediate(r));
 assert.equal((await f.dispatch(command('abort'))).success,true);
 assert.equal(f.frames.filter(v=>v.event==='agent_end').length,1);
 assert.equal(f.lease.state().busy,false);
});
