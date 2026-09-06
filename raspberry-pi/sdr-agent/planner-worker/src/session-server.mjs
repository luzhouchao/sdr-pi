import { chmodSync, existsSync, lstatSync, unlinkSync } from "node:fs";
import { createServer } from "node:net";
import { MAX_FRAME_BYTES } from "./protocol.mjs";
import { makeSessionResponse, parseSessionCommand } from "./session-protocol.mjs";
import { validateRuntimeSocketPath } from "./runtime-path.mjs";

export function startSessionServer({ socketPath, createRuntime, onError = () => {}, frameTimeoutMs = 1000, maxPendingFrames = 32 }) {
  if (!Number.isInteger(frameTimeoutMs) || frameTimeoutMs < 1 || frameTimeoutMs > 1000 || !Number.isInteger(maxPendingFrames) || maxPendingFrames < 1 || maxPendingFrames > 32) throw new Error("invalid session frame budgets");
  prepareSocket(socketPath);
  let activeSocket;
  const server = createServer((socket) => {
    if (activeSocket !== undefined) {
      writeFrame(socket, makeSessionResponse(undefined, false, "interactive session is busy"));
      socket.end();
      return;
    }
    activeSocket = socket;
    const runtime = createRuntime();
    let buffer = Buffer.alloc(0);
    let commandChain = Promise.resolve();
    let closing = false;
    let pendingFrames = 0;
    let partialTimer;
    const failConnection = (message) => {
      if (closing) return;
      writeFrame(socket, makeSessionResponse(undefined, false, message));
      closing = true;
      clearTimeout(partialTimer);
      socket.end(() => socket.destroy());
      const reap = setTimeout(() => socket.destroy(), 100);
      reap.unref();
    };
    const emit = (event) => {
      if (!closing && !socket.destroyed) writeFrame(socket, event);
    };

    socket.setNoDelay(true);
    socket.on("data", (chunk) => {
      if (closing) return;
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > MAX_FRAME_BYTES + 1 && !buffer.includes(0x0a)) {
        failConnection("session frame exceeds 32 KiB");
        return;
      }
      while (true) {
        const newline = buffer.indexOf(0x0a);
        if (newline < 0) break;
        clearTimeout(partialTimer);
        partialTimer = undefined;
        const frame = buffer.subarray(0, newline);
        buffer = buffer.subarray(newline + 1);
        if (frame.length > MAX_FRAME_BYTES) {
          failConnection("session frame exceeds 32 KiB");
          break;
        }
        if (pendingFrames >= maxPendingFrames) {
          failConnection("session pending frame limit exceeded");
          break;
        }
        pendingFrames += 1;
        commandChain = commandChain.then(async () => {
          if (closing) { pendingFrames -= 1; return; }
          let command;
          try {
            command = parseSessionCommand(frame.toString("utf8"));
            const response = await runtime.dispatch(command, emit);
            writeFrame(socket, response);
          } catch (error) {
            writeFrame(socket, makeSessionResponse(command, false, error));
          } finally {
            pendingFrames -= 1;
          }
        });
      }
      if (buffer.length > MAX_FRAME_BYTES) failConnection("session frame exceeds 32 KiB");
      if (buffer.length === 0 || closing) {
        clearTimeout(partialTimer);
        partialTimer = undefined;
      } else if (partialTimer === undefined) {
        partialTimer = setTimeout(() => failConnection("session partial frame deadline exceeded"), frameTimeoutMs);
        partialTimer.unref();
      }
    });
    socket.on("error", onError);
    socket.on("close", () => {
      closing = true;
      clearTimeout(partialTimer);
      activeSocket = undefined;
      void commandChain.finally(() => runtime.dispose()).catch(onError);
    });
  });
  server.maxConnections = 2;
  server.listen(socketPath, () => chmodSync(socketPath, 0o660));
  return server;
}

function prepareSocket(socketPath) {
  validateRuntimeSocketPath(socketPath, "session socket");
  if (!existsSync(socketPath)) return;
  if (!lstatSync(socketPath).isSocket()) {
    throw new Error("refusing to replace a non-socket session path");
  }
  unlinkSync(socketPath);
}

function writeFrame(socket, value) {
  const frame = `${JSON.stringify(value)}\n`;
  if (Buffer.byteLength(frame, "utf8") > MAX_FRAME_BYTES + 1) {
    socket.write(`${JSON.stringify(makeSessionResponse(undefined, false, "session response exceeds 32 KiB"))}\n`);
    return;
  }
  if (socket.writableLength + Buffer.byteLength(frame, "utf8") > 2 * MAX_FRAME_BYTES) {
    socket.destroy();
    return;
  }
  socket.write(frame);
}
