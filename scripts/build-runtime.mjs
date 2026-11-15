#!/usr/bin/env node
// Build the frozen Python runtime into dist-runtime/.
//
// PyInstaller freezes the interpreter it runs in and bundles whatever that
// interpreter can import. So the build never uses a shared Python: it creates
// build/python-venv from the version pinned in .python-version, installs exactly
// the hash-checked packages in requirements.lock, and runs the spec from there.
//
// Usage: node scripts/build-runtime.mjs [--check] [--distpath DIR] [--workpath DIR]
//   --check  only report which interpreter would be used, then exit
// Set RAILWATCH_BUILD_PYTHON to a python executable to skip interpreter discovery.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_DIST = "dist-runtime";
// Reports the base interpreter even when run from inside a virtual environment,
// so the build environment never depends on another one.
// The answer is one line of JSON, which json.dumps keeps pure ASCII. On Windows
// Python encodes piped output in the ANSI code page: under a Chinese account name
// the path would arrive garbled (GBK) or fail to print at all (CP1252).
const PROBE = "import json, sys; print(json.dumps(['%d.%d' % sys.version_info[:2], sys.version.split()[0], "
  + "getattr(sys, '_base_executable', None) or sys.executable]))";

function capture(command, args) {
  return spawnSync(command, args, { encoding: "utf8", windowsHide: true });
}

/** ".python-version" content -> "major.minor". */
export function pinnedPythonVersion(text) {
  const match = /^(\d+)\.(\d+)(?:\.\d+)?$/.exec(String(text).trim());
  if (!match) throw new Error(`.python-version must hold a version such as 3.14, not "${String(text).trim()}"`);
  return `${match[1]}.${match[2]}`;
}

/** Where to look for the pinned interpreter, in order. */
export function interpreterCandidates(version, { platform = process.platform, env = process.env } = {}) {
  if (env.RAILWATCH_BUILD_PYTHON) return [{ command: env.RAILWATCH_BUILD_PYTHON, args: [] }];
  return [
    { command: "python", args: [] },
    { command: "python3", args: [] },
    platform === "win32" ? { command: "py", args: [`-${version}`] } : { command: `python${version}`, args: [] },
    // Prints the path of an interpreter uv knows about; it does not download one.
    { command: "uv", args: ["python", "find", version], locator: true },
  ];
}

export function probeInterpreter(command, args = [], spawn = capture) {
  const result = spawn(command, [...args, "-c", PROBE]);
  if (result.error || result.status !== 0) return null;
  let fields;
  try {
    fields = JSON.parse(String(result.stdout));
  } catch {
    return null;
  }
  if (!Array.isArray(fields) || fields.length !== 3 || !fields.every((field) => field && typeof field === "string")) return null;
  const [version, fullVersion, executable] = fields;
  return { version, fullVersion, executable };
}

export function findInterpreter(version, { platform, env, spawn = capture } = {}) {
  const checked = [];
  for (const candidate of interpreterCandidates(version, { platform, env })) {
    const label = [candidate.command, ...candidate.args].join(" ");
    let { command, args } = candidate;
    if (candidate.locator) {
      const located = spawn(command, args);
      const found = located.error || located.status !== 0 ? "" : String(located.stdout).split(/\r?\n/)[0].trim();
      if (!found) {
        checked.push(`${label}: not found`);
        continue;
      }
      command = found;
      args = [];
    }
    const probed = probeInterpreter(command, args, spawn);
    if (probed?.version === version) return probed;
    checked.push(`${label}: ${probed ? `Python ${probed.fullVersion}` : "not found"}`);
  }
  throw new Error(
    `Python ${version} (pinned in .python-version) was not found. Checked ${checked.join("; ")}. ` +
    `Install Python ${version} from python.org or with "uv python install ${version}", ` +
    "or set RAILWATCH_BUILD_PYTHON to its executable.",
  );
}

export function venvPythonPath(venvDirectory, platform = process.platform) {
  return platform === "win32"
    ? path.join(venvDirectory, "Scripts", "python.exe")
    : path.join(venvDirectory, "bin", "python");
}

/** Changes whenever the lock or the base interpreter does, which rebuilds the environment. */
export function environmentStamp(lockText, interpreter) {
  return JSON.stringify({
    lock: createHash("sha256").update(lockText).digest("hex"),
    python: interpreter.fullVersion,
    executable: interpreter.executable,
  });
}

function run(command, args, what) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", windowsHide: true });
  if (result.error) throw new Error(`${what} could not start: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`${what} failed with exit code ${result.status}`);
}

function ensureBuildEnvironment(interpreter) {
  const venvDirectory = path.join(root, "build", "python-venv");
  const stampPath = path.join(venvDirectory, "railwatch-build-stamp.json");
  const python = venvPythonPath(venvDirectory);
  const stamp = environmentStamp(readFileSync(path.join(root, "requirements.lock"), "utf8"), interpreter);
  if (existsSync(python) && existsSync(stampPath) && readFileSync(stampPath, "utf8") === stamp) {
    console.log("Reusing build/python-venv (requirements.lock and interpreter unchanged)");
    return python;
  }
  console.log("Creating build/python-venv from requirements.lock");
  rmSync(venvDirectory, { recursive: true, force: true });
  mkdirSync(path.dirname(venvDirectory), { recursive: true });
  run(interpreter.executable, ["-m", "venv", venvDirectory], "Creating the virtual environment");
  run(python, ["-m", "pip", "install", "--disable-pip-version-check", "--require-hashes", "-r", "requirements.lock"],
    "Installing requirements.lock");
  // Written last: an interrupted install leaves no stamp and is redone next time.
  writeFileSync(stampPath, stamp);
  return python;
}

function main(argv) {
  const options = { check: false, distPath: DEFAULT_DIST, workPath: path.join("build", "runtime") };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--check") options.check = true;
    else if (argv[index] === "--distpath" && argv[index + 1]) options.distPath = argv[++index];
    else if (argv[index] === "--workpath" && argv[index + 1]) options.workPath = argv[++index];
    else throw new Error("Usage: node scripts/build-runtime.mjs [--check] [--distpath DIR] [--workpath DIR]");
  }
  const version = pinnedPythonVersion(readFileSync(path.join(root, ".python-version"), "utf8"));
  const interpreter = findInterpreter(version);
  console.log(`Python ${interpreter.fullVersion} at ${interpreter.executable}`);
  if (options.check) return;

  const python = ensureBuildEnvironment(interpreter);
  // electron-builder ships everything under dist-runtime, so start it empty.
  // A custom --distpath is left to PyInstaller, which only replaces its own output.
  if (options.distPath === DEFAULT_DIST) rmSync(path.join(root, DEFAULT_DIST), { recursive: true, force: true });
  run(python, ["-m", "PyInstaller", "RailWatch_runtime.spec", "--distpath", options.distPath,
    "--workpath", options.workPath, "-y"], "PyInstaller");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`::error::${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}
