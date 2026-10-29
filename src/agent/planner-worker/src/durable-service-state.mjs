import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { openDurableStore } from './durable-store.mjs';

export function validBusinessId(value) {
  return typeof value==='string' && /^[A-Za-z0-9_-]{1,128}$/u.test(value) && !['__proto__','constructor','prototype'].includes(value);
}

// The service-wide owner is acquired before touching either socket. It also
// excludes offline maintenance, including operations on another business DB.
export async function openDurableServiceState(root) {
  const owner=await openDurableStore(join(root,'service.sqlite'));
  return {
    root,
    databasePath(appSessionId) {
      if(!validBusinessId(appSessionId))throw new Error('invalid business session identity');
      const path=join(root,appSessionId,'planner.sqlite');
      if(!existsSync(path) && readdirSync(root,{withFileTypes:true}).filter(e=>e.isDirectory()).length>=128)throw new Error('durable business session capacity reached; archive or delete inactive history');
      return path;
    },
    close:()=>owner.close(),
  };
}
