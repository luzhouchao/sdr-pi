import assert from 'node:assert/strict';
import test from 'node:test';
import {spawnSync} from 'node:child_process';
import {mkdtemp,rm,readFile,stat,writeFile,symlink} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {openDurableServiceState} from '../src/durable-service-state.mjs';
import {openDurableStore} from '../src/durable-store.mjs';
import {maintainDurableState} from '../src/durable-maintenance.mjs';

test('offline archive and exact deletion exclude live owner and preserve other sessions',async t=>{
 const base=await mkdtemp(join(tmpdir(),'pd-maint-'));t.after(()=>rm(base,{recursive:true,force:true}));
 const root=join(base,'state');const service=await openDurableServiceState(root);
 for(const id of ['alpha','beta']){const store=await openDurableStore(service.databasePath(id));await store.close();}
 await assert.rejects(maintainDurableState({operation:'status',root}),/already owned/);
 await assert.rejects(openDurableServiceState(root),/already owned/);
 assert.throws(()=>service.databasePath('../escape'),/invalid/);
 const cli=join(base,'maintenance.mjs');await symlink(new URL('../src/durable-maintenance.mjs',import.meta.url).pathname,cli);
 const blocked=spawnSync(process.execPath,[cli,'status','--state-dir',root],{encoding:'utf8'});assert.equal(blocked.status,1);assert.match(blocked.stderr,/already owned/);
 await service.close();
 const listed=spawnSync(process.execPath,[cli,'status','--state-dir',root],{encoding:'utf8'});assert.equal(listed.status,0,listed.stderr);assert.equal(JSON.parse(listed.stdout).sessions.length,2);
 const result=await maintainDurableState({operation:'archive',root,sessionId:'alpha',output:join(base,'backup.sqlite')});
 const data=await readFile(result.archive);assert.equal(result.sha256,createHash('sha256').update(data).digest('hex'));
 assert.equal((await stat(result.archive)).mode&0o777,0o600);
 assert.equal(JSON.parse(await readFile(`${result.archive}.manifest.json`)).session_id,'alpha');
 const db=new DatabaseSync(result.archive,{readOnly:true});assert.equal(db.prepare('PRAGMA integrity_check').get().integrity_check,'ok');db.close();
 await assert.rejects(maintainDurableState({operation:'archive',root,sessionId:'alpha',output:result.archive}),/EEXIST/);
 await assert.rejects(maintainDurableState({operation:'delete',root,sessionId:'alpha'}),/--yes/);
 const extra=join(root,'alpha','unexpected');await writeFile(extra,'keep',{mode:0o600});
 await assert.rejects(maintainDurableState({operation:'delete',root,sessionId:'alpha',confirmDelete:true}),/unexpected/);
 await rm(extra);await symlink(join(root,'beta','planner.sqlite'),extra);
 await assert.rejects(maintainDurableState({operation:'delete',root,sessionId:'alpha',confirmDelete:true}),/unexpected/);await rm(extra);
 const deleted=await maintainDurableState({operation:'delete',root,sessionId:'alpha',confirmDelete:true});assert.ok(deleted.files>=2);assert.ok(deleted.bytes_before_close>0);
 const status=await maintainDurableState({operation:'status',root});assert.deepEqual(status.sessions.map(s=>s.session_id),['beta']);
 await assert.rejects(stat(join(root,'alpha')),/ENOENT/);
});
