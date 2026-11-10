---
name: ajcrew-commands
description: Complete CLI reference for Aj Crew commands. Use for help, commands, setup, how to, what can you do, getting started, onboarding.
always: false
triggers: help, commands, setup, gateway, how to, what can you do, getting started, onboard, browse, auth, doctor, cron, artifact, memory, snapshot, eval, security, ajcrew pod, pod up, pod down, pod ls, pod status, pod logs, pod provision, pod install, pod token
inject_on_trigger: false
---
# Aj Crew CLI Reference

## Setup & System

| Command | Description |
|---------|-------------|
| `ajcrew setup` | Interactive wizard — install agent config (messaging channels connect later) |
| `ajcrew setup --slack` | Also run the guided Slack credential setup (opt-in; ignored with `--agent-only`) |
| `ajcrew setup --agent-only` | Only install kiro-cli agent config, skip the other wizard steps |
| `ajcrew setup --clean` | Fresh install — don't merge from existing config |
| `ajcrew doctor` | Verify Aj Crew setup (checks all dependencies) |
| `ajcrew doctor --bundle` | Collect logs + crash reports into a redacted diagnostics zip |
| `ajcrew ledger-sweep` | List finished session/work ledgers older than 30 days (dry run, deletes nothing) |
| `ajcrew update` | Update Aj Crew to the latest version |
| `ajcrew update approve` | Approve a pending in-app update armed from the dashboard |
| `ajcrew update --force` | Discard local commits when a git checkout has diverged from upstream (git installs only) |
| `ajcrew --version` | Print installed version |
| `ajcrew sandbox status` | Report whether this launch is covered by the userns AppArmor profile |
| `ajcrew sandbox install-profile` | Attach the profile to this app (sudo; `--path P` for an explicit executable) |
| `ajcrew sandbox remove-profile` | Unload and remove the profile (sudo) |

`update --force` is destructive on a git install: the hard reset discards local
commits, recoverable only from `git reflog`. The `sandbox` verbs matter only on
hosts with `kernel.apparmor_restrict_unprivileged_userns=1` (Ubuntu 23.10+ and
derivatives) and are no-ops everywhere else; `--path` is refused for
world-writable locations and for shared interpreters such as `/usr/bin/python3`,
which would over-grant.

## Gateway (Server)

| Command | Description |
|---------|-------------|
| `ajcrew gateway` | Start dashboard + Slack gateway |
| `ajcrew gateway --slack-only` | Slack only — skip dashboard web server |
| `ajcrew gateway --no-crons` | Skip cron scheduler |
| `ajcrew gateway --port 9999` | Override dashboard port |
| `ajcrew gateway --port auto` | OS-assigned ephemeral port |
| `ajcrew gateway --no-open` | Don't auto-open dashboard URL in browser |
| `ajcrew gateway --approval reads` | Auto-approve read-only tools on background turns (cron, task runner, subagents); a channel turn still asks about every tool |
| `ajcrew gateway --approval yolo` | Auto-approve all tools (requires isolated AJCREW_HOME) |
| `ajcrew gateway --approval interactive` | Prompt for every tool. Without `--approval`, `agent.approval_mode` decides (default `auto`: no prompt) |
| `ajcrew gateway --seed FIXTURE` | Seed $AJCREW_HOME from fixture before starting (dev) |
| `ajcrew gateway --seed-replace` | Wipe a non-empty target home and re-seed it (paired with `--seed`) |
| `ajcrew gateway --no-tunnel` | Never publish a tunnel for this process's whole life, whatever `tunnel.enabled` says. Scoped to TUNNELS: it does not change where the dashboard binds |
| `ajcrew gateway --json-ready` | Print one `AJCREW_READY:{...}` line (port, token, pid, AJCREW_HOME) once the dashboard is bound |
| `ajcrew gateway --test-mode` | Alias for `--port auto --no-open --json-ready --approval reads` |
| `ajcrew stop` | Stop a running gateway |
| `ajcrew stop --port 9999` | Stop gateway on specific port |
| `ajcrew restart` | Restart gateway (service-aware) |
| `ajcrew status` | Show runtime stats (uptime, sessions, crons, lessons) |

The token in a `--json-ready` line grants dashboard access for up to 20 hours, so
captured stdout from a test harness is a credential: keep it out of logs and
transcripts.

## Service Management

| Command | Description |
|---------|-------------|
| `ajcrew service install` | Install and start as system service (sudo on Linux) |
| `ajcrew service uninstall` | Stop and remove system service (Linux: both system and per-user unit, each scope reported) |
| `ajcrew service status` | Show service status (systemctl/launchctl; Linux: system and per-user unit, each named) |
| `ajcrew logs` | Show gateway logs (last 100 lines) |
| `ajcrew logs -f` | Follow (tail) live log output |
| `ajcrew logs -n 50` | Show last N lines |

## Pods (Isolated Worktree Test Instances)

Ephemeral, full-stack Aj Crew gateways — one per feature worktree — that run on
their own port + isolated `AJCREW_HOME` and never touch the live `:5476`
gateway or shared data. Linux `systemd --user`, macOS `launchd`, Windows Task
Scheduler. `<wt>` is a worktree name
(resolved by directory basename or `feat/<name>` branch convention).

| Command | Description |
|---------|-------------|
| `ajcrew pod install` | Lay down the systemd --user template unit (once per machine; Linux only, a no-op elsewhere) |
| `ajcrew pod provision <wt>` | Build the worktree's venv + SPA dist (the on-ramp) |
| `ajcrew pod up <wt>` | Bring up an isolated pod (auto-builds venv; fails if dist missing) |
| `ajcrew pod up <wt> --provision` | Provision (venv + dist build) then bring up |
| `ajcrew pod up <wt> --json` | Bring up and print `{base_url, token, port}` as JSON |
| `ajcrew pod ls` | List running pods |
| `ajcrew pod status <wt>` | Up/down + health for one pod |
| `ajcrew pod token <wt>` | (Re)mint a dashboard token for a running pod |
| `ajcrew pod url <wt>` | Print the pod's base URL |
| `ajcrew pod logs <wt> -n N` | Tail the pod's journal |
| `ajcrew pod down <wt>` | Evict the pod and delete its isolated HOME |
| `ajcrew pod prune` | Bulk-reclaim orphaned pod HOMEs (`--older-than 3d` by default, `--all`, `--dry-run`, `--json`) |
| `ajcrew pod scenarios` | List the seed scenarios `pod up --seed <scenario>` accepts (`--json`) |
| `ajcrew pod exec <wt> -- <args>` | Run an ajcrew command against a pod, using the pod's own binary and data |
| `ajcrew pod api <wt> <METHOD> <path>` | Call a running pod's HTTP API with its own token; prints `{name, method, path, status, ok, body}` |
| `ajcrew pod api <wt> POST config --data '{…}' --allow-write` | GET and HEAD are permitted by default; every other method needs `--allow-write` |

**Platform:** Linux (`systemd --user`), macOS (`launchd`; no memory/CPU ceiling)
and Windows (Task Scheduler; no restart on crash, `pod api` unsupported). On a
host with none of those, every service-manager verb refuses with a one-line
message pointing at `./dev-backend.sh` — it does not crash, and `pod install`
writes no unit file. `pod url` works anywhere (pure computation).

Port derivation: `base + (cksum(name) % 199) + 1` (base `7810` → `7811..8009`).
Override with `PORT=` in `~/.kiro/crew/pods/<name>.env`.

`ajcrew pod --help` lists every verb and its flags.

## Dashboard Access

| Command | Description |
|---------|-------------|
| `ajcrew token` | Print a dashboard URL with auth token (TTL: 20h) |
| `ajcrew token --ttl 1h` | Token with custom TTL (e.g. 1h, 30m) |
| `ajcrew logout` | Revoke all active dashboard sessions |
| `ajcrew manifest` | Generate Slack app manifest with your alias |
| `ajcrew manifest --url` | Print one-click Slack app creation URL |

## Chat

| Command | Description |
|---------|-------------|
| `ajcrew chat` | Interactive chat (REPL mode) |
| `ajcrew chat -m "message"` | Single message (non-interactive) |
| `ajcrew chat --model MODEL_ID` | Use a specific model (default `auto`; any id the model picker lists) |

When `ajcrew chat` asks to run a tool, answer `y` to allow that call once or
`n` to deny it, the same keys `kiro-cli chat` uses. `o` denies it and lets you
type a reply to the agent instead. Anything else denies.

## Browsing (`browser` MCP tool)

Browsing is not an `ajcrew` subcommand. It is the **`browser` MCP tool**:
`op=navigate|back|snapshot|click|drag|scroll|type|press_key|hover|select_option|wait_for|console|screenshot|tabs|reflex|ask`.
It drives one browser the gateway owns (the user's own Chrome where there is
one, Edge on Windows without Chrome, otherwise Kiro's headless Chromium), and the
user watches the page live in the chat, where one click takes over. It opens
public `http(s)` URLs only, plus loopback origins the user listed under
**Settings → Browser → Local preview origins**.

| Op | Description |
|----|-------------|
| `navigate {url}` | Open a page (returns URL and title) |
| `snapshot` | The page as an outline with element refs (`e5`); re-run after every page change |
| `click {ref \| x,y}` / `type {ref, text, submit?}` | Act on an element from a snapshot; `type` refuses a password field |
| `screenshot` | Write a PNG, return its absolute path; show it with `![..](path)` |
| `tabs {action: list\|switch\|new}` | The tabs the agent opened, and only those |

**Browsing workflow:** load the `web-browse`, `web-verify`, or `browser-auth`
skill for the task. A sign-in, CAPTCHA or 2FA is the user's step: use the `ask`
op (the tool's description lists its args), or ask them to take over the live
view; your next op waits until they hand it back, then runs.

**Setup:** **Settings → Browser** installs the engine on the gateway's machine
and, on a desktop, connects the user's own Chrome (enable
`chrome://inspect/#remote-debugging` once, then Allow). A tool reply that
browsing is not set up points there; a `capabilities.browse` policy denial is
final. The old Playwright CLI install is gone: `ajcrew doctor` reports a
leftover prefix without touching it.

## Autonomous Task Runner

| Command | Description |
|---------|-------------|
| `ajcrew run TASK.md` | Run a task spec file (auto-resumes from checkpoint) |
| `ajcrew run TASK.md --fresh` | Start from scratch, ignore checkpoint |
| `ajcrew run TASK.md --no-test` | Skip build/test verification after each step |
| `ajcrew run TASK.md --timeout 3600` | Set global timeout in seconds |
| `ajcrew run TASK.md --name "My Task"` | Override human-readable task name |

## Subagents

| Command | Description |
|---------|-------------|
| `ajcrew spawn run "task"` | Spawn a background subagent (wait for result) |
| `ajcrew spawn run --async "task"` | Fire-and-forget subagent |
| `ajcrew spawn run --crew NAME "task"` | Run as a Bot (its memory and template); an unknown name is refused |
| `ajcrew spawn run --agent NAME "task"` | Run under a named agent template; an unknown name is refused |
| `ajcrew spawn run --model ID "task"` | Run on a model id; it outranks the member's and the template's pin |
| `ajcrew spawn list` | List active subagents |

## Cron Jobs

| Command | Description |
|---------|-------------|
| `ajcrew cron list` | List all cron jobs |
| `ajcrew cron add NAME MESSAGE --every 3600` | Add job with interval (seconds) |
| `ajcrew cron add NAME MESSAGE --cron "0 9 * * MON-FRI"` | Add job with cron expression |
| `ajcrew cron add NAME MESSAGE --agent myagent` | Add job for specific agent |
| `ajcrew cron add NAME MESSAGE --approval-mode auto` | Add job with auto tool approval |
| `ajcrew cron add NAME MESSAGE --channel C123456` | Post results to Slack channel |
| `ajcrew cron add NAME MESSAGE --at "tomorrow 9am"` | One-shot job: fires once, then deletes itself (Unix timestamp or time string) |
| `ajcrew cron add NAME MESSAGE --cron "0 9 * * *" --timezone Europe/Paris` | Evaluate the cron expression in an IANA timezone |
| `ajcrew cron add NAME "" --every 3600 --script ~/.kiro/crew/crons/f.py:run --no-persistent-session --minimal-context` | Zero-token job: run a Python function (file must already be under `crons/`; registers, does not copy) |
| `ajcrew cron add NAME "" --every 600 --command "df -h /" --no-persistent-session --minimal-context` | Zero-token job: run a vetted shell command |
| `ajcrew cron add ... --timeout 30 --timeout-secs 60` | Subprocess timeout (script/command) and whole-wake budget |
| `ajcrew cron add ... --[no-]persistent-session --[no-]minimal-context --hide-in-chat --model ID` | Session shape and model; defaults are persistent session on, minimal context off, so pass `--no-persistent-session --minimal-context` for a script/command job |
| `ajcrew cron add ... --project-path /abs/repo` | Run the agent session in that repo, so its `.kiro/steering/` and `AGENTS.md` load (agent jobs only; `cron update JOB_ID --project-path ''` clears it) |
| `ajcrew cron update JOB_ID --message "new msg"` | Update job message |
| `ajcrew cron update JOB_ID --agent myagent` | Update job agent |
| `ajcrew cron update JOB_ID --approval-mode auto` | Set auto-approval |
| `ajcrew cron update JOB_ID --approval-mode default` | Reset approval to default |
| `ajcrew cron remove JOB_ID` | Remove a cron job |
| `ajcrew cron pause JOB_ID` | Pause a cron job |
| `ajcrew cron resume JOB_ID` | Resume a paused job |
| `ajcrew cron adopt JOB_ID --session-of SESSION` | Give the job an owning chat session, so that session manages it and receives its results |
| `ajcrew cron adopt JOB_ID --release` | Clear the owning session, returning the job to CLI/dashboard-only management |
| `ajcrew cron trigger JOB_ID` | Trigger a job immediately |
| `ajcrew cron preview SCRIPT` | Run a script cron locally with real MCP tools; notifications and session and crew-log calls are printed, not made |
| `ajcrew cron preview SCRIPT -m "msg" -e K=V` | Preview with an input message / extra env vars |

## Learning & Memory

| Command | Description |
|---------|-------------|
| `ajcrew learn list` | List all saved lessons |
| `ajcrew learn add "rule text"` | Save a lesson (category: knowledge) |
| `ajcrew learn add "rule text" --category tool` | Save with category (tool/preference/knowledge) |
| `ajcrew learn add "rule text" --negative "avoid X"` | Save with negative example |
| `ajcrew learn remove "query"` | Remove lessons matching substring (add `--repo-scope FRAG` to remove only that scope, `--repo-scope ""` for global only) |
| `ajcrew memory list` | Show semantic memory entries |
| `ajcrew memory search "query"` | Search episodic memories |
| `ajcrew memory stats` | Show memory statistics |
| `ajcrew memory audit` | Scan memory for suspicious content |
| `ajcrew memory create-store <name>` | Create the directory of a named V1 store declared in `memory_stores` (`use` never creates it; refuses the default store, an undeclared name and a V2 member store) |
| `ajcrew memory export` | Export the default store's rows to JSON (stdout) |
| `ajcrew memory export -o file.json` | Export to file |
| `ajcrew memory export --store <name>` | Export a named store's rows instead |
| `ajcrew memory import file.json` | Import memory from JSON |
| `ajcrew memory import --store <name> file.json` | Import into a named store instead |
| `ajcrew memory migrate` | Migrate legacy markdown memory to vector store |
| `ajcrew memory backup [--keep N]` | Back up active memory stores now |
| `ajcrew memory backups [--store <name>]` | List memory backups, newest first |
| `ajcrew memory restore [--store <name>] [--from FILE \| --cancel-pending]` | Restore a store from a backup (default: its newest) |
| `ajcrew memory carve --store <name>` | Filter or count a crew store's memory by carve facets (`--scope`, `--surface`, `--crew`, `--session-key`) |
| `ajcrew memory retired [--restore ID]` | List episodes a semantic write superseded, and restore one |
| `ajcrew memory show [preferences\|projects\|history]` | Show the markdown memory layer (default: all three; `--format md\|json`, `--since YYYY-MM-DD` for history) |
| `ajcrew knowledge dedup` | Preview cross-source duplicate knowledge documents (dry-run) |
| `ajcrew knowledge dedup --apply` | Actually collapse the duplicates |
| `ajcrew consolidate` | List sessions with unconsolidated messages |
| `ajcrew consolidate SESSION_KEY` | Force consolidate a session (triggers auto-skill extraction) |
| `ajcrew consolidate --all` | Consolidate all pending sessions |

## Artifacts

LLM-generated UI components (widgets, HTML, markdown, SVG, JSON, text).

| Command | Description |
|---------|-------------|
| `ajcrew artifact list` | List all artifacts |
| `ajcrew artifact list --tag ops --kind widget` | Filter by tag and kind |
| `ajcrew artifact list -q "CR"` | Substring filter on name |
| `ajcrew artifact show SLUG` | Print artifact content |
| `ajcrew artifact show SLUG --version 2` | Show specific version |
| `ajcrew artifact show SLUG --meta` | Show metadata as JSON |
| `ajcrew artifact save --name "My Widget" --content-file widget.html` | Save new artifact |
| `ajcrew artifact save --name "X" --content "..." --tags ops,cr` | Save with inline content |
| `ajcrew artifact update SLUG --content-file widget.html` | Update artifact content |
| `ajcrew artifact update SLUG --name "New Name" --tags ops` | Rename/retag |
| `ajcrew artifact versions SLUG` | List version numbers |
| `ajcrew artifact delete SLUG` | Delete artifact and all versions |

## Agents & Workspaces

| Command | Description |
|---------|-------------|
| `ajcrew agent list` | List Aj Crew agents |
| `ajcrew agent create --name NAME` | Create a new agent |
| `ajcrew agent create --name NAME --kiro-agent ajcrew --workspace default` | Full options |
| `ajcrew agent update NAME --kiro-agent new-agent` | Update agent settings |
| `ajcrew agent update NAME --display-name "Label"` | Change the name the dashboard shows (`""` clears it); the agent name stays |
| `ajcrew agent delete NAME` | Delete an agent |
| `ajcrew agent reset-model [--agent ajcrew]` | Clear a pinned model so the agent tracks the shipped default |
| `ajcrew workspace list` | List workspaces |
| `ajcrew workspace create --name NAME --dir DIRNAME` | Create workspace (`--dir` is a **name under the data home**, not an absolute path) |
| `ajcrew workspace create --name NAME --copy-from existing` | Copy from existing |
| `ajcrew workspace update NAME --dir DIRNAME` | Update workspace dir (same containment rule) |
| `ajcrew workspace delete NAME` | Delete workspace |

**On the CLI**, `--dir` must resolve to a **strict descendant** of
`$AJCREW_HOME` (default `~/.kiro/crew`): anything landing outside — `/tmp/x`,
`../x`, `~/x` — is refused with a SEL `denied` audit event, and so is the data
home **root itself** (in any spelling: absolute, `~/.kiro/crew`, `.`, or empty),
since a workspace there would put agent-writable memory on top of `config.json`
and `.env`. The test is containment, not "is it absolute": an absolute path
landing *under* the home is accepted, since it resolves where the relative form
would. Pass `workspace-myproject`, not `/path/to/dir`.

Note the surface difference: the **dashboard** `POST /api/workspaces` DOES accept
an absolute `dir` (screened by `is_sensitive_path`, so `~/.ssh` / `~/.aws` /
keystone paths are still refused). The CLI is the stricter of the two.

## Apps

| Command | Description |
|---------|-------------|
| `ajcrew app list` | List installed apps |
| `ajcrew app install /path/to/app-dir` | Install app from local directory (needs app.json) |
| `ajcrew app enable NAME` | Enable an installed app (an app that asks to control your chats is allowed in the dashboard only) |
| `ajcrew app disable NAME` | Disable an installed app |
| `ajcrew app update NAME [--source DIR]` | Update an installed app in place from its source directory (the one it was installed or last updated from, unless `--source` names another, which then becomes the recorded one), keeping its data and enabled state. Needs a running gateway; with none reachable it changes nothing |
| `ajcrew app uninstall NAME` | Uninstall an app and preserve its data directory |
| `ajcrew app uninstall NAME --purge-data` | Uninstall and explicitly delete the app data directory |
| `ajcrew app info NAME` | Show app details |
| `ajcrew app init NAME` | Scaffold a new app (kebab-case name) |
| `ajcrew app init NAME --backend --ui --cron` | Scaffold with backend, UI, and sample cron |
| `ajcrew app dev NAME` | Toggle an app into dev mode (no-store UI serving + live reload on file change) |
| `ajcrew app dev NAME --off` | Leave dev mode |
| `ajcrew app mcp NAME` | Run an app's MCP server on stdio (spawned by kiro-cli, not for humans) |

## Configuration

| Command | Description |
|---------|-------------|
| `ajcrew config get` | Show all config |
| `ajcrew config get agent.provider` | Get specific value (dot-separated key) |
| `ajcrew config set dashboard.url http://localhost:5476` | Set a config value (port is the AJCREW_PORT env var, not a config key) |
| `ajcrew config set --file config.json` | Load full config from JSON file |
| `ajcrew config edit` | Open config in $EDITOR |
| `ajcrew config defaults [KEYS…]` | Review stored values that still hold a superseded default |
| `ajcrew config defaults [KEYS…] --adopt` | Remove those stored keys so the current defaults apply |
| `ajcrew config defaults [KEYS…] --keep` | Record the stored values as intentional and stop reporting them |

## Profiling (debug-only)

Off unless `AJCREW_DEBUG=1` is set; the CLI is the only entry point. Emits folded
stacks (open in speedscope / flamegraph.pl). See `docs/architecture/design-notes/profiling.md`.

| Command | Description |
|---------|-------------|
| `AJCREW_DEBUG=1 ajcrew perf sample --call mod:fn` | Profile that callable in-process (no extra dependency) |
| `AJCREW_DEBUG=1 ajcrew perf sample` | Attach to the running gateway (needs `pip install "ajcrew[perf]"`) |
| `AJCREW_DEBUG=1 ajcrew perf sample --pid 1234 --seconds 30` | Attach to a specific PID for N seconds (1-300) |
| `... --interval 0.002` | Seconds between samples (0.001-1.0, default 0.005) |
| `... --output /tmp/p.folded` | Where to write the profile (default `./ajcrew-profile.folded`) |
| `AJCREW_DEBUG=1 ajcrew desktop metrics` | Per-process CPU/memory of the **Electron** app (`--json`, `--top N`, `--path`) |

On macOS the attach path additionally needs elevated privileges (the OS denies
`task_for_pid`), so it may require sudo; `--call` needs neither py-spy nor sudo.

`desktop metrics` reads a recording rather than querying the app: `getAppMetrics()`
is Electron-main-only, so the app samples itself into an artifact when **started**
with `AJCREW_DEBUG` set. Setting the variable only for the CLI does not make an
already-running app record -- restart it.

## Security & Eval

| Command | Description |
|---------|-------------|
| `ajcrew secrets import` | Dry-run the migration of plaintext `.env` credentials into the encrypted vault |
| `ajcrew secrets import --apply` | Store the secrets and rewrite `.env` to `secret://` refs |
| `ajcrew telemetry status` | Show exactly what the anonymous beacon sends, and whether it will |
| `ajcrew telemetry disable` | Turn the anonymous beacon off permanently |
| `ajcrew telemetry enable` | Turn the anonymous beacon back on |
| `ajcrew security audit` | Scan conversation history for suspicious tool usage |
| `ajcrew security deny-list` | Show active deny patterns |
| `ajcrew security events` | Show recent security event log entries (last 20) |
| `ajcrew security events -n 50` | Show N entries |
| `ajcrew security verify` | Verify security event log HMAC integrity |
| `ajcrew eval` | Run smoke test evaluation (~30s) |
| `ajcrew eval memory_recall_basic` | Run specific scenario by name |
| `ajcrew eval --all` | Run all scenarios (slow) |
| `ajcrew eval --judge` | Enable LLM judge scoring |
| `ajcrew bench list` | Show the available corpora and what is cached |
| `ajcrew bench fetch CORPUS` | Download a corpus into the local cache and verify its checksum |
| `ajcrew bench retrieval` | Measure retrieval recall/nDCG against a corpus (deterministic) |
| `ajcrew bench kb-retrieval` | Measure Knowledge Library recall/MRR/nDCG against a golden set (deterministic) |
| `ajcrew bench lesson-recall` | Measure lesson ranking recall/MRR/nDCG against a golden set (deterministic) |
| `ajcrew bench compare A B` | Diff two saved JSON reports; refuses to attribute a delta when the runs disagree on corpus |

## Governance Policy

Inspects the two-level security model (`effective = POLICY ∩ PROFILE`,
tightest-wins). Six verbs: five are read-only, and `fetch` writes — it applies the
central policy when the download is usable. The enterprise ceiling is never
hand-edited through the CLI (its files are keystone-fenced so the agent cannot read
or write them).

| Command | Description |
|---------|-------------|
| `ajcrew policy show` | Show the effective enterprise security policy |
| `ajcrew policy show --ids` | List each denied-command category's rule ids (default: counts only) |
| `ajcrew policy validate` | Load-check the policy + all profiles |
| `ajcrew policy explain SCOPE ITEM` | Explain one tool/scope decision for a surface |
| `ajcrew policy explain SCOPE ITEM --session-key K --agent A --app APP` | Scope the explanation to a surface |
| `ajcrew policy profile NAME` | Show a profile by name |
| `ajcrew policy source` | Show whether this host fetches its policy from a central source |
| `ajcrew policy fetch` | Fetch the central policy now and apply it if usable (`--force` re-downloads, ignoring cached validators) |

## Cloud (Bring-Your-Own AWS)

Runs Aj Crew on an EC2 instance in **your own** AWS account; credentials are
resolved by the `aws` CLI and never stored by Aj Crew. All verbs accept
`--profile` / `--region`; the single-instance verbs also accept `--tag`
(defaults to the last launched instance).

| Command | Description |
|---------|-------------|
| `ajcrew cloud doctor` | Check cloud prerequisites + AWS reachability |
| `ajcrew cloud launch` | Provision + configure an instance (interactive) |
| `ajcrew cloud launch --size TIER -y` | Non-interactive launch at a size tier |
| `ajcrew cloud launch --new` | Create a separate new instance instead of resuming the saved one |
| `ajcrew cloud launch --keep-on-failure` | On bootstrap failure keep the instance for inspection |
| `ajcrew cloud list` | List your Aj Crew cloud instances |
| `ajcrew cloud status` | Show one instance's state |
| `ajcrew cloud connect` | Open the dashboard over an SSM tunnel |
| `ajcrew cloud tunnel` | Open the dashboard SSM tunnel (standalone alias of connect) |
| `ajcrew cloud connect --local-port N --no-browser` | Forward to a specific local port, no browser |
| `ajcrew cloud login` | Sign kiro-cli in on the instance (fixes "not logged in" chat errors) |
| `ajcrew cloud logout` | Sign kiro-cli out on the instance, to switch Kiro account |
| `ajcrew cloud stop` | Stop the instance (pause billing) |
| `ajcrew cloud start` | Start a stopped instance |
| `ajcrew cloud destroy` | Remove the instance and ALL its AWS resources |
| `ajcrew cloud destroy --dry-run` | Show the delete command without running it |
| `ajcrew cloud iam-policy` | Print the least-privilege IAM policy to apply |
| `ajcrew cloud iam-boundary` | Pre-create the immutable EC2 + Fargate permissions boundaries (admin, one-time) |

## Tailnet (Tailscale)

Publishes this dashboard on your tailnet and trusts its origin, so a device on the
tailnet reaches it without a public tunnel.

| Command | Description |
|---------|-------------|
| `ajcrew tailnet status` | Show whether the dashboard is published and trusted on your tailnet |
| `ajcrew tailnet up` | Publish the dashboard on your tailnet and trust its origin |
| `ajcrew tailnet down` | Stop publishing the dashboard on your tailnet |
| `... --port N` | Name the dashboard port; `up` needs it whenever discovery has no verified port |

`up` publishes only a port it has evidence for: an explicit `--port`, `AJCREW_PORT`,
or the running gateway's run marker. With none of those — the gateway is down, the
marker is unreadable, or several gateways are up, where the marker deliberately
refuses — `up` refuses rather than falling back to the configured `dashboard.url`
port, because nothing is verified to answer there and `tailscale serve` would expose
whatever does. Start the gateway and re-run, or name the port yourself. `status` and
`down` do accept the configured port: one only reports, and the other checks mount
ownership before removing anything.

## Computer Use (Desktop Automation)

Default-OFF behind a keystone enable (`~/.kiro/crew/computer_use.json`, **not**
`config.json`). macOS and Windows carry the full tool set; Linux answers a typed
unsupported refusal. On Windows there is no per-process input, so a keystroke takes
the user's keyboard focus and a coordinate click moves their real cursor — say so
rather than reporting a silent success. These are human debug/diagnostic twins of the
`computer_*` MCP tools — the agent uses the MCP tools, not these.

| Command | Description |
|---------|-------------|
| `ajcrew computer doctor` | Report platform support, keystone enable state, and the advisory Accessibility / Screen Recording probe |
| `ajcrew computer doctor --json` | Same as JSON |
| `ajcrew computer apps` | List on-screen applications the accessibility layer can address |
| `ajcrew computer call TOOL k=v …` | Run ONE computer-use tool through the same gated chokepoint the agent uses |
| `ajcrew computer call --calls '[…]'` | Run a JSON array of calls in a SINGLE process, so `element_index` values stay resolvable |

## Snapshot & Restore

| Command | Description |
|---------|-------------|
| `ajcrew snapshot` | Create a portable backup of Aj Crew state |
| `ajcrew snapshot /path/to/dir` | Snapshot to specific output directory |
| `ajcrew snapshot --keep 7` | Keep N most recent snapshots (default: 7) |
| `ajcrew snapshot --strict` | Exit 3 instead of 0 when the bundle omits entries it was asked to carry |
| `ajcrew snapshot --list` | List existing snapshots |
| `ajcrew restore` | Restore from most recent snapshot |
| `ajcrew restore /path/to/snap.tar.gz` | Restore from specific snapshot |
| `ajcrew restore --mode replace` | Replace mode (overwrite existing state) |
| `ajcrew restore --mode merge` | Merge mode (keep existing state, add). Without `--mode`: merge when `memory.db` exists, else replace |
| `ajcrew restore --dry-run` | Preview without applying |
| `ajcrew restore --components memory,crons` | Restore specific components only |
| `ajcrew restore --list-components` | List restorable components |
| `ajcrew restore --force` | Restore even if gateway is running |

## Slack Commands

### All Allowed Users
| Command | Description |
|---------|-------------|
| `!dashboard` | Get a presigned dashboard link (DM'd to you). Link expires in 5 min; session lasts 1h |
| `!dashboard 2h` | Dashboard link with custom duration (accepts `<N>h` or `<N>m`, max 20h) |
| `/ajcrew dashboard` | Same via slash command |
| `/ajcrew help` | List available slash sub-commands |
| `/ajcrew status` | Show runtime stats |
| `/ajcrew sessions` | List recent sessions with resume/end buttons |
| `!stop` | Force-halt the current agent turn (bypasses semaphore, cancels active task) |
| `status` | Show runtime stats |
| `ping` | Auto-reply `pong` |
| `cron list` | List cron jobs |
| `run <path>` | Run an autonomous task from a spec file |

### Owner-Only Slash Commands
| Command | Description |
|---------|-------------|
| `/ajcrew yolo` | Toggle YOLO mode (auto-approve all tool calls) |
| `/ajcrew agent` | Show agent selector dropdown |
| `/ajcrew agent <name>` | Switch to named agent |
| `/ajcrew voice` | Open TTS voice settings modal |
| `/ajcrew config` | Open config modal |
| `/ajcrew users` | Open allowed users management modal |
| `/ajcrew channels` | Open tracked channels modal |
| `/ajcrew restart` | Restart the gateway (needs a systemd supervisor) |

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `AJCREW_HOME` | Override config/data directory | `~/.kiro/crew` |
| `AJCREW_PORT` | Override dashboard port | `5476` |
| `AJCREW_PROJECT_DIR` | Override agent config/skills directory | Auto-detected |
| `AJCREW_POD_REPO` | Repo to resolve worktree names from | invoking cwd |
| `AJCREW_POD_ROOT` | Isolated pod HOMEs (nuked on stop) | `~/.ajcrew-pods` |
| `AJCREW_POD_BASE_PORT` | Port derivation base | `7810` |
| `AJCREW_POD_LIVE_PORT` | Port a pod must never bind | `5476` |
