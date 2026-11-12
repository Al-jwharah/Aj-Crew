# Use Cases & Workflows

Example workflows that combine Aj Crew's capabilities — cron jobs, subagents,
memory, chat channels, and task runner — into end-to-end automation. They were
first written up by users of Kiro Crew, the project Aj Crew is forked from.

## Backlog Crusher

An example workflow: Aj Crew works through your issue backlog, picks up tasks,
implements them, runs tests, opens pull requests, and handles review comments
without you driving each step.

The task runner reads a spec you write. Save the steps below as
`backlog-crusher.md`:

```markdown
# Backlog crusher

1. List open issues in the project's tracker.
2. Pick the highest-priority unassigned issue.
3. Read the issue description and the code it links to.
4. Implement the change.
5. Run the test suite (e.g. `pytest`).
6. Open a pull request targeting the correct branch.
7. Move to the next issue.
```

Then hand that file to the runner. The path is resolved as given, so run this from
the directory holding the file, or pass its absolute path:

```
ajcrew run backlog-crusher.md
```

`ajcrew run --help` lists the flags that matter for a long run: `--fresh`
ignores an existing checkpoint, `--no-test` skips verification between steps,
and `--timeout` caps the whole run.

Standalone `ajcrew run` has nobody to ask for approval, so it is
deny-by-default: a tool runs only when it matches `hooks.auto_approve_tools`.
Allowlist the tools this spec needs (see
[Task Runner → Tool Approval](task-runner.md#tool-approval)), or start the run
from the dashboard Task Runner, where you approve tool calls as they come or
switch on auto-approve for that run.

The `yolo` approval mode applies to the gateway only (`ajcrew gateway
--approval yolo`), not to `ajcrew run`. The gateway refuses it unless
`AJCREW_HOME` points at an isolated data home rather than the main one.

## Repetitive Refactors

Automate repetitive cleanup across a codebase. Aj Crew reads a config or
feature-flag list, identifies dead code paths, removes them, and opens pull
requests.

## Slack → Issue Pipeline

An example of composing a cron job with a task-runner spec: a cron prompt turns
requests in a Slack channel into issues, and a separate run works on them.
Nothing picks the new issues up on its own; you start that run.

Setup:
1. Enable observe mode for the source channel.
2. Create a cron job: "Every hour, check #my-channel for new requests and create issues for actionable items"
3. Run a backlog-crusher spec (above) over the new issues

## Daily Briefings

Schedule morning briefings that summarize what matters:

- "Every weekday at 9am, give me a CI/pipeline health summary"
- "Every Monday at 8am, list my open pull requests and their review status"
- "Every day at 5pm, summarize today's Slack activity in #my-team"

These run as cron jobs with results posted to your Slack DM.

Use `skip_dates` and `timezone` to skip holidays or vacation days — the next
run automatically covers the gap. See [Cron Jobs](cron-and-scheduling.md#skipping-dates).

## Parallel Research

Fan out research across multiple sources simultaneously:

> "Research EC2 pricing changes across all regions"

Aj Crew spawns subagents — one per region or source — and synthesizes the
results into a single summary.

## Auto-Collect Information

Replace manual information-gathering workflows. Use Aj Crew cron jobs to
gather data from your sources and publish to a dashboard or static site.

## Oncall Automation

- "Every 30 minutes, check my service health and alert me if anything is red"
- "When I get paged, pull the last 15 minutes of logs for my service"
- Combine with a custom oncall skill for ticket triage

## Code Review Assistance

Select an installed review agent from the terminal:

```
ajcrew agent list
ajcrew chat --agent <installed-review-agent>
```

The agent reads the pull-request diff, checks for common issues, and posts
review comments.

## Multi-Agent Workflows

List available agents with `ajcrew agent list`, then select one for a CLI chat with `ajcrew chat --agent <agent-name>`.

Each installed agent has its own system prompt, tools, and skills — scoped via
per-agent MCP configuration.

## Tips

- **Unattended overnight runs**: For `ajcrew run`, allowlist the tools the spec needs in `hooks.auto_approve_tools`; for a gateway started with `--approval yolo`, use an isolated `AJCREW_HOME`. Review the pull requests in the morning.
- **Workspace isolation**: Use `AJCREW_HOME` and `AJCREW_PORT` env vars to run multiple Aj Crew instances with separate data.
- **Background gateway**: Use a macOS Launch Agent or systemd service to keep the gateway running across reboots (see [Getting Started](getting-started.md)).
