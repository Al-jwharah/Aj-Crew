"use strict";

// What the SHIPPED build does about updates: it names no feed and no byte
// host, so the updater stands down without constructing anything and offers
// no download link. The rest of the suite injects a feed (makeDeps) and names
// a byte host (test/_preload.cjs) to exercise the lanes behind this gate, so
// the unset behavior is read here from a child process that inherits neither.

const { test } = require("node:test");
const assert = require("node:assert");
const { spawnSync } = require("node:child_process");
const path = require("node:path");

const { initAutoUpdate } = require("../auto-update");
const { makeDeps } = require("./auto-update-test-helpers");

const ELECTRON_DIR = path.join(__dirname, "..");

/** Run `script` in a fresh node with the update overrides removed (or set). */
function inChild(script, env = {}) {
  const childEnv = { ...process.env };
  delete childEnv.AJCREW_UPDATE_FEED;
  delete childEnv.AJCREW_DOWNLOAD_BASE;
  delete childEnv.NODE_OPTIONS;
  const out = spawnSync(process.execPath, ["-e", script], {
    cwd: ELECTRON_DIR,
    env: { ...childEnv, ...env },
    encoding: "utf8",
  });
  assert.strictEqual(out.status, 0, out.stderr);
  return JSON.parse(out.stdout);
}

const REPORT_DEFAULTS = `
  const u = require("./auto-update");
  process.stdout.write(JSON.stringify({
    feed: u.DEFAULT_FEED_BASE,
    download: u.DOWNLOAD_BASE,
    links: [
      u.manualDownloadUrl("stable", "darwin", "arm64"),
      u.manualDownloadUrl("stable", "win32", "x64"),
      u.manualDownloadUrl("nightly", "linux", "x64", "deb"),
    ],
  }));
`;

test("the shipped build names no update feed and no byte host", () => {
  const got = inChild(REPORT_DEFAULTS);
  assert.deepStrictEqual(got, { feed: "", download: "", links: [null, null, null] });
});

test("the shipped update code names no host of any other project", () => {
  const fs = require("node:fs");
  const sources = [
    path.join(ELECTRON_DIR, "auto-update.js"),
    ...fs.readdirSync(path.join(ELECTRON_DIR, "runtime", "update"))
      .filter((name) => name.endsWith(".js"))
      .map((name) => path.join(ELECTRON_DIR, "runtime", "update", name)),
  ];
  for (const file of sources) {
    const hosts = fs.readFileSync(file, "utf8").match(/https?:\/\/[a-z0-9.-]*kiro\.dev[^\s"'`)]*/gi) || [];
    assert.deepStrictEqual(hosts, [], `${path.basename(file)} names an upstream host`);
  }
});

test("AJCREW_DOWNLOAD_BASE names the byte host, and only over HTTPS or loopback", () => {
  const named = inChild(REPORT_DEFAULTS, { AJCREW_DOWNLOAD_BASE: "https://dl.example.test/" });
  assert.strictEqual(named.download, "https://dl.example.test");
  assert.strictEqual(named.links[0], "https://dl.example.test/desktop/stable/latest/AjCrew.dmg");

  const loopback = inChild(REPORT_DEFAULTS, { AJCREW_DOWNLOAD_BASE: "http://127.0.0.1:8799" });
  assert.strictEqual(loopback.download, "http://127.0.0.1:8799");

  for (const refused of ["http://dl.example.test", "ftp://dl.example.test", "not a url"]) {
    const got = inChild(REPORT_DEFAULTS, { AJCREW_DOWNLOAD_BASE: refused });
    assert.deepStrictEqual([got.download, got.links], ["", [null, null, null]], refused);
  }
});

test("a packaged build with no feed stands down as no-feed and contacts nothing", async () => {
  for (const osPlatform of ["darwin", "linux", "win32"]) {
    const { deps, calls } = makeDeps({ osPlatform });
    deps.feedBase = "";
    const lines = [];
    deps.log = { info: (m) => lines.push(m), warn: (m) => lines.push(m), error: (m) => lines.push(m) };
    const u = initAutoUpdate(deps);
    assert.strictEqual(u.disabled, "no-feed", osPlatform);
    await u.check();
    await u.download();
    await u.install();
    assert.deepStrictEqual(
      calls,
      { setFeedURL: [], checkForUpdates: 0, downloadUpdate: 0, quitAndInstall: [] },
      osPlatform,
    );
    assert.ok(lines.some((m) => /no update feed configured/.test(m)), osPlatform);
    assert.strictEqual(typeof u.getInfo, "function");
  }
});

test("the more specific refusals still win over no-feed", () => {
  const dev = makeDeps({ isPackaged: false });
  dev.deps.feedBase = "";
  assert.strictEqual(initAutoUpdate(dev.deps).disabled, "dev");

  const managed = makeDeps({ externallyManaged: { managedBy: "apt" } });
  managed.deps.feedBase = "";
  assert.strictEqual(initAutoUpdate(managed.deps).disabled, "externally-managed");
});

test("a named feed still arms the updater", async () => {
  const { deps, calls } = makeDeps();
  const u = initAutoUpdate(deps);
  assert.strictEqual(u.disabled, undefined);
  await u.check();
  assert.ok(calls.setFeedURL.length >= 1);
});
test("the publish URLs baked into packages name no real host", () => {
  // electron-builder needs a publish entry to emit app-update.yml, and writes
  // its URL into every package. A real host there is a host a packaged build
  // could reach if the no-feed gate were ever bypassed.
  const pkg = require("../package.json");
  const urls = [];
  (function walk(node) {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node.publish)) for (const p of node.publish) urls.push(p.url);
    for (const v of Object.values(node)) walk(v);
  })(pkg.build);
  assert.ok(urls.length >= 3, "expected the top-level, deb and rpm publish entries");
  for (const url of urls) {
    assert.match(new URL(url).hostname, /\.invalid$/, url);
  }
});
