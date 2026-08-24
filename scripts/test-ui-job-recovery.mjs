import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

const temporaryDirectory = await mkdtemp(path.join(tmpdir(), "flagshipeditor-ui-recovery-"));
const bundlePath = path.join(temporaryDirectory, "resilient-job.mjs");

try {
  await build({
    entryPoints: [path.resolve("src/js/main/lib/resilient-job.ts")],
    outfile: bundlePath,
    bundle: true,
    platform: "node",
    format: "esm",
    logLevel: "silent",
  });
  const { pollPersistentJob, retryTransientOperation } = await import(pathToFileURL(bundlePath).href);

  {
    const notices = [];
    const statuses = [];
    const sleeps = [];
    const responses = [new Error("timeout"), { state: "running" }, { state: "completed" }];
    const result = await pollPersistentJob({
      terminalStates: new Set(["completed", "cancelled", "failed"]),
      cancellationRequested: () => false,
      getStatus: async () => {
        const response = responses.shift();
        if (response instanceof Error) throw response;
        return response;
      },
      cancel: async () => ({ state: "cancelling" }),
      onStatus: (status) => statuses.push(status.state),
      isTransient: (error) => error instanceof Error && error.message === "timeout",
      onReconnect: (notice) => notices.push(notice.attempt),
      sleep: async (milliseconds) => { sleeps.push(milliseconds); },
    });
    assert.equal(result.state, "completed");
    assert.deepEqual(statuses, ["running", "completed"]);
    assert.deepEqual(notices, [1]);
    assert.deepEqual(sleeps, [1000, 600]);
  }

  {
    const missing = Object.assign(new Error("not found"), { status: 404 });
    let sleeps = 0;
    await assert.rejects(
      pollPersistentJob({
        terminalStates: new Set(["completed"]),
        cancellationRequested: () => false,
        getStatus: async () => { throw missing; },
        cancel: async () => ({ state: "cancelled" }),
        onStatus: () => undefined,
        isTransient: () => false,
        onReconnect: () => undefined,
        sleep: async () => { sleeps += 1; },
      }),
      (error) => error === missing,
    );
    assert.equal(sleeps, 0, "terminal 404 must not enter a reconnect loop");
  }

  {
    const statuses = [];
    let statusCalls = 0;
    let cancelCalls = 0;
    const result = await pollPersistentJob({
      terminalStates: new Set(["cancelled"]),
      cancellationRequested: () => true,
      getStatus: async () => {
        statusCalls += 1;
        if (statusCalls === 1) throw new Error("offline");
        return statusCalls === 2 ? { state: "running" } : { state: "cancelled" };
      },
      cancel: async () => {
        cancelCalls += 1;
        return { state: "cancelling" };
      },
      onStatus: (status) => statuses.push(status.state),
      isTransient: (error) => error instanceof Error && error.message === "offline",
      onReconnect: () => undefined,
      sleep: async () => undefined,
    });
    assert.equal(result.state, "cancelled");
    assert.equal(cancelCalls, 1, "cancel remains actionable after reconnect");
    assert.deepEqual(statuses, ["running", "cancelling", "cancelled"]);
  }

  {
    const notices = [];
    const delays = [];
    let attempts = 0;
    const result = await retryTransientOperation(
      async () => {
        attempts += 1;
        if (attempts < 3) throw new Error("result timeout");
        return { results: ["safe"] };
      },
      {
        isTransient: () => true,
        onReconnect: (notice) => notices.push(notice.attempt),
        sleep: async (milliseconds) => { delays.push(milliseconds); },
      },
    );
    assert.deepEqual(result, { results: ["safe"] });
    assert.deepEqual(notices, [1, 2]);
    assert.deepEqual(delays, [1000, 2000]);
  }

  console.log("UI analysis-job recovery tests passed (status retry, terminal 404, cancel during reconnect, result retry). ");
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
