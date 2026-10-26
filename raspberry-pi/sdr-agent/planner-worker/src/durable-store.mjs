import { DatabaseSync } from "node:sqlite";
import { chmodSync, existsSync, lstatSync, mkdirSync, openSync, closeSync, realpathSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";

// SQLite's OS-backed exclusive transaction is the lifetime lock. A separate,
// data-free lock database avoids holding a transaction on Harness's WAL store.
// SIGKILL releases it through the kernel; there is no PID-file eviction race.
export async function openDurableStore(path) {
  if (resolve(path) !== path) throw new Error("durable database requires a canonical absolute path");
  const parent = dirname(path);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  const dir = lstatSync(parent);
  if (realpathSync(parent) !== parent || !dir.isDirectory() || dir.uid !== process.getuid() || (dir.mode & 0o077)) {
    throw new Error("durable directory must be private and owned by the Worker");
  }
  for (const file of [path, `${path}-wal`, `${path}-shm`, `${path}.owner.sqlite`]) {
    let info;
    try { info = lstatSync(file); } catch (error) { if (error.code === "ENOENT") continue; throw error; }
    if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid() || (info.mode & 0o077)) {
      throw new Error("unsafe durable database file");
    }
  }
  const lockPath = `${path}.owner.sqlite`;
  try { closeSync(openSync(lockPath, "wx", 0o600)); } catch (error) { if (error.code !== "EEXIST") throw error; }
  let lock;
  try {
    lock = new DatabaseSync(lockPath);
    lock.exec("PRAGMA busy_timeout=0; BEGIN EXCLUSIVE;");
  } catch {
    lock?.close();
    throw new Error("durable store already owned or lifetime lock unavailable");
  }
  try {
    // Precreate with mode 0600 even when a caller has a permissive umask.
    try { closeSync(openSync(path, "wx", 0o600)); } catch (error) { if (error.code !== "EEXIST") throw error; }
    const storage = await openNodeSqliteStorage(path, { busyTimeoutMs: 0 });
    for (const file of [path, `${path}-wal`, `${path}-shm`]) if (existsSync(file)) chmodSync(file, 0o600);
    let closed = false;
    return {
      storage,
      // Maintenance may close the business database while retaining the
      // permanent owner inode's lock until backup/deletion has settled.
      async quiesce() { await storage.close(); },
      async close() {
        if (closed) return;
        closed = true;
        try { await storage.close(); } finally { lock.close(); }
      },
    };
  } catch (error) {
    lock.close();
    throw error;
  }
}
