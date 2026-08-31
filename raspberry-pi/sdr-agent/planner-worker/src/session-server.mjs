import { chmodSync, existsSync, lstatSync, unlinkSync } from "node:fs";
import { createServer } from "node:net";
import { MAX_FRAME_BYTES } from "./protocol.mjs";
import { makeSessionResponse, parseSessionCommand } from "./session-protocol.mjs";

export function startSessionServer({ socketPath, createRuntime, onError = () => {} }) {
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
    const emit = (event) => {
      if (!closing && !socket.destroyed) writeFrame(socket, event);
    };

    socket.setNoDelay(true);
    socket.on("data", (chunk) => {
      if (closing) return;
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > MAX_FRAME_BYTES + 1 && !buffer.includes(0x0a)) {
        writeFrame(socket, makeSessionResponse(undefined, false, "session frame exceeds 32 KiB"));
        closing = true;
        socket.end();
        return;
      }
      while (true) {
        const newline = buffer.indexOf(0x0a);
        if (newline < 0) break;
        const frame = buffer.subarray(0, newline);
        buffer = buffer.subarray(newline + 1);
        if (frame.length > MAX_FRAME_BYTES) {
          writeFrame(socket, makeSessionResponse(undefined, false, "session frame exceeds 32 KiB"));
          continue;
        }
        commandChain = commandChain.then(async () => {
          let command;
          try {
            command = parseSessionCommand(frame.toString("utf8"));
            const response = await runtime.dispatch(command, emit);
            writeFrame(socket, response);
          } catch (error) {
            writeFrame(socket, makeSessionResponse(command, false, error));
          }
        });
      }
    });
    socket.on("error", onError);
    socket.on("close", () => {
      closing = true;
      activeSocket = undefined;
      void commandChain.finally(() => runtime.dispose()).catch(onError);
    });
  });
  server.maxConnections = 2;
  server.listen(socketPath, () => chmodSync(socketPath, 0o660));
  return server;
}

function prepareSocket(socketPath) {
  const runtimePrefix = `/run/user/${process.getuid?.()}/sdr-agent/`;
  if (!socketPath.startsWith("/run/sdr-agent/") && !socketPath.startsWith(runtimePrefix)) {
    throw new Error("session socket must be under a dedicated /run sdr-agent directory");
  }
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
  socket.write(frame);
}
