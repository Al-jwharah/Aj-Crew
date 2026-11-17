// Desktop data-home resolution -- a mirror of the backend's data-home resolver
// in src/aj_crew/config/paths.py (config_dir -> _resolve_default_home):
//   1. A valid AJCREW_HOME env override wins. INVALID overrides -- a
//      filesystem/drive root ("/" or "C:\") or a POSIX system dir
//      (/usr, /System, /etc) -- are rejected (paths.py _valid_override_home)
//      and fall through to the default, so both sides agree on which overrides
//      are honored.
//   2. Guarded ~/.kiro/crew -> ~/.ajcrew state machine:
//      ~/.ajcrew is the canonical standalone home. When ~/.kiro/crew exists
//      with real state and ~/.ajcrew does not yet carry a completed/fresh
//      .home_migration_state.json marker (or config.json), fall back cleanly to
//      ~/.kiro/crew until the backend's guarded migration completes.

const nodeFs = require("fs");
const nodeOs = require("os");
const nodePath = require("path");

const MIGRATION_STATE_FILE = ".home_migration_state.json";

function canonicalHome(os = nodeOs, path = nodePath) {
  return path.join(os.homedir(), ".ajcrew");
}

function legacyKiroHome(os = nodeOs, path = nodePath) {
  return path.join(os.homedir(), ".kiro", "crew");
}

function defaultHome({ os = nodeOs, path = nodePath, fs = nodeFs } = {}) {
  const target = canonicalHome(os, path);
  const legacy = legacyKiroHome(os, path);
  try {
    if (fs && typeof fs.readFileSync === "function") {
      const markerPath = path.join(target, MIGRATION_STATE_FILE);
      if (fs.existsSync(markerPath)) {
        const parsed = JSON.parse(fs.readFileSync(markerPath, "utf8"));
        if (parsed && (parsed.state === "completed" || parsed.state === "fresh")) {
          return target;
        }
        if (parsed && parsed.state === "migrating" && fs.existsSync(legacy)) {
          return legacy;
        }
      }
      if (fs.existsSync(path.join(target, "config.json"))) {
        return target;
      }
      if (fs.existsSync(legacy)) {
        const entries = typeof fs.readdirSync === "function" ? fs.readdirSync(legacy) : ["x"];
        if (entries.length > 0) return legacy;
      }
    }
  } catch {
    try {
      if (fs && typeof fs.existsSync === "function" && fs.existsSync(legacy)) {
        return legacy;
      }
    } catch {
      // Fall back to canonical ~/.ajcrew when probing is unavailable.
    }
  }
  return target;
}

/**
 * The resolved AJCREW_HOME override iff set AND valid, else null. Mirrors
 * paths.py _valid_override_home: the value is expanduser()'d + resolve()'d to a
 * normalized absolute path (so a literal "~/foo" or a relative override matches
 * Python instead of being read verbatim), then a filesystem/drive root or a
 * POSIX system dir (/usr, /System, /etc) is refused so the backend and Electron
 * never diverge on which override is honored.
 * @returns {string|null}
 */
function validOverride(env, os, path) {
  const raw = env.AJCREW_HOME;
  if (!raw) return null;
  // Expand a leading "~" against the home dir (path.resolve treats "~" as a
  // literal segment, unlike Python's expanduser()), then normalize to absolute.
  let expanded = raw;
  if (raw === "~") expanded = os.homedir();
  else if (raw.startsWith("~/") || raw.startsWith("~\\")) {
    expanded = path.join(os.homedir(), raw.slice(2));
  }
  const p = path.resolve(expanded);
  if (p === path.dirname(p)) return null; // "/" (POSIX) or "C:\" (Windows) root
  const segs = p.split(path.sep);
  if (segs[0] === "" && ["usr", "System", "etc"].includes(segs[1])) return null;
  return p; // normalized absolute path, matching Python expanduser().resolve()
}

/**
 * The data home whose config content governs this launch: a valid
 * AJCREW_HOME override, else the default ~/.kiro/crew.
 * @param {{env?: object, os?: object, path?: object}} deps
 * @returns {string}
 */
function resolveHome({ env = process.env, os = nodeOs, path = nodePath, fs = nodeFs } = {}) {
  return validOverride(env, os, path) || defaultHome({ os, path, fs });
}

/**
 * Candidate paths for .local_secret, re-resolved at call time. Mirrors the
 * backend, which reads it from config_dir() only -- the override when set, else
 * the default home.
 * @returns {string[]}
 */
function secretCandidates({ env = process.env, os = nodeOs, path = nodePath, fs = nodeFs } = {}) {
  const override = validOverride(env, os, path);
  const home = override || defaultHome({ os, path, fs });
  return [path.join(home, ".local_secret")];
}

module.exports = { resolveHome, secretCandidates, canonicalHome, legacyKiroHome, defaultHome };
