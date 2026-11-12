export const FEATURES = [
  { icon: '01', title: 'Multi-Session Chat', desc: 'Tabbed sessions with streaming markdown, inline tool calls, TTS, and Virtuoso-powered rendering. CLI, Slack, Dashboard, or TUI.', tag: 'Core' },
  { icon: '02', title: 'Agent Orchestration', desc: 'Hot-swap multiple agent types per thread. Discovery, warm session pool, conductor skill routing.', tag: 'AI' },
  { icon: '03', title: 'Cron & Heartbeat', desc: 'Recurring jobs, one-shot timers, skip-dates, and a self-healing heartbeat loop that survives gateway restarts.', tag: 'Ops' },
  { icon: '04', title: 'Persistent Memory', desc: 'Episodic + semantic + vector memory. Learns corrections, tracks projects, decays history over 90 days.', tag: 'AI' },
  { icon: '05', title: 'Parallel Subagents', desc: 'Fan-out independent tasks to parallel agents. Results auto-inject as completion events.', tag: 'Core' },
  { icon: '06', title: 'Autonomous Task Runner', desc: 'Give it a spec, walk away. Git-isolated execution, checkpoint resume, retry + replan, learn from failures.', tag: 'AI' },
  { icon: '07', title: 'MCP Tools', desc: 'AWS, GitHub, CI/CD, issue trackers, calendars, email — all via Model Context Protocol.', tag: 'Ops' },
  { icon: '08', title: 'Slack & Dashboard', desc: 'Same agent, same context. Voice memos via Whisper. Images to vision. Presigned 1-click dashboard links.', tag: 'Core' },
  { icon: '09', title: 'Trust & Security', desc: 'Tool approvals, tamper-resistant deny patterns, an audit trail, and OS sandboxing where available.', tag: 'Ops' },
];

export const TAG_CLS: Record<string, string> = {
  Core: 'bg-teal-500/10 text-teal-400',
  AI: 'bg-amber-300/10 text-amber-300',
  Ops: 'bg-green-500/10 text-green-400',
  UX: 'bg-rose-500/10 text-rose-400',
};

export const ARCH = [
  { label: 'Slack / Dashboard', sub: 'WebSocket + Events API' },
  { label: 'Gateway', sub: 'Python async orchestrator' },
  { label: 'Session Pool', sub: 'Warm agent processes' },
  { label: 'Agent Harness', sub: 'ACP (kiro-cli by default)' },
  { label: 'MCP Servers', sub: 'Tool servers' },
];

export const TERMINAL_LINES = [
  { prompt: true, text: 'ajcrew gateway' },
  { text: 'Aj Crew starting...' },
  { text: '   Dashboard:  ', hl: 'http://localhost:5476' },
  { text: '   Slack:      ', hl: 'connected (Socket Mode)' },
  { text: '   MCP:        ', hl: '12 servers loaded' },
  { text: '   Agents:     ', hl: '17 available' },
  { text: '   Memory:     ', hl: 'vector + episodic + semantic' },
  { text: '   Cron:       ', hl: '3 jobs scheduled' },
  { comment: '   Ready. Type !dashboard in Slack to connect.' },
];

export const IN_ACTION = [
  { label: 'Voice', user: '[sends a voice memo in Slack]', bot: 'Transcribed: "Can you check if the deployment to prod finished?"\nChecking your pipeline now — Deployment d-4829 completed 12 minutes ago. All health checks passing.' },
  { label: 'Oncall', user: "who's on call for MyService?", bot: '@janedoe (secondary, started Monday). Primary is @johndoe. Want me to page them?' },
  { label: 'Cron', user: 'every weekday at 9am give me a pipeline briefing', bot: "Created cron job. I'll check your pipelines every weekday at 9:00 AM and send you the results." },
  { label: 'Learn', user: 'no, always use the staging profile for deploy credentials', bot: "Learned: Use the staging profile for deploy credentials. I won't make this mistake again." },
  { label: 'Vision', user: '[pastes a screenshot of an error]', bot: "That's a NullPointerException in OrderService.java:142. The customer field is null when..." },
];

export const FAQ = [
  { q: 'Does any data leave my machine?', a: 'Aj Crew runs on your own hardware and the dashboard binds to loopback by default. Model inference goes to the provider behind the agent harness you sign in to, and anything you connect (Slack, MCP servers, a cloud speech service) talks to that service. First start downloads the embedding model. Usage telemetry is off by default.' },
  { q: 'What LLM models are supported?', a: 'The models your agent harness offers. kiro-cli is the default harness and needs its own install and sign-in; other verified ACP harnesses are selected in the configuration. Switch models mid-session from the dashboard.' },
  { q: 'Can non-engineers use it?', a: 'Yes — PMs, designers, data scientists, and any role. The install is a source build today, so it takes someone comfortable with a terminal to set it up; after that the dashboard needs none.' },
  { q: 'How do I add custom tools?', a: 'Add an MCP server from the dashboard, or declare it in ~/.kiro/settings/mcp.json, the global MCP config the default harness reads.' },
  { q: 'How do I contribute?', a: 'Fork the repo on GitHub, create a branch, and open a PR. See CONTRIBUTING.md for full guidelines.' },
];

export const THEMES = [
  '#22c55e', '#f59e0b', '#6366f1', '#f43f5e', '#06b6d4',
  '#a78bfa', '#88c0d0', '#e0af68', '#eb6f92', '#fab387',
  '#d4be98', '#f9e2af', '#93a1a1', '#7dcfff',
];
