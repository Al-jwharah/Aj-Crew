const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const { resolveHome, secretCandidates, canonicalHome } = require("../home-dir");

// Absolute paths are built with path.resolve, not written as POSIX literals:
// resolveHome() normalizes every override through path.resolve(), so on Windows
// a literal "/custom/home" comes back as "C:\custom\home" and a hardcoded
// expectation compares a normalized path against an unnormalized one. Deriving
// both sides the same way keeps this suite about the RESOLUTION RULES, which are
// platform-independent, rather than about path syntax, which is not.
const HOME = path.resolve(path.sep, "mock", "home");
const fakeOs = { homedir: () => HOME };
const emptyFs = { existsSync: () => false, readdirSync: () => [] };
const CANONICAL = path.join(HOME, ".ajcrew");
const LEGACY_KIRO = path.join(HOME, ".kiro", "crew");
const OVERRIDE = path.resolve(path.sep, "custom", "home");

describe("resolveHome", () => {
  it("returns the default ~/.ajcrew when no override or legacy dir is present", () => {
    assert.equal(resolveHome({ env: {}, os: fakeOs, path, fs: emptyFs }), CANONICAL);
  });

  it("falls back to ~/.kiro/crew when unmigrated legacy data exists, then switches once completed", () => {
    const preMigrationFs = {
      existsSync: (p) => p === LEGACY_KIRO,
      readdirSync: (p) => (p === LEGACY_KIRO ? ["config.json"] : []),
      readFileSync: () => "",
    };
    assert.equal(resolveHome({ env: {}, os: fakeOs, path, fs: preMigrationFs }), LEGACY_KIRO);

    const marker = path.join(CANONICAL, ".home_migration_state.json");
    const migratedFs = {
      existsSync: (p) => p === LEGACY_KIRO || p === marker,
      readdirSync: () => ["config.json"],
      readFileSync: (p) => (p === marker ? JSON.stringify({ state: "completed", version: 1 }) : ""),
    };
    assert.equal(resolveHome({ env: {}, os: fakeOs, path, fs: migratedFs }), CANONICAL);
  });

  it("returns a valid AJCREW_HOME override", () => {
    assert.equal(
      resolveHome({ env: { AJCREW_HOME: OVERRIDE }, os: fakeOs, path }),
      OVERRIDE,
    );
  });

  it("rejects a filesystem root override and falls back to canonical -- parity with paths.py", () => {
    // Backend _valid_override_home refuses a root via `p == p.parent`; Electron
    // must agree or the two read different config/secret homes. The root is
    // spelled per-platform ("/" vs "C:\") because that is what the rule is
    // about -- a path whose parent is itself -- and path.parse().root is the
    // only portable way to name the root of the volume this test runs on.
    const root = path.parse(path.resolve(path.sep)).root;
    assert.equal(
      resolveHome({ env: { AJCREW_HOME: root }, os: fakeOs, path, fs: emptyFs }),
      CANONICAL,
      `override ${root} should be rejected`,
    );
  });

  // The POSIX system-directory guard. Scoped to POSIX deliberately rather than
  // made cross-platform: the backend's list (_UNSAFE_HOME_PREFIXES) is literally
  // /usr, /System, /etc, and on Windows those are ordinary relative-looking
  // names that path.resolve() rewrites onto the current drive -- so asserting
  // them here would test Windows path syntax, not the shared rule. Windows'
  // equivalent protection is the root check above.
  it("rejects POSIX system-dir overrides and falls back to canonical -- parity with paths.py", { skip: process.platform === "win32" ? "POSIX-only rule (backend guards /usr, /System, /etc)" : false }, () => {
    for (const bad of ["/etc", "/usr", "/System"]) {
      assert.equal(
        resolveHome({ env: { AJCREW_HOME: bad }, os: fakeOs, path, fs: emptyFs }),
        CANONICAL,
        `override ${bad} should be rejected`,
      );
    }
  });

  it("expands a leading '~' in the override to an absolute path -- parity with Python expanduser()", () => {
    // Python _valid_override_home returns Path(override).expanduser().resolve();
    // Electron must NOT read a literal "~/foo" or the two diverge (GPT 5.6 MEDIUM).
    assert.equal(
      resolveHome({ env: { AJCREW_HOME: "~/foo" }, os: fakeOs, path, fs: emptyFs }),
      path.join(HOME, "foo"),
    );
    assert.equal(
      resolveHome({ env: { AJCREW_HOME: "~" }, os: fakeOs, path, fs: emptyFs }),
      HOME,
    );
    // secretCandidates uses the same expanded, absolute override.
    assert.deepEqual(secretCandidates({ env: { AJCREW_HOME: "~/foo" }, os: fakeOs, path, fs: emptyFs }), [
      path.join(HOME, "foo", ".local_secret"),
    ]);
  });
});

describe("secretCandidates (post-spawn, call-time resolution)", () => {
  it("env override is authoritative and sole", () => {
    const env = { AJCREW_HOME: OVERRIDE };
    assert.deepEqual(secretCandidates({ env, os: fakeOs, path, fs: emptyFs }), [
      path.join(OVERRIDE, ".local_secret"),
    ]);
  });

  it("uses the default home when no override is set", () => {
    // Mirrors the backend, which reads .local_secret from config_dir() only.
    assert.deepEqual(secretCandidates({ env: {}, os: fakeOs, path, fs: emptyFs }), [
      path.join(CANONICAL, ".local_secret"),
    ]);
  });

  it("ignores an invalid (root) override and uses the default home -- parity", () => {
    assert.deepEqual(secretCandidates({ env: { AJCREW_HOME: "/" }, os: fakeOs, path, fs: emptyFs }), [
      path.join(CANONICAL, ".local_secret"),
    ]);
  });
});

describe("path shape helpers", () => {
  it("canonical resolves to ~/.ajcrew", () => {
    assert.equal(canonicalHome(fakeOs, path), CANONICAL);
  });
});
