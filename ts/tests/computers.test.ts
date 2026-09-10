import assert from "node:assert/strict";
import { describe, it } from "node:test";

import * as sdk from "../src/index";
import { Computer } from "../src/computers/computer";
import { ComputersClient } from "../src/computers/client";
import type { CreateComputerParams } from "../src/computers/types";
import type { ClientConfig } from "../src/core/config";
import { CelestoApiError, CelestoError, CelestoNetworkError } from "../src/core/errors";

interface RecordedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

const makeFetchMock = (
  responder: (call: RecordedCall) => { status: number; body: unknown },
): { fetch: typeof fetch; calls: RecordedCall[] } => {
  const calls: RecordedCall[] = [];
  const mock: typeof fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const rawHeaders = (init?.headers ?? {}) as Record<string, string>;
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(rawHeaders)) {
      headers[k.toLowerCase()] = v;
    }
    const bodyStr = typeof init?.body === "string" ? init.body : undefined;
    const parsed = bodyStr ? JSON.parse(bodyStr) : undefined;
    const call: RecordedCall = {
      url,
      method: init?.method ?? "GET",
      headers,
      body: parsed,
    };
    calls.push(call);
    const { status, body } = responder(call);
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  };
  return { fetch: mock, calls };
};

const makeConfig = (fetchMock: typeof fetch): ClientConfig => ({
  baseUrl: "https://api.example.test",
  token: "test-token",
  fetch: fetchMock,
});

describe("ComputersClient", () => {
  it("top-level package exports Computer API but not the old Celesto client", () => {
    assert.equal(sdk.Computer, Computer);
    assert.equal(typeof sdk.resolveCelestoApiKey, "function");
    assert.equal(typeof sdk.resolveClientConfig, "function");
    assert.equal("Celesto" in sdk, false);
  });

  it("create() sends explicit resource/template fields and unwraps snake_case response", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_abc",
        name: "test",
        status: "creating",
        vcpus: 2,
        ram_mb: 2048,
        disk_size_mb: 15360,
        image: "ubuntu-desktop-24.04",
        template_id: "coding-agent",
        template_version: "latest",
        external_volume_enabled: true,
        created_at: "2026-04-16T00:00:00Z",
        last_error: null,
        stopped_at: null,
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.create({
      cpus: 2,
      memory: 2048,
      diskSizeMb: 15360,
      templateId: "coding-agent",
      templateVersion: "latest",
      persistentHome: true,
    });

    assert.equal(calls.length, 1);
    assert.equal(calls[0]!.method, "POST");
    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers");
    assert.deepEqual(calls[0]!.body, {
      vcpus: 2,
      ram_mb: 2048,
      disk_size_mb: 15360,
      template_id: "coding-agent",
      template_version: "latest",
      external_volume_enabled: true,
    });
    assert.equal(calls[0]!.headers["authorization"], "Bearer test-token");
    assert.equal(result.id, "cmp_abc");
    assert.equal(result.ramMb, 2048);
    assert.equal(result.diskSizeMb, 15360);
    assert.equal(result.templateId, "coding-agent");
    assert.equal(result.templateVersion, "latest");
    assert.equal(result.persistentHome, true);
    assert.equal(result.lastError, null);
  });

  it("create() leaves defaults to the backend when no params are provided", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_d",
        name: "d",
        status: "creating",
        vcpus: 1,
        ram_mb: 512,
        disk_size_mb: 7168,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.create();

    assert.deepEqual(calls[0]!.body, {});
    assert.deepEqual(result.networkPolicy, { mode: "open" });
  });

  it("create() can explicitly disable a persistent home", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_ephemeral",
        name: "ephemeral",
        status: "creating",
        vcpus: 1,
        ram_mb: 512,
        disk_size_mb: 7168,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
        external_volume_enabled: false,
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.create({ persistentHome: false });

    assert.deepEqual(calls[0]!.body, { external_volume_enabled: false });
    assert.equal(result.persistentHome, false);
  });

  it("create() accepts friendly disk sizes", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        id: "cmp_disk",
        name: "disk",
        status: "creating",
        vcpus: 1,
        ram_mb: 1024,
        disk_size_mb: 1536,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    await client.create({ disk: "1.5gb" });

    assert.deepEqual(calls[0]!.body, { disk_size_mb: 1536 });
  });

  it("create() rejects conflicting aliases", async () => {
    const client = new ComputersClient(makeConfig(async () => new Response()));

    await assert.rejects(
      () => client.create({ cpus: 1, vcpus: 2 }),
      /cpus and vcpus must have the same value/i,
    );
    await assert.rejects(
      () => client.create({ memory: 1024, ramMb: 2048 }),
      /memory and ramMb must have the same value/i,
    );
    await assert.rejects(
      () => client.create({ disk: "2gb", diskSizeMb: 1024 }),
      /disk and diskSizeMb must have the same value/i,
    );
  });

  it("list() maps each computer through the wire transform", async () => {
    const { fetch } = makeFetchMock(() => ({
      status: 200,
      body: {
        computers: [
          {
            id: "cmp_1",
            name: "one",
            status: "running",
            vcpus: 1,
            ram_mb: 1024,
            disk_size_mb: 7168,
            image: "ubuntu-desktop-24.04",
            template_id: "scratch",
            created_at: "2026-04-16T00:00:00Z",
            connection: { ssh: "user@host", access_url: "https://a" },
          },
          {
            id: "cmp_2",
            name: "two",
            status: "stopped",
            vcpus: 4,
            ram_mb: 8192,
            disk_size_mb: 15360,
            image: "ubuntu-desktop-24.04",
            template_id: "browser-agent",
            created_at: "2026-04-16T00:00:00Z",
            stopped_at: "2026-04-16T01:00:00Z",
          },
        ],
        count: 2,
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.list();

    assert.equal(result.count, 2);
    assert.equal(result.computers.length, 2);
    assert.equal(result.computers[0]!.connection?.ssh, "user@host");
    assert.equal(result.computers[0]!.connection?.accessUrl, "https://a");
    assert.equal(result.computers[1]!.diskSizeMb, 15360);
    assert.equal(result.computers[1]!.templateId, "browser-agent");
    assert.equal(result.computers[1]!.stoppedAt, "2026-04-16T01:00:00Z");
  });

  it("listTemplates() maps sandbox template metadata", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 200,
      body: [
        {
          id: "coding-agent",
          display_name: "Coding Agent",
          description: "Ready-to-code sandbox",
          default_vcpus: 1,
          default_ram_mb: 1024,
          default_disk_size_mb: 15360,
          version: "latest",
          experimental: false,
        },
      ],
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const templates = await client.listTemplates();

    assert.equal(calls[0]!.method, "GET");
    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers/templates");
    assert.equal(templates[0]!.id, "coding-agent");
    assert.equal(templates[0]!.displayName, "Coding Agent");
    assert.equal(templates[0]!.defaultDiskSizeMb, 15360);
  });

  it("Computer static list and listTemplates cover listing without the old Celesto client", async () => {
    const { fetch, calls } = makeFetchMock((call) => ({
      status: 200,
      body: call.url.includes("/templates")
        ? [
            {
              id: "scratch",
              display_name: "Scratch",
              description: "Minimal VM",
              default_vcpus: 1,
              default_ram_mb: 512,
              default_disk_size_mb: 7168,
              version: "latest",
              experimental: false,
            },
          ]
        : {
            computers: [
              {
                id: "cmp_1",
                name: "curie",
                status: "running",
                vcpus: 1,
                ram_mb: 512,
                disk_size_mb: 7168,
                image: "ubuntu-desktop-24.04",
                template_id: "scratch",
                created_at: "2026-04-16T00:00:00Z",
              },
            ],
            count: 1,
          },
    }));

    const computers = await Computer.list({ status: "running", templateId: "scratch" }, makeConfig(fetch));
    const templates = await Computer.listTemplates(makeConfig(fetch));

    assert.equal(computers[0]!.name, "curie");
    assert.equal(templates[0]!.id, "scratch");
    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers?status=running&template_id=scratch");
    assert.equal(calls[1]!.url, "https://api.example.test/v1/computers/templates");
  });

  it("Computer static methods automatically resolve local credentials", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 200,
      body: { computers: [], count: 0 },
    }));
    const previousApiKey = process.env.CELESTO_API_KEY;
    process.env.CELESTO_API_KEY = "resolved-token";

    try {
      await Computer.list({}, { baseUrl: "https://api.example.test", fetch });
    } finally {
      if (previousApiKey === undefined) {
        delete process.env.CELESTO_API_KEY;
      } else {
        process.env.CELESTO_API_KEY = previousApiKey;
      }
    }

    assert.equal(calls[0]!.headers["authorization"], "Bearer resolved-token");
  });

  it("get() resolves name to ID via /v1/computers/{name}", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 200,
      body: {
        id: "cmp_resolved",
        name: "my-name",
        status: "running",
        vcpus: 1,
        ram_mb: 1024,
        disk_size_mb: 7168,
        image: "ubuntu-desktop-24.04",
        template_id: "scratch",
        created_at: "2026-04-16T00:00:00Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const info = await client.get("my-name");

    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers/my-name");
    assert.equal(info.id, "cmp_resolved");
  });

  it("exec() sends command + timeout and maps execution metadata", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 200,
      body: {
        exit_code: 0,
        stdout: "ok\n",
        stderr: "",
        command_id: "cmd_1",
        duration_ms: 25,
        timed_out: false,
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.exec("cmp_1", "uname -a", { timeout: 60 });

    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers/cmp_1/exec");
    assert.deepEqual(calls[0]!.body, { command: "uname -a", timeout: 60 });
    assert.deepEqual(result, {
      exitCode: 0,
      stdout: "ok\n",
      stderr: "",
      commandId: "cmd_1",
      durationMs: 25,
      timedOut: false,
    });
  });

  it("exec() preserves the legacy response shape when metadata is absent", async () => {
    const { fetch } = makeFetchMock(() => ({
      status: 200,
      body: { exit_code: 0, stdout: "ok\n", stderr: "" },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const result = await client.exec("cmp_1", "true");

    assert.deepEqual(result, { exitCode: 0, stdout: "ok\n", stderr: "" });
  });

  it("exec() combines AbortSignal with the configured request timeout", async () => {
    const fetch: typeof globalThis.fetch = async (_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Timed out", "AbortError")),
          { once: true },
        );
      });
    const client = new ComputersClient({ ...makeConfig(fetch), timeoutMs: 5 });

    await assert.rejects(
      () => client.exec("cmp_1", "sleep 60", { signal: new AbortController().signal }),
      (error: unknown) => error instanceof CelestoNetworkError,
    );
  });

  it("execStream() parses fragmented SSE events and forwards AbortSignal", async () => {
    const encoder = new TextEncoder();
    const controller = new AbortController();
    let requestUrl = "";
    let requestBody: unknown;
    let requestSignal: AbortSignal | null | undefined;
    const fetch: typeof globalThis.fetch = async (input, init) => {
      requestUrl = String(input);
      requestBody = JSON.parse(String(init?.body));
      requestSignal = init?.signal;
      const body = new ReadableStream<Uint8Array>({
        start(streamController) {
          streamController.enqueue(
            encoder.encode(
              'data: {"type":"started","command_id":"cmd_1","started_at_unix_ms":10,',
            ),
          );
          streamController.enqueue(
            encoder.encode(
              '"timeout_seconds":60}\n\ndata: {"type":"stdout","data":"hello\\n"}\n',
            ),
          );
          streamController.enqueue(
            encoder.encode(
              'data: {"type":"stderr","data":"warn\\n"}\ndata: {"type":"exit","exit_code":0,"started_at_unix_ms":10,"ended_at_unix_ms":35,"duration_ms":25,"timed_out":false}\n',
            ),
          );
          streamController.close();
        },
      });
      return new Response(body, {
        status: 200,
        headers: {
          "content-type": "text/event-stream",
          "x-celesto-command-id": "cmd_1",
        },
      });
    };
    const client = new ComputersClient(makeConfig(fetch));

    const events = [];
    for await (const event of client.execStream("cmp_1", "echo hello", {
      timeout: 60,
      signal: controller.signal,
    })) {
      events.push(event);
    }

    assert.equal(requestUrl, "https://api.example.test/v1/computers/cmp_1/exec/stream");
    assert.deepEqual(requestBody, { command: "echo hello", timeout: 60 });
    assert.equal(requestSignal, controller.signal);
    assert.deepEqual(events, [
      { type: "started", commandId: "cmd_1", startedAtUnixMs: 10, timeoutSeconds: 60 },
      { type: "stdout", data: "hello\n" },
      { type: "stderr", data: "warn\n" },
      {
        type: "exit",
        exitCode: 0,
        commandId: "cmd_1",
        startedAtUnixMs: 10,
        endedAtUnixMs: 35,
        durationMs: 25,
        timedOut: false,
      },
    ]);
  });

  it("execStream() rejects malformed and invalid SSE payloads", async () => {
    const cases = [
      {
        payload: "{not json",
        message: "Celesto returned malformed JSON in the command stream.",
      },
      {
        payload: '{"type":"started","command_id":1}',
        message: "Celesto returned an invalid command-start event.",
      },
      {
        payload: '{"type":"exit","exit_code":"0"}',
        message: "Celesto returned an invalid command-exit event.",
      },
      {
        payload: '{"type":"future.event"}',
        message: "Celesto returned an unknown command stream event.",
      },
      {
        payload: "null",
        message: "Celesto returned an invalid command stream event.",
      },
    ];

    for (const testCase of cases) {
      const fetch: typeof globalThis.fetch = async () =>
        new Response(`data: ${testCase.payload}\n`, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      const client = new ComputersClient(makeConfig(fetch));

      await assert.rejects(
        async () => {
          for await (const _event of client.execStream("cmp_1", "true")) {
            // Invalid events must fail before they are yielded.
          }
        },
        (error: unknown) =>
          error instanceof Error && error.message === testCase.message,
      );
    }
  });

  it("execStream() finishes on exit without waiting for the server to close", async () => {
    const encoder = new TextEncoder();
    let cancelled = false;
    const fetch: typeof globalThis.fetch = async () => {
      const body = new ReadableStream<Uint8Array>({
        start(streamController) {
          streamController.enqueue(
            encoder.encode(
              'data: {"type":"exit","exit_code":0,"command_id":"cmd_1"}\n',
            ),
          );
        },
        cancel() {
          cancelled = true;
        },
      });
      return new Response(body, { status: 200 });
    };
    const client = new ComputersClient(makeConfig(fetch));
    const events = [];

    for await (const event of client.execStream("cmp_1", "true")) {
      events.push(event);
    }

    assert.deepEqual(events, [{ type: "exit", exitCode: 0, commandId: "cmd_1" }]);
    assert.equal(cancelled, true);
  });

  it("execStream() cancels the response body when iteration stops", async () => {
    const encoder = new TextEncoder();
    let cancelled = false;
    const fetch: typeof globalThis.fetch = async () => {
      const body = new ReadableStream<Uint8Array>({
        start(streamController) {
          streamController.enqueue(
            encoder.encode(
              'data: {"type":"started","command_id":"cmd_1","started_at_unix_ms":10,"timeout_seconds":60}\n',
            ),
          );
        },
        cancel() {
          cancelled = true;
        },
      });
      return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
    };
    const client = new ComputersClient(makeConfig(fetch));
    const iterator = client.execStream("cmp_1", "sleep 60");

    assert.equal((await iterator.next()).value?.type, "started");
    await iterator.return(undefined);

    assert.equal(cancelled, true);
  });

  it("execStream() wraps failures that happen after response headers", async () => {
    const encoder = new TextEncoder();
    const controller = new AbortController();
    const fetch: typeof globalThis.fetch = async (_input, init) => {
      const body = new ReadableStream<Uint8Array>({
        start(streamController) {
          streamController.enqueue(
            encoder.encode(
              'data: {"type":"started","command_id":"cmd_1","started_at_unix_ms":10,"timeout_seconds":60}\n',
            ),
          );
          init?.signal?.addEventListener(
            "abort",
            () => streamController.error(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        },
      });
      return new Response(body, { status: 200 });
    };
    const client = new ComputersClient(makeConfig(fetch));
    const iterator = client.execStream("cmp_1", "sleep 60", { signal: controller.signal });

    assert.equal((await iterator.next()).value?.type, "started");
    controller.abort();

    await assert.rejects(
      () => iterator.next(),
      (error: unknown) => error instanceof CelestoNetworkError,
    );
  });

  it("execStream() applies the configured request timeout to the full stream", async () => {
    const fetch: typeof globalThis.fetch = async (_input, init) => {
      const body = new ReadableStream<Uint8Array>({
        start(streamController) {
          init?.signal?.addEventListener(
            "abort",
            () => streamController.error(new DOMException("Timed out", "AbortError")),
            { once: true },
          );
        },
      });
      return new Response(body, { status: 200 });
    };
    const client = new ComputersClient({ ...makeConfig(fetch), timeoutMs: 5 });
    const iterator = client.execStream("cmp_1", "sleep 60");

    await assert.rejects(
      () => iterator.next(),
      (error: unknown) => error instanceof CelestoNetworkError,
    );
  });

  it("listCommandHistory() maps command records", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 200,
      body: {
        commands: [
          {
            command_id: "cmd_1",
            source: "api",
            status: "completed",
            started_at: "2026-07-10T12:00:00Z",
            ended_at: "2026-07-10T12:00:01Z",
            duration_ms: 1000,
            timeout_seconds: 30,
            exit_code: 0,
            stdout_bytes: 3,
            stderr_bytes: 0,
            error_type: null,
          },
        ],
        count: 1,
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const history = await client.listCommandHistory("cmp_1", { limit: 10 });

    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers/cmp_1/commands?limit=10");
    assert.deepEqual(history, {
      commands: [
        {
          commandId: "cmd_1",
          source: "api",
          status: "completed",
          startedAt: "2026-07-10T12:00:00Z",
          endedAt: "2026-07-10T12:00:01Z",
          durationMs: 1000,
          timeoutSeconds: 30,
          exitCode: 0,
          stdoutBytes: 3,
          stderrBytes: 0,
          errorType: null,
        },
      ],
      count: 1,
    });
  });

  it("stop/start/delete hit the right endpoints with the right methods", async () => {
    const hits: string[] = [];
    const { fetch } = makeFetchMock((call) => {
      hits.push(`${call.method} ${call.url}`);
      return {
        status: 200,
        body: {
          id: "cmp_1",
          name: "n",
          status: "stopping",
          vcpus: 1,
          ram_mb: 1024,
          disk_size_mb: 7168,
          image: "ubuntu-desktop-24.04",
          template_id: "scratch",
          created_at: "2026-04-16T00:00:00Z",
        },
      };
    });
    const client = new ComputersClient(makeConfig(fetch));

    await client.stop("cmp_1");
    await client.start("cmp_1");
    await client.delete("cmp_1");

    assert.deepEqual(hits, [
      "POST https://api.example.test/v1/computers/cmp_1/stop",
      "POST https://api.example.test/v1/computers/cmp_1/start",
      "DELETE https://api.example.test/v1/computers/cmp_1",
    ]);
  });

  it("published port methods hit the right endpoints and map response fields", async () => {
    const { fetch, calls } = makeFetchMock((call) => ({
      status: 200,
      body: call.method === "GET"
        ? [
            {
              id: "cpp_1",
              computer_id: "cmp_1",
              port: 8080,
              url: "https://p-test.celesto.ai",
              status: "published",
              created_at: "2026-04-16T00:00:00Z",
            },
          ]
        : {
            id: "cpp_1",
            computer_id: "cmp_1",
            port: 8080,
            url: call.method === "DELETE" ? null : "https://p-test.celesto.ai",
            status: call.method === "DELETE" ? "unpublished" : "published",
            created_at: "2026-04-16T00:00:00Z",
          },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const published = await client.publishPort("cmp_1", 8080);
    const ports = await client.listPublishedPorts("cmp_1");
    const unpublished = await client.unpublishPort("cmp_1", 8080);

    assert.equal(published.url, "https://p-test.celesto.ai");
    assert.equal(ports[0]!.computerId, "cmp_1");
    assert.equal(unpublished.status, "unpublished");
    assert.deepEqual(calls.map((call) => `${call.method} ${call.url}`), [
      "POST https://api.example.test/v1/computers/cmp_1/published-ports",
      "GET https://api.example.test/v1/computers/cmp_1/published-ports",
      "DELETE https://api.example.test/v1/computers/cmp_1/published-ports/8080",
    ]);
  });

  it("Computer convenience object supports properties, run, stop, and publishPort", async () => {
    const { fetch, calls } = makeFetchMock((call) => {
      if (call.url.endsWith("/exec")) {
        return { status: 200, body: { exit_code: 0, stdout: "hello\n", stderr: "" } };
      }
      if (call.url.endsWith("/stop")) {
        return {
          status: 200,
          body: {
            id: "cmp_1",
            name: "curie",
            status: "stopped",
            vcpus: 1,
            ram_mb: 512,
            disk_size_mb: 2048,
            image: "ubuntu-desktop-24.04",
            template_id: "scratch",
            created_at: "2026-04-16T00:00:00Z",
          },
        };
      }
      if (call.url.endsWith("/published-ports")) {
        return {
          status: 200,
          body: {
            id: "cpp_1",
            computer_id: "cmp_1",
            port: 8080,
            url: "https://p-test.celesto.ai",
            status: "published",
            created_at: "2026-04-16T00:00:00Z",
          },
        };
      }
      return {
        status: 201,
        body: {
          id: "cmp_1",
          name: "curie",
          status: "running",
          vcpus: 1,
          ram_mb: 512,
          disk_size_mb: 2048,
          image: "ubuntu-desktop-24.04",
          template_id: "scratch",
          created_at: "2026-04-16T00:00:00Z",
        },
      };
    });

    const computer = await Computer.create(
      { cpus: 1, memory: 512, disk: "2gb" },
      makeConfig(fetch),
    );
    const result = await computer.run("echo hello", { timeout: 60 });
    await computer.stop();
    const url = await computer.publishPort(8080);

    assert.equal(computer.name, "curie");
    assert.equal(computer["name"], "curie");
    assert.equal(computer.get("name"), "curie");
    assert.equal(result.stdout, "hello\n");
    assert.equal(computer.status, "stopped");
    assert.equal(url, "https://p-test.celesto.ai");
    assert.deepEqual(calls[0]!.body, {
      vcpus: 1,
      ram_mb: 512,
      disk_size_mb: 2048,
    });
  });

  it("throws CelestoApiError on non-2xx responses", async () => {
    const { fetch } = makeFetchMock(() => ({
      status: 404,
      body: { detail: "Computer not found" },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    await assert.rejects(
      () => client.get("cmp_missing"),
      (err: unknown) => {
        if (!(err instanceof CelestoApiError)) {
          return false;
        }
        assert.ok(err instanceof CelestoError, "CelestoApiError should extend CelestoError");
        assert.equal(err.status, 404);
        assert.equal(err.message, "Computer not found");
        return true;
      },
    );
  });

  it("wraps network failures in CelestoNetworkError", async () => {
    const failingFetch: typeof fetch = async () => {
      throw new TypeError("fetch failed");
    };
    const client = new ComputersClient(makeConfig(failingFetch));

    await assert.rejects(
      () => client.list(),
      (err: unknown) => {
        if (!(err instanceof CelestoNetworkError)) {
          return false;
        }
        assert.ok(err instanceof CelestoError, "CelestoNetworkError should extend CelestoError");
        assert.match(err.message, /fetch failed/);
        return true;
      },
    );
  });

  it("createTerminalSession() uses the direct terminal gateway API", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        terminal_id: "term_123",
        gateway_url: "wss://terminal-gateway.example/v1/terminals/term_123/connect",
        token: "token with spaces",
        expires_at: "2026-07-10T12:01:30Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const connection = await client.createTerminalSession("my-computer");

    assert.equal(calls.length, 1);
    assert.equal(calls[0]!.method, "POST");
    assert.equal(
      calls[0]!.url,
      "https://api.example.test/v1/computers/my-computer/terminals",
    );
    assert.deepEqual(connection, {
      terminalId: "term_123",
      gatewayUrl: "wss://terminal-gateway.example/v1/terminals/term_123/connect",
      url: "wss://terminal-gateway.example/v1/terminals/term_123/connect?token=token%20with%20spaces",
      token: "token with spaces",
      expiresAt: "2026-07-10T12:01:30Z",
      headers: {},
      firstMessage: "",
    });
  });

  it("getTerminalConnection() remains an alias for the gateway API", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: {
        terminal_id: "term_123",
        gateway_url: "wss://gateway.example/connect?region=us",
        token: "token",
        expires_at: "2026-07-10T12:01:30Z",
      },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const connection = await client.getTerminalConnection("cmp_1");

    assert.equal(calls[0]!.url, "https://api.example.test/v1/computers/cmp_1/terminals");
    assert.equal(connection.url, "wss://gateway.example/connect?region=us&token=token");
  });
});

describe("internet policy", () => {
  it("allows an explicit open policy with a persistent home", async () => {
    const { fetch, calls } = makeFetchMock(() => ({
      status: 201,
      body: { id: "cmp_open", network_policy: { mode: "open" } },
    }));
    const client = new ComputersClient(makeConfig(fetch));

    const info = await client.create({
      networkPolicy: { mode: "open" },
      persistentHome: true,
    });

    assert.deepEqual(calls[0]!.body, {
      network_policy: { mode: "open" },
      external_volume_enabled: true,
    });
    assert.deepEqual(info.networkPolicy, { mode: "open" });
  });

  it("sends the off policy and reads it from the response", async () => {
    const { fetch, calls } = makeFetchMock(() => ({ status: 201, body: { id: "cmp_off", network_policy: { mode: "off" } } }));
    const client = new ComputersClient(makeConfig(fetch));
    const info = await client.create({ networkPolicy: { mode: "off" } });
    assert.deepEqual(calls[0]!.body, { network_policy: { mode: "off" } });
    assert.deepEqual(info.networkPolicy, { mode: "off" });
  });
  it("rejects an external volume with internet off before sending", async () => {
    const { fetch, calls } = makeFetchMock(() => ({ status: 201, body: {} }));
    const client = new ComputersClient(makeConfig(fetch));
    await assert.rejects(client.create({ networkPolicy: { mode: "off" }, persistentHome: true }), /External volumes require internet/);
    assert.equal(calls.length, 0);
  });

  it("rejects malformed policies before sending", async () => {
    const invalidPolicies: unknown[] = [
      null,
      { mode: "restricted" },
      { mode: "off", allowedDomains: ["example.com"] },
      { policy: "off" },
    ];

    for (const networkPolicy of invalidPolicies) {
      const { fetch, calls } = makeFetchMock(() => ({ status: 201, body: {} }));
      const client = new ComputersClient(makeConfig(fetch));

      await assert.rejects(
        client.create({ networkPolicy } as CreateComputerParams),
        /networkPolicy/,
      );
      assert.equal(calls.length, 0);
    }
  });
});
