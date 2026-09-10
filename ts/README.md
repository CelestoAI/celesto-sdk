# @celestoai/sdk

Use this package to run work in Celesto from a Node.js app. Your code can create
a cloud computer, run commands in it, and delete it when the work is done.

An AI agent is software that can plan and run tasks. A harness is the code that
starts, tests, or supervises an agent.

Use this package when you want to:

- Run an AI agent or harness in a clean computer.
- Run shell commands from JavaScript or TypeScript.
- Keep agent work separate from your laptop, server, or production system.
- Run an agent for each of your own users, with a spending limit per user.
- Ask a user to approve access to Google Drive through Gatekeeper.

Gatekeeper is Celesto's access helper. It lets a user approve which external
files or folders your app can use.

## Requirements

- Node.js 18 or newer.
- A Celesto API key from [Celesto Settings](https://celesto.ai) under
  **Settings > Security**.

## Install

```bash
npm install @celestoai/sdk
```

Sign in once with the Celesto CLI:

```bash
pip install celesto
celesto auth login
```

The `Computer` API checks an explicitly passed `token` or `apiKey` first, then `CELESTO_API_KEY` in the shell, the current project's `.env`, and credentials saved by `celesto auth login`. You can use a local `.env` instead of the CLI:

```bash .env
CELESTO_API_KEY="your-api-key"
```

Add `.env` to `.gitignore`.

## Quickstart

Create a file named `quickstart.mjs`:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create();
try {
  console.log(`Computer ready: ${computer.name}`);

  const result = await computer.run("uname -a");
  console.log(result.stdout);
} finally {
  await computer.delete();
}
```

Run it:

```bash
node quickstart.mjs
```

## Run Agents for Your Users

If you are building a product on top of an AI agent, every run happens for one
of *your* users. Celesto keeps them apart: each run is recorded against the user
it acted for, so you can see what that person's agent did and what it cost, and
stop it from spending more than you allow.

You identify each of your users with a string you already have — a database ID,
an email, anything. Celesto stores it as you send it. There is no Celesto user
ID to look up and no mapping table to keep.

This example creates an agent, runs it for one user, prints the answer as it
arrives, and then reads that user's spending.

```ts
import { ManagedAgentsClient } from "@celestoai/sdk";

const celesto = new ManagedAgentsClient({ apiKey: process.env.CELESTO_API_KEY });

const agent = await celesto.agents.create({
  name: "support-bot",
  model: "openai/gpt-5.4-mini",
  instructions: "Answer order questions in one short paragraph.",
});

for await (const event of celesto.runs.stream(agent.id, {
  input: "Where is my order?",
  endUserId: "usr_8837",
})) {
  if (event.name === "message.delta") process.stdout.write(event.data.text ?? "");
}

const { budget } = await celesto.endUsers.get("usr_8837");
console.log(`\nSpent ${budget.spentUsd} of ${budget.capUsd}`);
```

Switching on `event.name` narrows the event, so `event.data` is typed for that
event and nothing else.

### Wait Instead of Streaming

`stream()` gives you the answer as it is written. `create()` waits and gives you
the finished run:

```ts
import { ManagedAgentsClient } from "@celestoai/sdk";

const celesto = new ManagedAgentsClient({ apiKey: process.env.CELESTO_API_KEY });
const agentId = "agt_your_agent_id";

const run = await celesto.runs.create(agentId, {
  input: "Where is my order?",
  endUserId: "usr_8837",
});
console.log(run.output, run.usage.costUsd);
```

### Money Is a String

Every amount — `costUsd`, `spentUsd`, `capUsd` — is a decimal string such as
`"0.000450"`, never a `number`. A single answer can cost a few millionths of a
dollar, which a JavaScript number cannot hold exactly. Display and compare the
string; if you need arithmetic, use a decimal library rather than `parseFloat`.

Writes are strings too. `budgetCapUsd` is typed `string`, so a number fails to
compile, and passing one anyway throws rather than sending it — `0.1 + 0.2`
stringifies to `"0.30000000000000004"`, and the only place that can still be
fixed is before it leaves your program.

### Set a Spending Limit

Give one user a cap, or set the default for everyone:

```ts
import { ManagedAgentsClient } from "@celestoai/sdk";

const celesto = new ManagedAgentsClient({ apiKey: process.env.CELESTO_API_KEY });

await celesto.endUsers.update("usr_8837", { budgetCapUsd: "5.00" });
await celesto.settings.update({ defaultEndUserBudgetUsd: "0.50" });
```

The cap covers a 30-day window that starts the first time that user runs
anything. When it runs out, the next run throws `BudgetExceededError`, and a run
already in flight stops at its next step with a `run.failed` event.

### Retry Safely

Pass `idempotencyKey` to make a retry safe: sending the same key again returns
the run that already happened instead of running the agent — and charging your
user — twice.

```ts
import { ManagedAgentsClient } from "@celestoai/sdk";

const celesto = new ManagedAgentsClient({ apiKey: process.env.CELESTO_API_KEY });
const agentId = "agt_your_agent_id";

const run = await celesto.runs.create(agentId, {
  input: "Where is my order?",
  endUserId: "usr_8837",
  idempotencyKey: "order-status-42",
});
```

One conversation runs one agent at a time. If a second run arrives while the
first is still going, Celesto throws `SessionBusyError`. Pass `maxRetries: 2` to
wait and try again; the SDK creates an idempotency key for you when you do.

### Keep the Conversation Going

Every run belongs to a session, which is that user's transcript. Leave
`sessionId` out and Celesto starts one; pass it back to continue:

```ts
import { ManagedAgentsClient } from "@celestoai/sdk";

const celesto = new ManagedAgentsClient({ apiKey: process.env.CELESTO_API_KEY });
const agentId = "agt_your_agent_id";

const first = await celesto.runs.create(agentId, {
  input: "Hello",
  endUserId: "usr_8837",
});
const followUp = await celesto.runs.create(agentId, {
  input: "And the one before that?",
  endUserId: "usr_8837",
  sessionId: first.sessionId,
});
```

### Change an Agent

Updating an agent saves a new version and leaves the old ones readable. Runs
remember the version they used, so a change never rewrites what already
happened. `celesto.agents.activateVersion(agent.id, 1)` goes back.

## Computers

A computer is a disposable cloud machine for your app or agent. By default,
Celesto creates a `scratch` computer, which is a minimal Ubuntu computer.

### Create with Custom Resources

Create a file named `create-computer.mjs`:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create({
  cpus: 2,
  memory: 2048,
  disk: "15gb",
});

try {
  console.log(computer.name, computer["name"]);
} finally {
  await computer.delete();
}
```

Omit CPU, memory, or disk fields to use the default size. `disk` accepts MB as
an integer or strings such as `"2gb"`.

Computers are ephemeral by default. To keep `/home/ohm` across stop and restore,
enable a persistent home when you create the computer:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create({ persistentHome: true });
```

This setting cannot be changed later.

### Control Internet Access

Internet is on by default. Disable outbound connections when you create a
computer:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create({ networkPolicy: { mode: "off" } });
try {
  console.log((await computer.run("uname -a")).stdout);
} finally {
  await computer.delete();
}
```

Commands and terminal sessions still work without internet access. The policy
survives stop/start and snapshot restore, and it cannot be changed after
creation. A persistent home uses an external volume, so do not combine
`networkPolicy: { mode: "off" }` with `persistentHome: true`. Domain and IP
allowlists are not supported.

### Templates

Use a template when you want a computer that already has extra tools installed.
For example, `coding-agent` includes common tools for coding tasks.

List available templates:

Create a file named `list-templates.mjs`:

```js
import { Computer } from "@celestoai/sdk";

const templates = await Computer.listTemplates();
for (const template of templates) {
  console.log(template.id, template.defaultRamMb);
}
```

Create a computer from a template:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create({ templateId: "coding-agent" });
try {
  console.log(computer.name);
} finally {
  await computer.delete();
}
```

### Run a Command

Create a file named `run-command.mjs`:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create();
try {
  const result = await computer.run("ls -la", {
    timeout: 60,
  });

  console.log(result.exitCode);
  console.log(result.stdout);
  console.error(result.stderr);
} finally {
  await computer.delete();
}
```

Stream output while the command is running:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.get("curie");
const controller = new AbortController();

for await (const event of computer.runStream("npm test", {
  timeout: 300,
  signal: controller.signal,
})) {
  if (event.type === "stdout") process.stdout.write(event.data);
  if (event.type === "stderr") process.stderr.write(event.data);
  if (event.type === "exit") console.log(`Exit code: ${event.exitCode}`);
}
```

Call `controller.abort()` to stop the stream and the remote command.

### Manage Computers

`computerId` can be `computer.id` from `Computer.create()` or a computer name
shown by the Celesto command-line tool: `celesto computer list`.

| Method | What it does |
| --- | --- |
| `Computer.list()` | List computers in your account |
| `Computer.get(computerId)` | Get one computer by name or ID |
| `computer.listCommandHistory()` | List recent commands and their status |
| `computer.stop()` | Stop a running computer |
| `computer.start()` | Start a stopped computer |
| `computer.delete()` | Delete a computer |

### Publish Ports

Publish a port when a service inside the computer needs a public URL:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.get("curie");
const url = await computer.publishPort(8000);
console.log(url);
```

List and remove published ports:

```js
import { Computer } from "@celestoai/sdk";

const computer = await Computer.get("curie");
console.log(await computer.listPublishedPorts());
await computer.unpublishPort(8000);
```

### Terminal Connections

Use `createTerminalSession()` when you are building an interactive terminal.
Celesto returns a short-lived URL that connects directly to the fast terminal
gateway instead of sending terminal traffic through the control plane. Creating
a terminal session requires write access to the computer.

For Node.js, first install a WebSocket client:

```bash
npm install ws
```

Then connect with the authenticated URL:

```js
import { Computer } from "@celestoai/sdk";
import WebSocket from "ws";

const computer = await Computer.get("curie");
const connection = await computer.createTerminalSession();
const ws = new WebSocket(connection.url);

ws.on("message", (data) => process.stdout.write(data));
ws.on("open", () => ws.send("pwd\n"));
```

`connection.url` contains a short-lived terminal token. Treat it as a secret and
create a new terminal session after `connection.expiresAt`.

## Gatekeeper

Use Gatekeeper when your app needs user-approved access to an external resource,
such as Google Drive.

Create a file named `gatekeeper-connect.mjs`:

```js
import { GatekeeperClient } from "@celestoai/sdk/gatekeeper";

const client = new GatekeeperClient({ token: process.env.CELESTO_API_KEY });

const connect = await client.connect({
  subject: "customer_123",
  provider: "google_drive",
  projectName: "Default",
});

if (connect.status === "redirect") {
  console.log(connect.oauthUrl);
} else {
  console.log(connect.status);
}
```

If the response prints a URL, open it so the user can approve access.

Full Gatekeeper docs: https://docs.celesto.ai/celesto-sdk/gatekeeper

## Configuration

| Option | What it does |
| --- | --- |
| `token` | Celesto API key or JWT |
| `apiKey` | Alias for `token` |
| `baseUrl` | Custom Celesto API URL |
| `organizationId` | Sends the `X-Current-Organization` header |
| `timeoutMs` | Request timeout in milliseconds |
| `headers` | Extra headers to send with every request |

Pass these options as the second argument to `Computer.create()` or
`Computer.get()`. An explicit `token` or `apiKey` takes precedence over local credential discovery. Gatekeeper clients accept the same options in their constructor and require an explicit token.

JWT is a signed login token. Most users should use a Celesto API key.

## Errors

The SDK exports these error classes:

| Error | When it is used |
| --- | --- |
| `CelestoApiError` | The API returns an error status |
| `CelestoNetworkError` | The network request fails |
| `CelestoError` | Base class for all SDK errors |

Managed agents add an error class per reason an operation can be refused, so you
can react to the specific one. Each extends `ManagedAgentError`, which extends
`CelestoApiError`.

| Error | When it is used |
| --- | --- |
| `BudgetExceededError` | This user has spent their budget for the window |
| `SessionBusyError` | Another run holds the conversation. Retryable; check `retryAfter` |
| `IdempotencyConflictError` | This key was already used with a different request |
| `AgentArchivedError` | The agent no longer takes runs |
| `ProviderNotConnectedError` | No credential is connected for the agent's model |
| `SessionAgentMismatchError` | That conversation belongs to a different agent |
| `SessionEndUserMismatchError` | That conversation belongs to a different user |
| `ModelRequiresOwnKeyError` | This model runs only on your own provider key |
| `ConfigKeyNotAllowedError` | The agent config carried an unsupported setting. Thrown by `agents.create()`/`agents.update()` before any request is sent, not by a run |

## Develop Locally

If you are contributing and have `npm` installed, run these commands from the
repository's `ts` directory:

```bash
npm install
npm test
npm run lint
npm run build
```

## License

Apache-2.0. The SDK is open source. Use of the Celesto platform is governed by
the Celesto Terms of Service: https://celesto.ai/legal/terms
