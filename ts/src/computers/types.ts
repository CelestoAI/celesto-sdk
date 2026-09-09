export type ComputerStatus =
  | "creating"
  | "running"
  | "stopping"
  | "stopped"
  | "starting"
  | "restoring"
  | "restorable"
  | "deleting"
  | "deleted"
  | "error";

export interface ComputerConnectionInfo {
  ssh?: string;
  accessUrl?: string;
}

export type PublishedPortStatus =
  | "publishing"
  | "published"
  | "unpublishing"
  | "unpublished"
  | "error";

export interface ComputerPublishedPortInfo {
  id?: string | null;
  computerId: string;
  port: number;
  url?: string | null;
  status: PublishedPortStatus;
  createdAt?: string | null;
}

export interface NetworkPolicy {
  mode: "open" | "off";
}

export interface ComputerInfo {
  networkPolicy?: NetworkPolicy;
  id: string;
  name: string;
  status: ComputerStatus;
  vcpus: number;
  ramMb: number;
  diskSizeMb: number;
  image: string;
  templateId: string;
  templateVersion?: string | null;
  /** Whether /home/ohm survives stop and restore. */
  persistentHome: boolean;
  connection?: ComputerConnectionInfo;
  publishedPorts?: ComputerPublishedPortInfo[];
  lastError?: string | null;
  createdAt: string;
  stoppedAt?: string | null;
}

export interface ComputerListResponse {
  computers: ComputerInfo[];
  count: number;
}

export interface ListComputersParams {
  /** Optional status filter, such as "running" or "stopped". */
  status?: ComputerStatus;
  /** Optional template filter, such as "coding-agent". */
  templateId?: string;
  /** Optional project ID filter. */
  projectId?: string;
  /** Optional maximum number of computers to return. */
  limit?: number;
}

export interface ComputerExecResponse {
  exitCode: number;
  stdout: string;
  stderr: string;
  commandId?: string | null;
  durationMs?: number | null;
  timedOut?: boolean | null;
}

export type ComputerExecStreamEvent =
  | {
      type: "started";
      commandId: string;
      startedAtUnixMs: number;
      timeoutSeconds: number;
    }
  | {
      type: "stdout" | "stderr";
      data: string;
    }
  | {
      type: "exit";
      exitCode: number;
      commandId?: string;
      startedAtUnixMs?: number;
      endedAtUnixMs?: number;
      durationMs?: number;
      timedOut?: boolean;
    };

export interface ComputerCommandHistoryEntry {
  commandId: string;
  source: string;
  status: string;
  startedAt?: string | null;
  endedAt?: string | null;
  durationMs?: number | null;
  timeoutSeconds?: number | null;
  exitCode?: number | null;
  stdoutBytes?: number | null;
  stderrBytes?: number | null;
  errorType?: string | null;
}

export interface ComputerCommandHistoryResponse {
  commands: ComputerCommandHistoryEntry[];
  count: number;
}

export interface SandboxTemplateInfo {
  id: string;
  displayName: string;
  description: string;
  defaultVcpus: number;
  defaultRamMb: number;
  defaultDiskSizeMb: number;
  version?: string | null;
  experimental: boolean;
}

export interface CreateComputerParams {
  /** Outbound internet access, fixed at creation. Defaults to open. */
  networkPolicy?: NetworkPolicy;
  /** Number of virtual CPUs (1-16). Alias for vcpus. */
  cpus?: number;
  /** Number of virtual CPUs (1-16). */
  vcpus?: number;
  /** Memory in MB (512-32768). Alias for ramMb. */
  memory?: number;
  /** Memory in MB (512-32768). */
  ramMb?: number;
  /** Disk size as MB or a string like "2gb". Alias for diskSizeMb. */
  disk?: number | string;
  /** Disk size in MB (512-51200). */
  diskSizeMb?: number;
  /** Legacy OS image selector. */
  image?: string;
  /** Sandbox template id, such as "scratch" or "coding-agent". */
  templateId?: string;
  /** Optional immutable template version. */
  templateVersion?: string;
  /** Keep /home/ohm across stop and restore. Off by default and immutable after create. */
  persistentHome?: boolean;
}

export interface ExecParams {
  /** Timeout in seconds (1-300). Defaults to 30. */
  timeout?: number;
  /** Abort the HTTP request. Streaming requests also stop the remote command. */
  signal?: AbortSignal;
}

export interface ListCommandHistoryParams {
  /** Maximum command records to return (1-200). Defaults to 50. */
  limit?: number;
}

/** Legacy WebSocket connection fields retained for source compatibility. */
export interface TerminalConnectionInfo {
  /** Authenticated wss:// URL ready to pass to a WebSocket constructor. */
  url: string;
  /** @deprecated The fast terminal gateway does not require custom headers. */
  headers: Record<string, string>;
  /** @deprecated The fast terminal gateway does not require a first message. */
  firstMessage: string;
}

/** A short-lived direct connection to Celesto's fast terminal gateway. */
export interface TerminalSessionInfo extends TerminalConnectionInfo {
  /** Durable terminal session ID. */
  terminalId: string;
  /** Gateway URL without credentials. */
  gatewayUrl: string;
  /** Short-lived terminal token. Treat this value as a secret. */
  token: string;
  /** ISO 8601 expiry time for the terminal token. */
  expiresAt: string;
}
