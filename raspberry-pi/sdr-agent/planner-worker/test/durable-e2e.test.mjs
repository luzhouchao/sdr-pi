import assert from 'node:assert/strict';
import test from 'node:test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp,mkdir,rm,readFile,readdir} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createServer,connect} from 'node:net';
import {planningUpstream} from '../test-support/planning-upstream.mjs';

const binary=process.env.SDR_TEST_CONTROLLER_BIN;
async function waitFor(check,label,ms=10000){const deadline=Date.now()+ms;while(Date.now()<deadline){if(await check())return;await new Promise(r=>setTimeout(r,10));}throw new Error(`deadline: ${label}`);}

test('real Controller v2 ledger reconciles a lost ACK across Controller restart without replay',{skip:!binary,timeout:30000},async t=>{
 const root=await mkdtemp(join(tmpdir(),'durable-e2e-'));
 const run=`/run/user/${process.getuid()}/sdr-agent`;await mkdir(run,{recursive:true,mode:0o700});
 const suffix=`durable-e2e-${process.pid}`;const plan=`${run}/${suffix}-plan.sock`,session=`${run}/${suffix}-session.sock`,proxyPath=`${run}/${suffix}-proxy.sock`;
 const {upstream,requests}=await planningUpstream();const children=[],connections=[];let dropAck=true,acksDropped=0;
 const worker=spawn(process.execPath,[new URL('../src/main.mjs',import.meta.url).pathname],{env:{...process.env,
  SDR_PLANNER_BASE_URL:`http://127.0.0.1:${upstream.address().port}/v1`,SDR_PLANNER_API:'openai-completions',SDR_PLANNER_PROVIDER:'sdk-test',SDR_PLANNER_MODEL:'test-model',SDR_PLANNER_API_KEY:'test-only-key',SDR_PLANNER_API_KEY_FILE:'',
  SDR_PLANNER_PROVIDER_CONFIG:join(root,'absent.json'),SDR_PLANNER_WEB_SEARCH_URL:'',SDR_PLANNER_SOCKET:plan,SDR_SESSION_SOCKET:session,SDR_DURABLE_DB:join(root,'planner.sqlite'),
 },stdio:['ignore','ignore','pipe']});children.push(worker);let workerLog='';worker.stderr.on('data',b=>workerLog+=b);
 const proxy=createServer(front=>{
  const back=connect(session);connections.push(front,back);back.pipe(front);
  let buffer='';front.setEncoding('utf8');front.on('data',chunk=>{
   buffer+=chunk;let newline;
   while((newline=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,newline);buffer=buffer.slice(newline+1);const command=JSON.parse(line);
    if(dropAck && command.type==='plan_ack'){acksDropped++;continue;}back.write(line+'\n');
   }
  });
  front.on('end',()=>back.end());front.on('error',()=>back.destroy());back.on('error',()=>front.destroy());
  front.on('close',()=>back.destroy());back.on('close',()=>front.destroy());
 });
 t.after(async()=>{
  for(const child of children){if(child.exitCode===null && child.signalCode===null){const exited=once(child,'exit');child.kill('SIGKILL');await exited;}}
  for(const socket of connections)socket.destroy();await new Promise(r=>proxy.close(r));
  upstream.closeAllConnections();await new Promise(r=>upstream.close(r));
  for(const path of [plan,session,proxyPath,root])await rm(path,{recursive:true,force:true});
 });
 await waitFor(()=>workerLog.includes('session_ready'),'worker ready');proxy.listen(proxyPath);await once(proxy,'listening');
 const fixturePath=new URL('../../../../jetson-agx/sdrharness/config/request.json',import.meta.url).pathname;
 const startController=()=>{
  const child=spawn(binary,['--socket',proxyPath,'--request',fixturePath,'--session-state',join(root,'terminal.json')],{env:{...process.env,SDR_DURABLE_CONTROLLER_DIR:join(root,'ledger')},stdio:['pipe','pipe','pipe']});children.push(child);
  let output='';child.stdout.on('data',b=>output+=b);child.stderr.on('data',b=>output+=b);
  return {child,output:()=>output};
 };
 const first=startController();await waitFor(()=>first.output().includes('逐步批准') || first.output().includes('/help'),'first Controller ready');
 first.child.stdin.write('只提交hold保持等待\n');
 await waitFor(()=>first.output().includes('该计划当前没有生产执行器'),'first admitted hold');
 await waitFor(()=>acksDropped===1,'ACK dropped');
 const exited=once(first.child,'exit');first.child.kill('SIGKILL');await exited;
 // Socket cleanup owns the reservation until the tool's cancellation joins.
 await waitFor(()=>connections.filter(s=>!s.destroyed).length===0,'proxy connection cleanup');
 await waitFor(async()=>{
  const probe=connect(plan);probe.on('error',()=>{});await once(probe,'connect');
  const data=once(probe,'data');probe.write('{"protocol_version":1,"operation":"health"}\n');
  try {return JSON.parse((await data)[0].toString()).session_available;}finally{probe.destroy();}
 },'old runtime fully disposed');
 dropAck=false;
 const second=startController();await waitFor(()=>second.output().includes('逐步批准') || second.output().includes('/help'),'second Controller ready');
 second.child.stdin.write('只提交hold保持等待\n');
 await waitFor(()=>second.output().includes('该计划当前没有生产执行器'),'second admitted hold');
 await waitFor(()=>requests.length===2,'two new requests only');
 second.child.stdin.write('/quit\n');const [code]=await once(second.child,'exit');assert.equal(code,0,second.output());
 const dirs=await readdir(join(root,'ledger'));assert.equal(dirs.length,1);
 const ledger=JSON.parse(await readFile(join(root,'ledger',dirs[0],'plans.json')));
 const records=Object.values(ledger.records);assert.equal(records.length,2);
 assert.equal(new Set(records.map(r=>r.identity.controller_epoch)).size,2);
 assert.ok(records.every(r=>r.decision==='accepted' && r.execution==='completed'));
 assert.equal(requests.length,2,'old request must not be regenerated or redelivered');
 assert.equal(acksDropped,1);
});
