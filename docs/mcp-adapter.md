# Project Brain MCP Adapter

Project Brain 0.7.0 includes a controlled, loopback-only MCP adapter. It lets an
MCP client create canonical Codex tasks, start the next one-shot Core worker,
inspect bounded state/evidence, and submit exact-head reviews. It is not a
remote shell or workspace browser.

## Install and start locally

The adapter uses the stable v1 line of the official MCP Python SDK:

```bash
python3.11 -m venv ~/.project-brain/app/venv
~/.project-brain/app/venv/bin/pip install -e .
~/.project-brain/app/venv/bin/project-brain serve
```

The project dependency is exactly pinned to `mcp==1.28.1` because strict
top-level unknown-field rejection currently relies on SDK-private generated
argument-model metadata. Do not upgrade the SDK until server startup, tool
discovery, `additionalProperties=false`, and runtime unknown-argument tests
all pass against the candidate version.

The default endpoint is:

```text
http://127.0.0.1:7677/mcp
```

The no-auth MVP accepts only `127.0.0.1` or `::1` bind addresses. Requests to
bind `0.0.0.0`, a LAN address, public address, or DNS name fail before the MCP
SDK starts. Do not expose this endpoint through port forwarding, a public
reverse proxy, Cloudflare, ngrok, or another generic tunnel.

The source config example contains an informational `mcp_server` block. CLI
flags are authoritative for this MVP:

```bash
project-brain serve --host 127.0.0.1 --port 7677
```

The server is long-running, but every dispatch starts a separate fixed
one-shot worker equivalent to:

```bash
python -m project_brain --runtime-root ~/.project-brain apply --json
```

MCP input cannot change that executable, module, runtime, argv, cwd, or
environment. The request returns after the worker starts; poll task state
instead of waiting on the dispatch call.

A daemon reaper waits for each spawned worker and records a bounded
`mcp_dispatch_worker_exited` audit event containing only PID, exit code, and
log ID. It does not terminate a safely running detached worker when the MCP
server shuts down.

## Local protocol verification

Use the official MCP Inspector or another local MCP client:

```bash
npx -y @modelcontextprotocol/inspector
```

Connect the Inspector to `http://127.0.0.1:7677/mcp`, then verify initialize,
tools/list, and the read-only tools. Inspector is only a local protocol check;
it is not proof that the OpenAI tunnel or ChatGPT workspace permissions are
configured.

## Connect through OpenAI Secure MCP Tunnel

ChatGPT does not connect directly to a local MCP listener. OpenAI Secure MCP
Tunnel is the supported remote path: `tunnel-client` runs in the same trust
boundary as Project Brain, makes an outbound HTTPS connection to OpenAI, and
forwards tunnel work to the loopback endpoint. Project Brain remains off the
public internet.

Prerequisites are managed outside this repository:

- a Platform `tunnel_id` associated with the intended Platform organization
  and ChatGPT workspace;
- a separate runtime API key whose principal has Tunnels Read + Use;
- ChatGPT developer-mode access for the intended workspace/account;
- the current public `tunnel-client` release.

Product Shell wraps the current official long-lived runtime flow. It uses a
fixed alias/profile, fixed loopback MCP URL, and an environment-backed runtime
key reference equivalent to:

```bash
export CONTROL_PLANE_API_KEY="<runtime-api-key>"
tunnel-client runtimes connect \
  --alias project-brain \
  --tunnel-id tunnel_0123456789abcdef0123456789abcdef \
  --profile project-brain \
  --profile-dir ~/.project-brain/tunnel/profiles \
  --mcp-server-url http://127.0.0.1:7677/mcp \
  --runtime-api-key env:CONTROL_PLANE_API_KEY \
  --json
tunnel-client runtimes status project-brain --json
tunnel-client runtimes stop project-brain --json
```

Ordinary users perform this through Connection Center, not a terminal. Never
commit the runtime API key or generated profile. Connection Center reports
ready only when the local MCP initialize succeeds and tunnel status says the
managed process is running, healthy, and ready. In
ChatGPT developer mode, create a draft app, choose Tunnel as the connection,
select the associated tunnel, scan tools, and review write-action permissions.
OpenAI may request confirmation for write actions.

Current references:

- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
- [Official MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)

## Tools and authority

| Tool | Type | Authority |
| --- | --- | --- |
| `project_brain_system_health` | read | Bounded Core/runtime/dependency health |
| `project_brain_projects_list` | read | Registered project identity and health, without paths or commands |
| `project_brain_tasks_create` | write | Canonical `source_type=mcp`, Codex-only task intake |
| `project_brain_queue_dispatch_next` | write | Start one fixed one-shot worker after lock/claim preflight |
| `project_brain_tasks_list` | read | At most 100 task summaries |
| `project_brain_tasks_get` | read | Bounded current evidence, reviews, archive metadata, and recent events |
| `project_brain_tasks_review` | write | Atomic `approved` or `needs_changes` verdict for the exact canonical head |
| `project_brain_tasks_recovery_preview` | read | Dry-run classifier and identity state only |
| `project_brain_acceptance_probe` | write | Consume one waiting, hash-bound transport challenge and record unattributed evidence; no external-verification, task, file, Git, or process authority |

There are no tools for arbitrary files, directories, shell, Git reset/clean/
checkout/merge, free-form Codex commands, task-directed claim bypass, recovery
resolution, cleanup, manual acceptance mutation, or PR merge. The acceptance
probe accepts only the one-time `challenge` string. It records
`mcp_transport_probe_passed` with `external_chatgpt_verified=false`; request
headers, source IP, Host, Origin, and User-Agent are not trusted source evidence.
It is not an external-acceptance setter.

Create accepts only stable IDs, revision, goal, criteria, a bounded prompt, and
optional expiry/supersession. Every schema rejects unknown fields. Any nesting
level containing `command`, `argv`, `shell`, `cwd`, `environment`, `repo_path`,
`worktree_path`, or `codex_command` is rejected before persistence. Credential-
like input is rejected, and response/log strings pass the Core redactor.

Create, review, and dispatch writes produce append-only audit events. Review
does not implicitly dispatch, accept, publish, or merge. Recovery preview never
terminates an agent or changes SQLite; `--terminate-agent`,
`--confirm-no-agent`, `--resume`, and `--cancel` remain local CLI-only actions.

## Dispatch logs

Each started worker receives a private JSON Lines log:

```text
~/.project-brain/logs/mcp-dispatch/   0700
└── dispatch-<timestamp>-<id>.jsonl   0600
```

The log begins with a redacted dispatch record. Worker output omits task
payloads, commands, environment, full evidence, and artifact content. The MCP
response returns only the log ID, never its absolute local path.

## Manual acceptance checklist

1. Start the server and complete local initialize/tools/list.
2. Confirm all nine tool schemas and read/write annotations.
3. Generate a challenge in Product Shell and use the connector to call only
   `project_brain_acceptance_probe`; confirm the App records an unattributed MCP
   transport probe while external ChatGPT acceptance remains Pending.
4. Through Secure MCP Tunnel and a ChatGPT developer-mode draft app, list
   projects and create a documentation-only real task.
5. Dispatch, poll status, inspect bounded verification evidence and the Draft
   PR, then submit `needs_changes` for the exact head.
6. Dispatch again and confirm the new canonical commit descends from the old
   commit; submit `approved` but do not merge.
7. Confirm the registered main checkout and legacy Gmail/MenuBar files were not
   changed.

Steps that require a tunnel ID, runtime key, ChatGPT workspace permissions, or
trusted control-plane attestation cannot be replaced by local tests. Report them
as externally pending when
those credentials are unavailable.

## Distinctions and non-goals

- The local MCP server is the loopback Project Brain process.
- Secure MCP Tunnel is OpenAI's outbound-only transport to that private server.
- OAuth, DCR/CIMD, RBAC, users, public domains, and app publishing are not
  implemented by Project Brain 0.4.0.
- DevSpace is a generic remote workspace interaction model. Project Brain does
  not copy its file or terminal authority; this adapter exposes only canonical
  Core operations.
- The frozen Gmail Bridge remains legacy and is not migrated or launched by
  this adapter.
