import { createHash } from 'node:crypto';
import { DatabaseSync, backup } from 'node:sqlite';
import { chmod, lstat, mkdir, open, readFile, readdir, realpath, rmdir, unlink } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { openDurableServiceState, validBusinessId } from './durable-service-state.mjs';
import { openDurableStore } from './durable-store.mjs';

async function privateDirectory(path) {
  const m=await lstat(path);
  if(!m.isDirectory() || m.uid!==process.getuid() || (m.mode&0o077) || await realpath(path)!==path)throw new Error('private canonical directory required');
}
async function privateFile(path) {
  const m=await lstat(path);
  if(!m.isFile() || m.uid!==process.getuid() || m.nlink!==1 || (m.mode&0o077))throw new Error('private regular single-link file required');
  return m;
}

// Offline only: the same root owner lock excludes the live Worker before any
// backup/delete. No Harness is opened and no task can run during maintenance.
export async function maintainDurableState({operation,root,sessionId,output,confirmDelete=false}) {
  if(!['status','archive','delete'].includes(operation) || resolve(root)!==root)throw new Error('invalid maintenance operation or root');
  await privateDirectory(root);await privateFile(join(root,'service.sqlite'));
  const service=await openDurableServiceState(root);
  try {
    if(operation==='status') {
      const sessions=[];
      for(const entry of await readdir(root,{withFileTypes:true})) {
        if(!entry.isDirectory() || !validBusinessId(entry.name))continue;
        await privateDirectory(join(root,entry.name));
        const path=join(root,entry.name,'planner.sqlite');
        try {sessions.push({session_id:entry.name,bytes:(await privateFile(path)).size});}
        catch(error){if(error.code!=='ENOENT')throw error;}
      }
      return {offline:true,sessions};
    }
    if(!validBusinessId(sessionId))throw new Error('invalid session identity');
    const path=join(root,sessionId,'planner.sqlite');
    await privateDirectory(dirname(path));await privateFile(path);
    const store=await openDurableStore(path);
    try {
      if(operation==='archive') {
        if(!output || resolve(output)!==output || output===path)throw new Error('absolute new archive path required');
        await mkdir(dirname(output),{recursive:true,mode:0o700});await privateDirectory(dirname(output));
        const target=await open(output,'wx',0o600);await target.close();
        let source;
        try {
          source=new DatabaseSync(path,{readOnly:true});await backup(source,output);
          await chmod(output,0o600);
          const bytes=await readFile(output);const sha256=createHash('sha256').update(bytes).digest('hex');
          const manifest={schema_version:1,sdk:'1.4.0',session_id:sessionId,bytes:bytes.length,sha256,
            controller_ledger:'separate authority; not included',restore:'offline only; reopen revokes execution eligibility'};
          const archive=await open(output,'r');try{await archive.sync();}finally{await archive.close();}
          const metadata=await open(`${output}.manifest.json`,'wx',0o600);
          try {await metadata.writeFile(JSON.stringify(manifest,null,2)+'\n');await metadata.sync();}finally{await metadata.close();}
          const parent=await open(dirname(output),'r');try{await parent.sync();}finally{await parent.close();}
          return {archive:output,...manifest};
        }catch(error){await unlink(output).catch(()=>{});throw error;}
        finally{source?.close();}
      }
      if(!confirmDelete)throw new Error('delete requires --yes after selecting the exact session');
      const allowed=new Set(['planner.sqlite','planner.sqlite-wal','planner.sqlite-shm','planner.sqlite.owner.sqlite','planner.sqlite.owner.sqlite-journal']);
      let bytes=0,files=0;
      for(const name of await readdir(dirname(path))) {
        if(!allowed.has(name))throw new Error('unexpected file in session directory; deletion refused');
        bytes+=(await privateFile(join(dirname(path),name))).size;files++;
      }
      await store.quiesce();
      for(const suffix of ['','-wal','-shm']) {
        try {await privateFile(path+suffix);await unlink(path+suffix);}
        catch(error){if(error.code!=='ENOENT')throw error;}
      }
      await store.close();
      // The root owner still excludes all service/maintenance entry points, so
      // removing this now-closed child owner inode cannot admit another writer.
      await unlink(`${path}.owner.sqlite`);await rmdir(dirname(path));
      const parent=await open(root,'r');try{await parent.sync();}finally{await parent.close();}
      return {deleted_session:sessionId,files,bytes_before_close:bytes,controller_ledger_retained:true};
    }finally{await store.close();}
  }finally{await service.close();}
}

if(process.argv[1] && pathToFileURL(await realpath(resolve(process.argv[1]))).href===import.meta.url) {
  try {
    const [operation,...args]=process.argv.slice(2);const options={operation};
    const names={'--state-dir':'root','--session-id':'sessionId','--output':'output'};
    for(let i=0;i<args.length;i++) {
      if(args[i]==='--yes'){options.confirmDelete=true;continue;}
      const key=names[args[i]];if(!key || options[key]!==undefined || !args[i+1])throw new Error('invalid maintenance arguments');
      options[key]=args[++i];
    }
    if(!options.root)throw new Error('--state-dir is required');
    console.log(JSON.stringify(await maintainDurableState(options)));
  }catch(error){process.stderr.write(`durable_maintenance_error=${error.message}\n`);process.exitCode=1;}
}
