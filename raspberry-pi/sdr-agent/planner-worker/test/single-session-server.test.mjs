import assert from "node:assert/strict";
import { mkdirSync, rmSync } from "node:fs";
import { connect } from "node:net";
import { once } from "node:events";
import test from "node:test";
import { startSessionServer } from "../src/session-server.mjs";

function openSocket(socketPath) {
  return new Promise((resolve, reject) => {
    const socket = connect(socketPath);
    const failConnect = (error) => reject(error);
    socket.once("error", failConnect);
    socket.once("connect", () => {
      socket.off("error", failConnect);
      socket.on("error", () => {});
      resolve(socket);
    });
  });
}

function readFrame(socket) {
  return new Promise((resolve, reject) => {
    let buffered = "";
    socket.setEncoding("utf8");
    socket.on("data", (chunk) => {
      buffered += chunk;
      const newline = buffered.indexOf("\n");
      if (newline >= 0) resolve(JSON.parse(buffered.slice(0, newline)));
    });
    socket.once("error", reject);
  });
}

function waitForClose(socket) {
  if (socket.destroyed) return Promise.resolve();
  return new Promise((resolve) => {
    socket.once("close", resolve);
    socket.once("error", resolve);
  });
}

test("permits only one interactive control connection", async (context) => {
  const uid = process.getuid?.();
  if (uid === undefined) {
    context.skip("Unix runtime ownership is unavailable");
    return;
  }
  const runtimeRoot = `/run/user/${uid}/sdr-agent`;
  const socketPath = `${runtimeRoot}/single-session-${process.pid}.sock`;
  mkdirSync(runtimeRoot, { recursive: true, mode: 0o700 });
  rmSync(socketPath, { force: true });
  const server = startSessionServer({
    socketPath,
    createRuntime: () => ({
      async dispatch(command) {
        return {
          protocol_version: 1,
          command_id: command.command_id,
          session_generation: command.session_generation,
          type: "response",
          command: command.type,
          success: true,
        };
      },
      async dispose() {},
    }),
  });
  await once(server, "listening");

  const owner = await openSocket(socketPath);
  const rejected = await openSocket(socketPath);
  const response = await readFrame(rejected);
  assert.equal(response.success, false);
  assert.match(response.error, /interactive session is busy/u);
  await waitForClose(rejected);

  const ownerClosed = waitForClose(owner);
  owner.end();
  await ownerClosed;

  server.close();
  await once(server, "close");
  rmSync(socketPath, { force: true });
});
