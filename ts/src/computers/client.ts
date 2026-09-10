import { buildRequestContext, ClientConfig, RequestOverrides } from "../core/config";
import { CelestoNetworkError } from "../core/errors";
import { request, requestStream } from "../core/http";
import {
  ComputerCommandHistoryEntry,
  ComputerCommandHistoryResponse,
  ComputerConnectionInfo,
  ComputerExecResponse,
  ComputerExecStreamEvent,
  ComputerInfo,
  ComputerListResponse,
  NetworkPolicy,
  ComputerPublishedPortInfo,
  ComputerStatus,
  CreateComputerParams,
  ExecParams,
  ListCommandHistoryParams,
  ListComputersParams,
  SandboxTemplateInfo,
  TerminalSessionInfo,
} from "./types";

interface ComputerConnectionInfoWire {
  ssh?: string | null;
  access_url?: string | null;
}

interface ComputerPublishedPortInfoWire {
  id?: string | null;
  computer_id: string;
  port: number;
  url?: string | null;
  status: ComputerPublishedPortInfo["status"];
  created_at?: string | null;
}

interface ComputerInfoWire {
  network_policy?: NetworkPolicy;
  id: string;
  name: string;
  status: ComputerStatus;
  vcpus: number;
  ram_mb: number;
  disk_size_mb: number;
  image: string;
  template_id: string;
  template_version?: string | null;
  external_volume_enabled?: boolean;
  connection?: ComputerConnectionInfoWire | null;
  published_ports?: ComputerPublishedPortInfoWire[];
  last_error?: string | null;
  created_at: string;
  stopped_at?: string | null;
}

interface ComputerListResponseWire {
  computers: ComputerInfoWire[];
  count: number;
}

interface ComputerExecResponseWire {
  exit_code: number;
  stdout: string;
  stderr: string;
  command_id?: string | null;
  duration_ms?: number | null;
  timed_out?: boolean | null;
}

interface ComputerCommandHistoryEntryWire {
  command_id: string;
  source: string;
  status: string;
  started_at?: string | null;
  ended_at?: string | null;
  duration_ms?: number | null;
  timeout_seconds?: number | null;
  exit_code?: number | null;
  stdout_bytes?: number | null;
  stderr_bytes?: number | null;
  error_type?: string | null;
}

interface ComputerCommandHistoryResponseWire {
  commands: ComputerCommandHistoryEntryWire[];
  count: number;
}

interface TerminalConnectionInfoWire {
  terminal_id: string;
  gateway_url: string;
  token: string;
  expires_at: string;
}

interface SandboxTemplateInfoWire {
  id: string;
  display_name: string;
  description: string;
  default_vcpus: number;
  default_ram_mb: number;
  default_disk_size_mb: number;
  version?: string | null;
  experimental: boolean;
}

const toConnection = (
  payload: ComputerConnectionInfoWire | null | undefined,
): ComputerConnectionInfo | undefined => {
  if (!payload) {
    return undefined;
  }
  const out: ComputerConnectionInfo = {};
  if (payload.ssh != null) {
    out.ssh = payload.ssh;
  }
  if (payload.access_url != null) {
    out.accessUrl = payload.access_url;
  }
  return out;
};

const toPublishedPortInfo = (payload: ComputerPublishedPortInfoWire): ComputerPublishedPortInfo => ({
  id: payload.id ?? null,
  computerId: payload.computer_id,
  port: payload.port,
  url: payload.url ?? null,
  status: payload.status,
  createdAt: payload.created_at ?? null,
});

const toComputerInfo = (payload: ComputerInfoWire): ComputerInfo => ({
  id: payload.id,
  name: payload.name,
  status: payload.status,
  vcpus: payload.vcpus,
  ramMb: payload.ram_mb,
  diskSizeMb: payload.disk_size_mb,
  image: payload.image,
  templateId: payload.template_id,
  templateVersion: payload.template_version ?? null,
  persistentHome: payload.external_volume_enabled ?? false,
  networkPolicy: payload.network_policy ?? { mode: "open" },
  connection: toConnection(payload.connection),
  publishedPorts: payload.published_ports?.map(toPublishedPortInfo),
  lastError: payload.last_error ?? null,
  createdAt: payload.created_at,
  stoppedAt: payload.stopped_at ?? null,
});

const toExecResponse = (payload: ComputerExecResponseWire): ComputerExecResponse => {
  const response: ComputerExecResponse = {
    exitCode: payload.exit_code,
    stdout: payload.stdout,
    stderr: payload.stderr,
  };
  if (payload.command_id !== undefined) response.commandId = payload.command_id;
  if (payload.duration_ms !== undefined) response.durationMs = payload.duration_ms;
  if (payload.timed_out !== undefined) response.timedOut = payload.timed_out;
  return response;
};

const toCommandHistoryEntry = (
  payload: ComputerCommandHistoryEntryWire,
): ComputerCommandHistoryEntry => ({
  commandId: payload.command_id,
  source: payload.source,
  status: payload.status,
  startedAt: payload.started_at,
  endedAt: payload.ended_at,
  durationMs: payload.duration_ms,
  timeoutSeconds: payload.timeout_seconds,
  exitCode: payload.exit_code,
  stdoutBytes: payload.stdout_bytes,
  stderrBytes: payload.stderr_bytes,
  errorType: payload.error_type,
});

const toTerminalConnectionInfo = (
  payload: TerminalConnectionInfoWire,
): TerminalSessionInfo => {
  const separator = payload.gateway_url.includes("?") ? "&" : "?";
  return {
    terminalId: payload.terminal_id,
    gatewayUrl: payload.gateway_url,
    url: `${payload.gateway_url}${separator}token=${encodeURIComponent(payload.token)}`,
    token: payload.token,
    expiresAt: payload.expires_at,
    headers: {},
    firstMessage: "",
  };
};

const toSandboxTemplateInfo = (payload: SandboxTemplateInfoWire): SandboxTemplateInfo => ({
  id: payload.id,
  displayName: payload.display_name,
  description: payload.description,
  defaultVcpus: payload.default_vcpus,
  defaultRamMb: payload.default_ram_mb,
  defaultDiskSizeMb: payload.default_disk_size_mb,
  version: payload.version ?? null,
  experimental: payload.experimental,
});

const diskUnitsToMb: Record<string, number> = {
  "": 1,
  m: 1,
  mb: 1,
  mib: 1,
  g: 1024,
  gb: 1024,
  gib: 1024,
  t: 1024 * 1024,
  tb: 1024 * 1024,
  tib: 1024 * 1024,
};

const isAsciiDigit = (char: string): boolean => char >= "0" && char <= "9";
const isAsciiLetter = (char: string): boolean =>
  (char >= "a" && char <= "z") || (char >= "A" && char <= "Z");
const isSeparatorWhitespace = (char: string): boolean => char === " " || char === "\t";

const parseDiskString = (disk: string): { amount: string; unit: string } | undefined => {
  const value = disk.trim();
  if (!value) {
    return undefined;
  }

  let index = 0;
  let digitCount = 0;
  let hasDecimalPoint = false;
  while (index < value.length) {
    const char = value[index]!;
    if (isAsciiDigit(char)) {
      digitCount += 1;
      index += 1;
      continue;
    }
    if (char === "." && !hasDecimalPoint) {
      hasDecimalPoint = true;
      index += 1;
      continue;
    }
    break;
  }

  if (digitCount === 0 || value[index - 1] === ".") {
    return undefined;
  }

  const amount = value.slice(0, index);
  while (index < value.length && isSeparatorWhitespace(value[index]!)) {
    index += 1;
  }

  const unit = value.slice(index);
  if ([...unit].some((char) => !isAsciiLetter(char))) {
    return undefined;
  }

  return { amount, unit };
};

const parseDiskSizeMb = (disk: number | string | undefined): number | undefined => {
  if (disk === undefined) {
    return undefined;
  }

  if (typeof disk === "number") {
    if (!Number.isInteger(disk) || disk <= 0) {
      throw new Error("disk as a number must be a whole number of MB.");
    }
    return disk;
  }

  const parsedDisk = parseDiskString(disk);
  if (!parsedDisk) {
    throw new Error("disk must be a size in MB or a string like '2gb'.");
  }

  const multiplier = diskUnitsToMb[parsedDisk.unit.toLowerCase()];
  if (multiplier === undefined) {
    throw new Error("disk must use MB, GB, or TB, for example '2048mb' or '2gb'.");
  }

  const sizeMb = Number(parsedDisk.amount) * multiplier;
  if (!Number.isInteger(sizeMb) || sizeMb <= 0) {
    throw new Error("disk must resolve to a whole number of MB, for example '1536mb' or '1.5gb'.");
  }
  return sizeMb;
};

const buildCreateComputerBody = (params: CreateComputerParams): Record<string, unknown> => {
  if (params.cpus !== undefined && params.vcpus !== undefined && params.cpus !== params.vcpus) {
    throw new Error("cpus and vcpus must have the same value when both are provided.");
  }
  if (params.memory !== undefined && params.ramMb !== undefined && params.memory !== params.ramMb) {
    throw new Error("memory and ramMb must have the same value when both are provided.");
  }

  const parsedDiskSizeMb = parseDiskSizeMb(params.disk);
  if (
    parsedDiskSizeMb !== undefined &&
    params.diskSizeMb !== undefined &&
    parsedDiskSizeMb !== params.diskSizeMb
  ) {
    throw new Error("disk and diskSizeMb must have the same value when both are provided.");
  }

  const body: Record<string, unknown> = {};
  if (params.networkPolicy !== undefined) {
    const policy = params.networkPolicy;
    if (!policy || Object.keys(policy).length !== 1 || !("mode" in policy) || !["open", "off"].includes(policy.mode)) {
      throw new Error('networkPolicy must be {mode: "open"} or {mode: "off"}.');
    }
    if (policy.mode === "off" && params.persistentHome) {
      throw new Error("External volumes require internet access; set persistentHome=false.");
    }
    body.network_policy = { mode: policy.mode };
  }
  const vcpus = params.vcpus ?? params.cpus;
  const ramMb = params.ramMb ?? params.memory;
  const diskSizeMb = params.diskSizeMb ?? parsedDiskSizeMb;
  if (vcpus !== undefined) {
    body.vcpus = vcpus;
  }
  if (ramMb !== undefined) {
    body.ram_mb = ramMb;
  }
  if (diskSizeMb !== undefined) {
    body.disk_size_mb = diskSizeMb;
  }
  if (params.image !== undefined) {
    body.image = params.image;
  }
  if (params.templateId !== undefined) {
    body.template_id = params.templateId;
  }
  if (params.templateVersion !== undefined) {
    body.template_version = params.templateVersion;
  }
  if (params.persistentHome !== undefined) {
    body.external_volume_enabled = params.persistentHome;
  }
  return body;
};

const computersPath = (path: string): string => `/v1/computers${path}`;

const pickOverrides = (options?: RequestOverrides): RequestOverrides => ({
  headers: options?.headers,
  signal: options?.signal,
});

const optionalNumber = (value: unknown): number | undefined =>
  typeof value === "number" ? value : undefined;

const optionalBoolean = (value: unknown): boolean | undefined =>
  typeof value === "boolean" ? value : undefined;

const parseExecStreamEvent = (value: unknown): ComputerExecStreamEvent => {
  if (!value || typeof value !== "object") {
    throw new Error("Celesto returned an invalid command stream event.");
  }

  const event = value as Record<string, unknown>;
  if (event.type === "stdout" || event.type === "stderr") {
    if (typeof event.data !== "string") {
      throw new Error("Celesto returned command output without text data.");
    }
    return { type: event.type, data: event.data };
  }

  if (event.type === "started") {
    if (
      typeof event.command_id !== "string" ||
      typeof event.started_at_unix_ms !== "number" ||
      typeof event.timeout_seconds !== "number"
    ) {
      throw new Error("Celesto returned an invalid command-start event.");
    }
    return {
      type: "started",
      commandId: event.command_id,
      startedAtUnixMs: event.started_at_unix_ms,
      timeoutSeconds: event.timeout_seconds,
    };
  }

  if (event.type === "exit") {
    if (typeof event.exit_code !== "number") {
      throw new Error("Celesto returned an invalid command-exit event.");
    }
    const result: Extract<ComputerExecStreamEvent, { type: "exit" }> = {
      type: "exit",
      exitCode: event.exit_code,
    };
    if (typeof event.command_id === "string") result.commandId = event.command_id;
    const startedAtUnixMs = optionalNumber(event.started_at_unix_ms);
    const endedAtUnixMs = optionalNumber(event.ended_at_unix_ms);
    const durationMs = optionalNumber(event.duration_ms);
    const timedOut = optionalBoolean(event.timed_out);
    if (startedAtUnixMs !== undefined) result.startedAtUnixMs = startedAtUnixMs;
    if (endedAtUnixMs !== undefined) result.endedAtUnixMs = endedAtUnixMs;
    if (durationMs !== undefined) result.durationMs = durationMs;
    if (timedOut !== undefined) result.timedOut = timedOut;
    return result;
  }

  throw new Error("Celesto returned an unknown command stream event.");
};

const parseSseDataLine = (line: string): ComputerExecStreamEvent | undefined => {
  const text = line.trim();
  if (!text || !text.startsWith("data:")) {
    return undefined;
  }
  const data = text.slice("data:".length).trim();
  if (!data || data === "[DONE]") {
    return undefined;
  }
  try {
    return parseExecStreamEvent(JSON.parse(data));
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error("Celesto returned malformed JSON in the command stream.");
    }
    throw error;
  }
};

const createManagedSignal = (
  signal: AbortSignal | undefined,
  timeoutMs: number | undefined,
): { signal: AbortSignal | undefined; cleanup: () => void } => {
  if (!timeoutMs || timeoutMs <= 0) {
    return { signal, cleanup: () => {} };
  }

  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) {
    abort();
  } else {
    signal?.addEventListener("abort", abort, { once: true });
  }
  const timer = setTimeout(abort, timeoutMs);

  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    },
  };
};

const toNetworkError = (error: unknown): CelestoNetworkError => {
  if (error instanceof CelestoNetworkError) return error;
  const cause = error instanceof Error ? error : new Error(String(error));
  return new CelestoNetworkError(cause.message, cause);
};

const withFallbackCommandId = (
  event: ComputerExecStreamEvent,
  commandId: string | undefined,
): ComputerExecStreamEvent => {
  if (event.type !== "exit" || event.commandId || !commandId) return event;
  return { ...event, commandId };
};

/**
 * Client for managing sandboxed computers (AI sandboxes).
 *
 * Provides computer lifecycle, buffered and streaming command execution,
 * command history, published ports, and direct terminal gateway sessions.
 *
 * @example
 * ```ts
 * const computer = await Computer.create();
 * const result = await computer.run("uname -a");
 * console.log(result.stdout);
 * await computer.delete();
 * ```
 */
export class ComputersClient {
  private readonly config: ClientConfig;

  constructor(config: ClientConfig) {
    this.config = config;
  }

  async create(params: CreateComputerParams = {}, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "POST",
      path: computersPath(""),
      body: buildCreateComputerBody(params),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async listTemplates(options?: RequestOverrides): Promise<SandboxTemplateInfo[]> {
    const ctx = buildRequestContext(this.config);
    const data = await request<SandboxTemplateInfoWire[]>(ctx, {
      method: "GET",
      path: computersPath("/templates"),
      ...pickOverrides(options),
    });
    return data.map(toSandboxTemplateInfo);
  }

  async list(params: ListComputersParams = {}, options?: RequestOverrides): Promise<ComputerListResponse> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerListResponseWire>(ctx, {
      method: "GET",
      path: computersPath(""),
      query: {
        status: params.status,
        template_id: params.templateId,
        project_id: params.projectId,
        limit: params.limit,
      },
      ...pickOverrides(options),
    });
    return {
      computers: data.computers.map(toComputerInfo),
      count: data.count,
    };
  }

  async get(computerId: string, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "GET",
      path: computersPath(`/${encodeURIComponent(computerId)}`),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async exec(
    computerId: string,
    command: string,
    params: ExecParams = {},
    options?: RequestOverrides,
  ): Promise<ComputerExecResponse> {
    const ctx = buildRequestContext(this.config);
    const managedSignal = createManagedSignal(
      params.signal ?? options?.signal,
      this.config.timeoutMs,
    );
    try {
      const data = await request<ComputerExecResponseWire>(ctx, {
        method: "POST",
        path: computersPath(`/${encodeURIComponent(computerId)}/exec`),
        body: {
          command,
          timeout: params.timeout ?? 30,
        },
        headers: options?.headers,
        signal: managedSignal.signal,
      });
      return toExecResponse(data);
    } finally {
      managedSignal.cleanup();
    }
  }

  async *execStream(
    computerId: string,
    command: string,
    params: ExecParams = {},
    options?: RequestOverrides,
  ): AsyncGenerator<ComputerExecStreamEvent> {
    const ctx = buildRequestContext(this.config);
    const managedSignal = createManagedSignal(
      params.signal ?? options?.signal,
      this.config.timeoutMs,
    );
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let completed = false;

    try {
      const response = await requestStream(ctx, {
        method: "POST",
        path: computersPath(`/${encodeURIComponent(computerId)}/exec/stream`),
        body: {
          command,
          timeout: params.timeout ?? 30,
        },
        headers: options?.headers,
        signal: managedSignal.signal,
      });
      if (!response.body) {
        throw new Error("Celesto did not return a command output stream.");
      }

      const responseCommandId = response.headers.get("x-celesto-command-id") ?? undefined;
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try {
          chunk = await reader.read();
        } catch (error) {
          throw toNetworkError(error);
        }
        if (chunk.done) {
          completed = true;
          buffer += decoder.decode();
          break;
        }
        buffer += decoder.decode(chunk.value, { stream: true });

        let newlineIndex = buffer.indexOf("\n");
        while (newlineIndex !== -1) {
          const line = buffer.slice(0, newlineIndex).replace(/\r$/, "");
          buffer = buffer.slice(newlineIndex + 1);
          const parsed = parseSseDataLine(line);
          if (parsed) {
            const event = withFallbackCommandId(parsed, responseCommandId);
            yield event;
            if (event.type === "exit") return;
          }
          newlineIndex = buffer.indexOf("\n");
        }
      }

      if (buffer) {
        const parsed = parseSseDataLine(buffer);
        if (parsed) {
          const event = withFallbackCommandId(parsed, responseCommandId);
          yield event;
          if (event.type === "exit") return;
        }
      }
      throw new Error("Command stream ended before Celesto returned an exit status.");
    } finally {
      if (reader) {
        if (!completed) {
          try {
            await reader.cancel();
          } catch {
            // The request may already be aborted or disconnected.
          }
        }
        reader.releaseLock();
      }
      managedSignal.cleanup();
    }
  }

  async listCommandHistory(
    computerId: string,
    params: ListCommandHistoryParams = {},
    options?: RequestOverrides,
  ): Promise<ComputerCommandHistoryResponse> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerCommandHistoryResponseWire>(ctx, {
      method: "GET",
      path: computersPath(`/${encodeURIComponent(computerId)}/commands`),
      query: { limit: params.limit },
      ...pickOverrides(options),
    });
    return {
      commands: data.commands.map(toCommandHistoryEntry),
      count: data.count,
    };
  }

  async stop(computerId: string, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "POST",
      path: computersPath(`/${encodeURIComponent(computerId)}/stop`),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async start(computerId: string, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "POST",
      path: computersPath(`/${encodeURIComponent(computerId)}/start`),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async delete(computerId: string, options?: RequestOverrides): Promise<ComputerInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerInfoWire>(ctx, {
      method: "DELETE",
      path: computersPath(`/${encodeURIComponent(computerId)}`),
      ...pickOverrides(options),
    });
    return toComputerInfo(data);
  }

  async publishPort(
    computerId: string,
    port = 8000,
    options?: RequestOverrides,
  ): Promise<ComputerPublishedPortInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerPublishedPortInfoWire>(ctx, {
      method: "POST",
      path: computersPath(`/${encodeURIComponent(computerId)}/published-ports`),
      body: { port },
      ...pickOverrides(options),
    });
    return toPublishedPortInfo(data);
  }

  async listPublishedPorts(
    computerId: string,
    options?: RequestOverrides,
  ): Promise<ComputerPublishedPortInfo[]> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerPublishedPortInfoWire[]>(ctx, {
      method: "GET",
      path: computersPath(`/${encodeURIComponent(computerId)}/published-ports`),
      ...pickOverrides(options),
    });
    return data.map(toPublishedPortInfo);
  }

  async unpublishPort(
    computerId: string,
    port = 8000,
    options?: RequestOverrides,
  ): Promise<ComputerPublishedPortInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<ComputerPublishedPortInfoWire>(ctx, {
      method: "DELETE",
      path: computersPath(`/${encodeURIComponent(computerId)}/published-ports/${port}`),
      ...pickOverrides(options),
    });
    return toPublishedPortInfo(data);
  }

  /** Create a short-lived direct connection to Celesto's terminal gateway. */
  async createTerminalSession(
    computerIdOrName: string,
    options?: RequestOverrides,
  ): Promise<TerminalSessionInfo> {
    const ctx = buildRequestContext(this.config);
    const data = await request<TerminalConnectionInfoWire>(ctx, {
      method: "POST",
      path: computersPath(`/${encodeURIComponent(computerIdOrName)}/terminals`),
      ...pickOverrides(options),
    });
    return toTerminalConnectionInfo(data);
  }

  /** @deprecated Use createTerminalSession(). */
  async getTerminalConnection(
    computerIdOrName: string,
    options?: RequestOverrides,
  ): Promise<TerminalSessionInfo> {
    return this.createTerminalSession(computerIdOrName, options);
  }
}
