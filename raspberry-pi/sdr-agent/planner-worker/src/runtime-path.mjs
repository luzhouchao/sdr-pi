import { dirname, resolve } from "node:path";

export function validateRuntimeSocketPath(socketPath, label = "socket") {
  const allowedDirectories = new Set(["/run/sdr-agent", "/run/sdrharness"]);
  const uid = process.getuid?.();
  if (uid !== undefined) {
    allowedDirectories.add(`/run/user/${uid}/sdr-agent`);
    allowedDirectories.add(`/run/user/${uid}/sdrharness`);
  }
  const resolved = resolve(socketPath);
  if (resolved !== socketPath || !allowedDirectories.has(dirname(resolved))) {
    throw new Error(
      `${label} must be directly under a dedicated /run sdr-agent or sdrharness directory`,
    );
  }
}
