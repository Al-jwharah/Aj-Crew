const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  SCHEME,
  deepLinkFromArgv,
  isAppName,
  isCrewName,
  isSshHost,
  resolveDeepLink,
} = require("../deep-link");

describe("resolveDeepLink accepts the local shapes", () => {
  it("bare scheme raises the window and routes nowhere", () => {
    for (const raw of ["ajcrew://", "ajcrew:", "AJCREW://"]) {
      assert.deepEqual(resolveDeepLink(raw), { ok: true, route: "", slotKey: "" }, raw);
    }
  });

  it("chat?sid= routes to the session and reports the slot key", () => {
    const r = resolveDeepLink("ajcrew://chat?sid=cos-quick-chat-high");
    assert.deepEqual(r, { ok: true, route: "/chat?sid=cos-quick-chat-high", slotKey: "cos-quick-chat-high" });
    assert.deepEqual(resolveDeepLink("ajcrew://chat/?sid=k"), { ok: true, route: "/chat?sid=k", slotKey: "k" });
  });

  it("re-encodes the sid rather than copying the input", () => {
    // `:` and `.` are legal in gateway slot keys; the route must carry them
    // encoded exactly as the SPA's own deep link does.
    const r = resolveDeepLink("ajcrew://chat?sid=slack_1712345678.123456");
    assert.equal(r.ok, true);
    assert.equal(r.route, `/chat?sid=${encodeURIComponent("slack_1712345678.123456")}`);
    const r2 = resolveDeepLink("ajcrew://chat?sid=hook%3Acos%3Amenubar-chat");
    assert.equal(r2.ok, true);
    assert.equal(r2.slotKey, "hook:cos:menubar-chat");
    assert.equal(r2.route, "/chat?sid=hook%3Acos%3Amenubar-chat");
  });

  it("apps/detail/<name> routes to that app's detail page and carries no session", () => {
    assert.deepEqual(resolveDeepLink("ajcrew://apps/detail/keeb-crew"), {
      ok: true,
      route: "/apps/detail/keeb-crew",
      slotKey: "",
    });
    // A trailing slash and host case are the URL parser's business, as for chat.
    assert.deepEqual(resolveDeepLink("ajcrew://apps/detail/mochi/"), { ok: true, route: "/apps/detail/mochi", slotKey: "" });
    assert.deepEqual(resolveDeepLink("ajcrew://APPS/detail/a1"), { ok: true, route: "/apps/detail/a1", slotKey: "" });
  });

  it("an app name is admitted only in the manifest's own kebab-case grammar", () => {
    // Mirrors KEBAB_RE in src/aj_crew/apps/manifest_names.py: a name the
    // manifest validator would refuse never becomes a route.
    for (const raw of [
      "ajcrew://apps/detail/Keeb-Crew",
      "ajcrew://apps/detail/keeb_crew",
      "ajcrew://apps/detail/-keeb",
      "ajcrew://apps/detail/keeb-",
      "ajcrew://apps/detail/keeb--crew",
      "ajcrew://apps/detail/keeb.crew",
      "ajcrew://apps/detail/keeb%2Dcrew",
      `ajcrew://apps/detail/${"a".repeat(129)}`,
    ]) {
      assert.deepEqual(resolveDeepLink(raw), { ok: false, reason: "invalid app name" }, raw);
    }
    assert.equal(resolveDeepLink(`ajcrew://apps/detail/${"a".repeat(128)}`).ok, true);
  });
});

describe("remote-crew/add fills in the Remote Crew add form", () => {
  const ok = (route) => ({ ok: true, route, slotKey: "" });

  it("routes to Settings -> Remote Crew with the host, port and label rebuilt from the link", () => {
    assert.deepEqual(
      resolveDeepLink("ajcrew://remote-crew/add?host=devbox.example.com&port=5476&name=Dev%20box"),
      ok("/settings/instances?host=devbox.example.com&port=5476&name=Dev%20box"),
    );
    // Only host is required; a link without port or name leaves those fields be.
    assert.deepEqual(resolveDeepLink("ajcrew://remote-crew/add?host=devbox"), ok("/settings/instances?host=devbox"));
    // Host case, a trailing slash and key order are the URL parser's business.
    assert.deepEqual(
      resolveDeepLink("ajcrew://REMOTE-CREW/add/?name=Dev&host=devbox"),
      ok("/settings/instances?host=devbox&name=Dev"),
    );
  });

  it("joins user and host into the form's user@host SSH host", () => {
    assert.deepEqual(
      resolveDeepLink("ajcrew://remote-crew/add?host=devbox.example.com&user=me"),
      ok("/settings/instances?host=me%40devbox.example.com"),
    );
    // A host that already names its user needs no user key.
    assert.deepEqual(
      resolveDeepLink("ajcrew://remote-crew/add?host=me%40devbox"),
      ok("/settings/instances?host=me%40devbox"),
    );
  });

  it("re-encodes the label rather than copying the input", () => {
    const r = resolveDeepLink("ajcrew://remote-crew/add?host=h&name=Caf%C3%A9+%26+co");
    assert.equal(r.ok, true);
    assert.equal(r.route, `/settings/instances?host=h&name=${encodeURIComponent("Café & co")}`);
    assert.equal(new URL(r.route, "http://x").searchParams.get("name"), "Café & co");
  });

  const refused = [
    ["ajcrew://remote-crew", "unknown route"],
    ["ajcrew://remote-crew/", "unknown route"],
    ["ajcrew://remote-crew/connect?host=h", "unknown route"],
    ["ajcrew://remote-crew/add/now?host=h", "unknown route"],
    ["ajcrew://remote-crew/add", "missing host"],
    ["ajcrew://remote-crew/add?name=Dev", "missing host"],
    ["ajcrew://remote-crew/add?host=h&connect=1", "unknown query parameter"],
    ["ajcrew://remote-crew/add?host=h&remote_bin=%2Ftmp%2Fx", "unknown query parameter"],
    ["ajcrew://remote-crew/add?host=h&token=abc", "unknown query parameter"],
    ["ajcrew://remote-crew/add?host=h&HOST=h", "unknown query parameter"],
    ["ajcrew://remote-crew/add?host=a&host=b", "repeated query parameter"],
    ["ajcrew://remote-crew/add?host=h&name=a&name=b", "repeated query parameter"],
    ["ajcrew://remote-crew/add?host=", "invalid host"],
    ["ajcrew://remote-crew/add?host=-oProxyCommand%3Dcalc", "invalid host"],
    ["ajcrew://remote-crew/add?host=h&user=-oProxyCommand%3Dcalc", "invalid host"],
    ["ajcrew://remote-crew/add?host=a%20b", "invalid host"],
    ["ajcrew://remote-crew/add?host=%20devbox", "invalid host"],
    ["ajcrew://remote-crew/add?host=a%3Bb", "invalid host"],
    ["ajcrew://remote-crew/add?host=me%40h&user=you", "invalid host"],
    ["ajcrew://remote-crew/add?host=h&user=", "invalid host"],
    ["ajcrew://remote-crew/add?host=h&user=a%40b", "invalid host"],
    [`ajcrew://remote-crew/add?host=${"a".repeat(256)}`, "invalid host"],
    [`ajcrew://remote-crew/add?host=${"a".repeat(250)}&user=abcde`, "invalid host"],
    ["ajcrew://remote-crew/add?host=h&port=", "invalid port"],
    ["ajcrew://remote-crew/add?host=h&port=0", "invalid port"],
    ["ajcrew://remote-crew/add?host=h&port=05476", "invalid port"],
    ["ajcrew://remote-crew/add?host=h&port=65536", "invalid port"],
    ["ajcrew://remote-crew/add?host=h&port=-1", "invalid port"],
    ["ajcrew://remote-crew/add?host=h&port=80abc", "invalid port"],
    ["ajcrew://remote-crew/add?host=h&port=%E0%A5%AB", "invalid port"],
    ["ajcrew://remote-crew/add?host=h&name=", "invalid name"],
    ["ajcrew://remote-crew/add?host=h&name=%20%20", "invalid name"],
    ["ajcrew://remote-crew/add?host=h&name=a%0Ab", "invalid name"],
    ["ajcrew://remote-crew/add?host=h&name=a%00b", "invalid name"],
    ["ajcrew://remote-crew/add?host=h&name=%E2%80%AEevil", "invalid name"],
    ["ajcrew://remote-crew/add?host=h&name=a%E2%80%8Bb", "invalid name"],
    [`ajcrew://remote-crew/add?host=h&name=${"a".repeat(201)}`, "invalid name"],
    // The authority carries no credentials or port, and a fragment is refused,
    // exactly as for the other shapes.
    ["ajcrew://me@remote-crew/add?host=h", "credentials or port in URL"],
    ["ajcrew://remote-crew:22/add?host=h", "credentials or port in URL"],
    ["ajcrew://remote-crew/add?host=h#connect", "fragment not allowed"],
    [`ajcrew://remote-crew/add?host=h&name=${"a".repeat(8192)}`, "link too long"],
  ];
  for (const [raw, reason] of refused) {
    it(`${JSON.stringify(raw).slice(0, 70)} -> ${reason}`, () => {
      assert.deepEqual(resolveDeepLink(raw), { ok: false, reason });
    });
  }

  it("caps the whole link at 8192 characters and the label at 200 code points", () => {
    const head = "ajcrew://remote-crew/add?host=h&name=";
    assert.equal(resolveDeepLink(head + "a".repeat(200)).ok, true);
    // 200 astral characters are 400 UTF-16 units; the registry counts 200.
    assert.equal(resolveDeepLink(head + encodeURIComponent("\u{1F680}".repeat(200))).ok, true);
    assert.equal(resolveDeepLink(head + encodeURIComponent("\u{1F680}".repeat(201))).reason, "invalid name");
    const atCap = "ajcrew://remote-crew/add?host=h&name=" + "%41".repeat(Math.floor((8192 - head.length) / 3));
    assert.ok(atCap.length <= 8192);
    assert.equal(resolveDeepLink(atCap).reason, "invalid name");
    assert.equal(resolveDeepLink(atCap + "%41%41%41").reason, "link too long");
  });

  it("never returns a route outside the Remote Crew page or with a key the form does not take", () => {
    const probes = [
      "ajcrew://remote-crew/add?host=h&name=%2F..%2F..%2Fchat",
      "ajcrew://remote-crew/add?host=h&name=x%26token%3Dabc",
      "ajcrew://remote-crew/add?host=h&name=x%23frag",
      "ajcrew://remote-crew/../chat?sid=k",
      "ajcrew://remote-crew/add/../../apps/detail/mochi",
      "ajcrew://remote-crew/%61dd?host=h",
    ];
    for (const raw of probes) {
      const r = resolveDeepLink(raw);
      if (!r.ok || !r.route.startsWith("/settings/")) continue;
      const url = new URL(r.route, "http://x");
      assert.equal(url.pathname, "/settings/instances", raw);
      assert.equal(url.hash, "", raw);
      for (const key of url.searchParams.keys()) assert.ok(["host", "port", "name"].includes(key), `${raw}: ${key}`);
    }
  });
});

describe("isSshHost agrees with the gateway's validate_ssh_host", () => {
  // test/test_cli_open.py runs the same hosts through validate_ssh_host, so the
  // two cannot drift apart without one side going red.
  const samples = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "ssh-host-samples.json"), "utf8"));

  it("accepts every valid sample", () => {
    assert.ok(samples.valid.length > 0);
    for (const host of samples.valid) assert.equal(isSshHost(host), true, JSON.stringify(host));
  });

  it("refuses every invalid sample", () => {
    assert.ok(samples.invalid.length > 0);
    for (const host of samples.invalid) assert.equal(isSshHost(host), false, JSON.stringify(host));
  });

  it("refuses surrounding whitespace the gateway would strip, non-strings, and hosts over the cap", () => {
    for (const host of [" devbox", "devbox ", "devbox\n", "\tdevbox"]) assert.equal(isSshHost(host), false, JSON.stringify(host));
    for (const value of [undefined, null, 7, ["devbox"], { host: "devbox" }]) assert.equal(isSshHost(value), false);
    assert.equal(isSshHost("a".repeat(255)), true);
    assert.equal(isSshHost("a".repeat(256)), false);
  });
});

describe("isCrewName", () => {
  it("takes an ordinary label, punctuation and non-Latin scripts included", () => {
    for (const name of ["Dev box", "devbox-1", "Café & co", "开发机", "Team's box (us-west-2)"]) {
      assert.equal(isCrewName(name), true, name);
    }
  });
  it("refuses blank, control and invisible formatting characters", () => {
    for (const name of ["", "   ", "a\tb", "a\u0007b", "a\u0085b", "a\u200Bb", "a\u202Eb", "a\u2066b", "\uFEFFa"]) {
      assert.equal(isCrewName(name), false, JSON.stringify(name));
    }
    for (const value of [undefined, null, 7, ["a"]]) assert.equal(isCrewName(value), false);
  });
});

describe("isAppName agrees with the manifest grammar", () => {
  // test/test_cli_open.py runs the same names through KEBAB_RE, so the two
  // grammars cannot drift apart without one side going red.
  const samples = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "app-name-samples.json"), "utf8"));

  it("accepts every valid sample", () => {
    assert.ok(samples.valid.length > 0);
    for (const name of samples.valid) assert.equal(isAppName(name), true, JSON.stringify(name));
  });

  it("refuses every invalid sample", () => {
    assert.ok(samples.invalid.length > 0);
    for (const name of samples.invalid) assert.equal(isAppName(name), false, JSON.stringify(name));
  });

  it("refuses non-strings and names over the length cap", () => {
    for (const value of [undefined, null, 7, ["a"], { name: "a" }]) assert.equal(isAppName(value), false);
    assert.equal(isAppName("a".repeat(128)), true);
    assert.equal(isAppName("a".repeat(129)), false);
  });
});

describe("resolveDeepLink: a session on a remote crew", () => {
  it("routes crew + sid with no sid parameter an older dashboard would read", () => {
    const r = resolveDeepLink("ajcrew://chat?crew=dev-box&sid=hook%3Acos%3Amenubar-chat");
    assert.deepEqual(r, {
      ok: true,
      route: "/chat?crew=dev-box&crewSid=hook%3Acos%3Amenubar-chat",
      slotKey: "hook:cos:menubar-chat",
    });
    assert.equal(new URL(r.route, "http://x.invalid").searchParams.has("sid"), false);
    assert.equal(resolveDeepLink("ajcrew://chat?sid=k&crew=dev-box").route, "/chat?crew=dev-box&crewSid=k");
  });

  it("a crew that is not a crew id routes to the value-free error, never silence", () => {
    for (const crew of ["Work%20Box", "Dev", "-x", "a%2Fb", ""]) {
      assert.deepEqual(resolveDeepLink(`ajcrew://chat?crew=${crew}&sid=k`), {
        ok: true,
        route: "/chat?crewError=1",
        slotKey: "",
      }, crew);
    }
  });

  it("caps the key at the hint store's 128 characters and keeps the leading-character rule", () => {
    assert.equal(resolveDeepLink(`ajcrew://chat?crew=c&sid=${"a".repeat(128)}`).ok, true);
    for (const sid of ["a".repeat(129), "..", ".", "-x", "a%20b"]) {
      assert.deepEqual(resolveDeepLink(`ajcrew://chat?crew=c&sid=${sid}`), { ok: false, reason: "invalid sid" }, sid);
    }
  });

  it("refuses a third parameter or a repeated crew", () => {
    for (const raw of [
      "ajcrew://chat?crew=c&sid=k&token=t",
      "ajcrew://chat?crew=c&crew=d&sid=k",
      "ajcrew://chat?crew=c",
      "ajcrew://chat?crew=c&slot=k",
    ]) {
      const r = resolveDeepLink(raw);
      assert.equal(r.ok, false, raw);
    }
  });

  it("the crew key rule is the slot-key rule capped at the hint store's limit", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "deep-link.js"), "utf8");
    const pane = fs.readFileSync(path.join(__dirname, "..", "..", "src", "lib", "paneLastSlot.ts"), "utf8");
    assert.match(source, /const SLOT_KEY_RE = \/\^\[A-Za-z0-9\]\[A-Za-z0-9\._:-\]\{0,199\}\$\/;/);
    assert.match(pane, /\/\^\[A-Za-z0-9\._:-\]\{1,128\}\$\//);
    assert.match(source, /const CREW_SLOT_KEY_RE = \/\^\[A-Za-z0-9\]\[A-Za-z0-9\._:-\]\{0,127\}\$\/;/);
    // The pane's check on the posted key must accept exactly what the resolver let through.
    const crewLink = fs.readFileSync(path.join(__dirname, "..", "..", "src", "lib", "crewDeepLink.ts"), "utf8");
    assert.match(crewLink, /\/\^\[A-Za-z0-9\]\[A-Za-z0-9\._:-\]\{0,127\}\$\/\.test\(v\)/);
  });
});

describe("resolveDeepLink refuses everything else", () => {
  const refused = [
    ["", "empty"],
    ["not a url", "unparseable"],
    ["https://github.com/Al-jwharah/Aj-Crew", "wrong scheme"],
    ["ajcrew://user:pw@chat", "credentials or port in URL"],
    ["ajcrew://chat:5476", "credentials or port in URL"],
    ["ajcrew://chat#frag", "fragment not allowed"],
    ["ajcrew://evil", "unknown route"],
    ["ajcrew://chat/extra?sid=x", "unknown route"],
    ["ajcrew://settings", "unknown route"],
    ["ajcrew://settings/browser", "unknown route"],
    ["ajcrew://artifacts/cr-queue", "unknown route"],
    ["ajcrew://chat", "missing sid"],
    ["ajcrew://chat?token=abc", "unknown query parameter"],
    ["ajcrew://chat?sid=a&token=b", "unknown query parameter"],
    ["ajcrew://chat?sid=a&sid=b", "unknown query parameter"],
    ["ajcrew://?sid=x", "unknown route"],
    ["ajcrew://chat?sid=", "invalid sid"],
    ["ajcrew://chat?sid=%3Cscript%3E", "invalid sid"],
    ["ajcrew://chat?sid=a%20b", "invalid sid"],
    ["ajcrew://chat?sid=-leading-dash", "invalid sid"],
    [`ajcrew://chat?sid=${"a".repeat(201)}`, "invalid sid"],
    // Under apps/ only the detail page is a target: not the store pages, not the
    // app's own page, and nothing the page could read as an instruction.
    ["ajcrew://apps", "unknown route"],
    ["ajcrew://apps/library", "unknown route"],
    ["ajcrew://apps/-/updates", "unknown route"],
    ["ajcrew://apps/keeb-crew", "unknown route"],
    ["ajcrew://apps/migrate/keeb-crew", "unknown route"],
    ["ajcrew://apps/detail", "unknown route"],
    ["ajcrew://apps/detail/keeb-crew/settings", "unknown route"],
    ["ajcrew://apps/detail/keeb-crew?autoAction=install", "unknown query parameter"],
    ["ajcrew://apps/detail/keeb-crew?sid=x", "unknown query parameter"],
    ["ajcrew://apps/detail/keeb-crew#enable", "fragment not allowed"],
    ["ajcrew://apps:5476/detail/keeb-crew", "credentials or port in URL"],
  ];
  for (const [raw, reason] of refused) {
    it(`${JSON.stringify(raw).slice(0, 60)} -> ${reason}`, () => {
      const r = resolveDeepLink(raw);
      assert.equal(r.ok, false);
      assert.equal(r.reason, reason);
    });
  }

  it("never returns a route containing characters outside the admitted set", () => {
    const probes = [
      "ajcrew://chat?sid=%0D%0Ainjected",
      "ajcrew://chat?sid=x%00y",
      "ajcrew://chat?sid=javascript:alert(1)",
      "ajcrew://chat?sid=..%2F..%2Fetc",
    ];
    for (const raw of probes) {
      const r = resolveDeepLink(raw);
      if (r.ok) assert.match(r.route, /^\/chat\?sid=[A-Za-z0-9._%-]*$/, raw);
    }
    const appProbes = [
      "ajcrew://apps/detail/%0D%0Ainjected",
      "ajcrew://apps/detail/x%00y",
      "ajcrew://apps/detail/javascript:alert(1)",
      "ajcrew://apps/detail/..%2F..%2Fsettings",
      "ajcrew://apps/detail/keeb-crew%3Fautoaction%3Dinstall",
    ];
    for (const raw of appProbes) {
      const r = resolveDeepLink(raw);
      if (r.ok) assert.match(r.route, /^\/apps\/detail\/[a-z0-9-]+$/, raw);
    }
  });

  it("dot-segments are normalized by the URL parser and cannot escape the chat route", () => {
    // WHATWG parsing collapses `..` before this module sees the path, so a
    // traversal attempt lands on the chat route's root or on a refused path.
    assert.deepEqual(resolveDeepLink("ajcrew://chat/..?sid=k"), { ok: true, route: "/chat?sid=k", slotKey: "k" });
    assert.deepEqual(resolveDeepLink("ajcrew://chat/%2e%2e?sid=k"), { ok: true, route: "/chat?sid=k", slotKey: "k" });
    for (const raw of ["ajcrew://chat/../settings?sid=k", "ajcrew://settings/../chat?sid=k"]) {
      const r = resolveDeepLink(raw);
      if (r.ok) assert.match(r.route, /^\/chat\?sid=k$/, raw);
      else assert.equal(r.reason, "unknown route", raw);
    }
  });

  it("dot-segments cannot turn an app link into another route", () => {
    // `..` is collapsed before the segments are read, so a traversal lands on
    // a two-segment detail path (rebuilt under /apps/detail/) or is refused.
    assert.deepEqual(resolveDeepLink("ajcrew://apps/../detail/mochi"), { ok: true, route: "/apps/detail/mochi", slotKey: "" });
    for (const raw of [
      "ajcrew://apps/detail/../library",
      "ajcrew://apps/detail/../../settings",
      "ajcrew://apps/detail/keeb-crew/../../../settings",
      "ajcrew://chat/../apps/detail/mochi?sid=k",
    ]) {
      const r = resolveDeepLink(raw);
      if (r.ok) assert.match(r.route, /^\/apps\/detail\/[a-z0-9-]+$/, raw);
      else assert.equal(r.reason, "unknown route", raw);
    }
  });
});

describe("deepLinkFromArgv", () => {
  it("picks the ajcrew URL out of a Windows/Linux second-instance argv", () => {
    assert.equal(
      deepLinkFromArgv(["/usr/bin/ajcrew", "--no-sandbox", "ajcrew://chat?sid=x"]),
      "ajcrew://chat?sid=x",
    );
  });
  it("answers empty for a macOS launch (no URL in argv) and for junk", () => {
    assert.equal(deepLinkFromArgv(["/Applications/AjCrew.app/Contents/MacOS/AjCrew"]), "");
    assert.equal(deepLinkFromArgv(["x", "https://example.com"]), "");
    assert.equal(deepLinkFromArgv(null), "");
  });
  it("takes the last URL when more than one is present", () => {
    assert.equal(deepLinkFromArgv(["bin", "ajcrew://chat?sid=a", "ajcrew://chat?sid=b"]), "ajcrew://chat?sid=b");
  });
});

describe("the scheme is registered with electron-builder", () => {
  it("package.json build.protocols names the same scheme the resolver accepts", () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
    const protocols = pkg.build && pkg.build.protocols;
    assert.ok(Array.isArray(protocols) && protocols.length, "build.protocols is declared");
    const schemes = protocols.flatMap((p) => p.schemes || []);
    assert.ok(schemes.includes(SCHEME), `protocols.schemes includes ${SCHEME}`);
  });
});
