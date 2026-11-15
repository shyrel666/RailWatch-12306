import { mkdtempSync, readFileSync, rmdirSync, symlinkSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import yaml from "js-yaml";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  environmentStamp,
  findInterpreter,
  interpreterCandidates,
  pinnedPythonVersion,
  probeInterpreter,
  venvPythonPath,
} from "../../scripts/build-runtime.mjs";

const root = path.resolve(__dirname, "../..");
const read = (file: string) => readFileSync(path.join(root, file), "utf8");

type Spawned = { status: number | null; stdout: string; error?: Error };
/** Fake process table: command line -> interpreter it reports, or a path printed by a locator. */
function fakeSpawn(table: Record<string, { version: string; executable: string } | string>) {
  const calls: string[] = [];
  const spawn = (command: string, args: string[]): Spawned => {
    const probing = args.includes("-c");
    const key = [command, ...(probing ? args.slice(0, args.indexOf("-c")) : args)].join(" ");
    calls.push(key);
    const entry = table[key];
    if (entry === undefined) return { status: null, stdout: "", error: new Error("ENOENT") };
    if (typeof entry === "string") return { status: 0, stdout: `${entry}\n` };
    const [major, minor] = entry.version.split(".");
    return { status: 0, stdout: `${JSON.stringify([`${major}.${minor}`, entry.version, entry.executable])}\r\n` };
  };
  return { spawn, calls };
}

describe("build-runtime interpreter selection", () => {
  test("reads major.minor from .python-version and rejects anything else", () => {
    expect(pinnedPythonVersion("3.14\n")).toBe("3.14");
    expect(pinnedPythonVersion("3.14.10\r\n")).toBe("3.14");
    expect(() => pinnedPythonVersion("pypy3.11")).toThrow(".python-version");
    expect(() => pinnedPythonVersion("")).toThrow(".python-version");
  });

  test("looks on PATH first, then the platform launcher, then uv", () => {
    const labels = (platform: NodeJS.Platform) =>
      interpreterCandidates("3.14", { platform, env: {} }).map((item) => [item.command, ...item.args].join(" "));
    expect(labels("win32")).toEqual(["python", "python3", "py -3.14", "uv python find 3.14"]);
    expect(labels("darwin")).toEqual(["python", "python3", "python3.14", "uv python find 3.14"]);
    expect(interpreterCandidates("3.14", { platform: "win32", env: { RAILWATCH_BUILD_PYTHON: "C:\\py\\python.exe" } }))
      .toEqual([{ command: "C:\\py\\python.exe", args: [] }]);
  });

  test("skips a PATH python of another version and takes the first match", () => {
    const { spawn, calls } = fakeSpawn({
      python: { version: "3.10.8", executable: "D:\\python-3.10.8\\python.exe" },
      "py -3.14": { version: "3.14.10", executable: "C:\\Python314\\python.exe" },
    });
    expect(findInterpreter("3.14", { platform: "win32", env: {}, spawn }))
      .toEqual({ version: "3.14", fullVersion: "3.14.10", executable: "C:\\Python314\\python.exe" });
    expect(calls).toEqual(["python", "python3", "py -3.14"]);
  });

  test("falls back to an interpreter uv already has", () => {
    const { spawn } = fakeSpawn({
      python3: { version: "3.12.10", executable: "/usr/bin/python3" },
      "uv python find 3.14": "/Users/me/.local/share/uv/python/cpython-3.14/bin/python3.14",
      "/Users/me/.local/share/uv/python/cpython-3.14/bin/python3.14":
        { version: "3.14.3", executable: "/Users/me/.local/share/uv/python/cpython-3.14/bin/python3.14" },
    });
    expect(findInterpreter("3.14", { platform: "darwin", env: {}, spawn }).fullVersion).toBe("3.14.3");
  });

  test("names every place it looked when the pinned version is missing", () => {
    const { spawn } = fakeSpawn({ python: { version: "3.10.8", executable: "D:\\python-3.10.8\\python.exe" } });
    expect(() => findInterpreter("3.14", { platform: "win32", env: {}, spawn })).toThrow(
      "Checked python: Python 3.10.8; python3: not found; py -3.14: not found; uv python find 3.14: not found",
    );
  });

  test("an explicit RAILWATCH_BUILD_PYTHON of the wrong version is an error, not a fallback", () => {
    const { spawn, calls } = fakeSpawn({
      "D:\\old\\python.exe": { version: "3.10.8", executable: "D:\\old\\python.exe" },
      python: { version: "3.14.10", executable: "C:\\Python314\\python.exe" },
    });
    expect(() => findInterpreter("3.14", { platform: "win32", env: { RAILWATCH_BUILD_PYTHON: "D:\\old\\python.exe" }, spawn }))
      .toThrow("D:\\old\\python.exe: Python 3.10.8");
    expect(calls).toEqual(["D:\\old\\python.exe"]);
  });
});

describe("build-runtime probe output", () => {
  afterEach(() => vi.unstubAllEnvs());

  test("reads the probe's ASCII answer back into a Chinese interpreter path", () => {
    // What json.dumps prints for C:\Users\张三\...: nothing outside ASCII reaches the pipe.
    const stdout = '["3.14", "3.14.3", "C:\\\\Users\\\\\\u5f20\\u4e09\\\\Python314\\\\python.exe"]\r\n';
    expect(stdout).toMatch(/^[\x20-\x7e\r\n]+$/);
    expect(probeInterpreter("python", [], () => ({ status: 0, stdout })))
      .toEqual({ version: "3.14", fullVersion: "3.14.3", executable: "C:\\Users\\张三\\Python314\\python.exe" });
  });

  test.each(["", "Python 3.14.3\r\n", "[]", '["3.14", "3.14.3", ""]', '["3.14", "3.14.3", null]', '{"version": "3.14"}'])(
    "output that is not the probe's answer counts as no interpreter (%j)", (stdout) => {
      expect(probeInterpreter("python", [], () => ({ status: 0, stdout }))).toBeNull();
    });

  // Only Windows encodes piped output in a legacy code page. PYTHONIOENCODING stands in for
  // a Chinese (GBK) and a Western (CP1252) system on whichever machine runs the test.
  test.runIf(process.platform === "win32")("finds a real interpreter under a Chinese path in every code page", (context) => {
    let base;
    try {
      base = findInterpreter(pinnedPythonVersion(read(".python-version")));
    } catch {
      return context.skip();  // No pinned interpreter here; the build cannot run on this machine either.
    }
    const directory = mkdtempSync(path.join(os.tmpdir(), "railwatch-probe-"));
    const links: string[] = [];
    try {
      const through = (name: string) => {
        const link = path.join(directory, name);
        symlinkSync(path.dirname(base.executable), link, "junction");
        links.push(link);
        return path.join(link, path.basename(base.executable));
      };
      // An interpreter that cannot start through a junction at all says nothing about encodings.
      if (!probeInterpreter(through("interpreter dir"))) return context.skip();
      const python = through("解释器 目录");
      for (const encoding of [undefined, "gbk", "cp1252"]) {
        vi.stubEnv("PYTHONIOENCODING", encoding);
        expect(probeInterpreter(python), `PYTHONIOENCODING=${encoding}`)
          .toEqual({ version: base.version, fullVersion: base.fullVersion, executable: python });
        expect(findInterpreter(base.version, { env: { RAILWATCH_BUILD_PYTHON: python } }).executable).toBe(python);
      }
    } finally {
      // The junctions point at a real interpreter: unlink each one, and delete nothing recursively.
      for (const link of links) rmdirSync(link);
      rmdirSync(directory);
    }
  }, 60_000);
});

describe("build-runtime environment", () => {
  const interpreter = { version: "3.14", fullVersion: "3.14.10", executable: "C:\\Python314\\python.exe" };

  test("the stamp changes with the lock, the interpreter version and its location", () => {
    const stamp = environmentStamp("selenium==4.44.0\n", interpreter);
    expect(environmentStamp("selenium==4.44.0\n", interpreter)).toBe(stamp);
    expect(environmentStamp("selenium==4.45.0\n", interpreter)).not.toBe(stamp);
    expect(environmentStamp("selenium==4.44.0\n", { ...interpreter, fullVersion: "3.14.11" })).not.toBe(stamp);
    expect(environmentStamp("selenium==4.44.0\n", { ...interpreter, executable: "D:\\py\\python.exe" })).not.toBe(stamp);
  });

  test("finds the environment's python on each platform", () => {
    expect(venvPythonPath("venv", "win32")).toBe(path.join("venv", "Scripts", "python.exe"));
    expect(venvPythonPath("venv", "darwin")).toBe(path.join("venv", "bin", "python"));
  });

  test("npm run build:runtime goes through the script, never a PATH pyinstaller", () => {
    const scripts = (JSON.parse(read("package.json")) as { scripts: Record<string, string> }).scripts;
    expect(scripts["build:runtime"]).toBe("node scripts/build-runtime.mjs");
    expect(scripts.package).toContain("npm run build:runtime");
    expect(scripts["package:mac"]).toContain("npm run build:runtime");
    expect(Object.values(scripts).join("\n")).not.toMatch(/(^|[^\w.-])pyinstaller /);
  });
});

type Step = { name?: string; run?: string; uses?: string; if?: string; with?: Record<string, unknown> };
type Workflow = { jobs: Record<string, { "runs-on": string; "timeout-minutes"?: number; strategy?: { matrix: Record<string, unknown> }; steps: Step[] }> };
const workflowSteps = (file: string) =>
  Object.values((yaml.load(read(`.github/workflows/${file}`)) as Workflow).jobs).flatMap((job) => job.steps);

describe("toolchain versions have one source", () => {
  test.each(["ci.yml", "package-release.yml"])("%s takes Python and Node from .python-version and .nvmrc", (file) => {
    const steps = workflowSteps(file);
    const python = steps.filter((step) => step.uses?.startsWith("actions/setup-python"));
    const node = steps.filter((step) => step.uses?.startsWith("actions/setup-node"));
    expect(python.length).toBeGreaterThan(0);
    expect(node.length).toBeGreaterThan(0);
    for (const step of python) {
      expect(step.with).toMatchObject({ "python-version-file": ".python-version", "cache-dependency-path": "requirements.lock" });
      expect(step.with).not.toHaveProperty("python-version");
    }
    for (const step of node) {
      expect(step.with).toMatchObject({ "node-version-file": ".nvmrc" });
      expect(step.with).not.toHaveProperty("node-version");
    }
  });

  test.each(["ci.yml", "package-release.yml"])("%s installs Python packages only from the hashed lock", (file) => {
    const installs = workflowSteps(file).flatMap((step) => (step.run ?? "").split("\n"))
      .map((line) => line.trim()).filter((line) => line.includes("pip install"));
    expect(installs.length).toBeGreaterThan(0);
    for (const line of installs) expect(line).toBe("python -m pip install --require-hashes -r requirements.lock");
  });

  test("CI covers both installer platforms and freezes the runtime on each", () => {
    const { test: job } = (yaml.load(read(".github/workflows/ci.yml")) as Workflow).jobs;
    expect(job.strategy?.matrix).toEqual({ os: ["windows-latest", "macos-15"] });
    expect(job["runs-on"]).toBe("${{ matrix.os }}");
    expect(job["timeout-minutes"]).toBeGreaterThan(0);
    expect(job.steps.map((step) => step.run ?? "")).toContain("npm run build:runtime");
  });

  test("CI smokes the frozen runtime and the packaged app on Windows, each again under a non-ASCII profile", () => {
    const { test: job } = (yaml.load(read(".github/workflows/ci.yml")) as Workflow).jobs;
    const steps = job.steps.filter((step) => /_smoke\.py|package:unpacked/.test(step.run ?? ""));
    expect(steps.map((step) => step.run)).toEqual([
      "python -X utf8 tests/runtime_order_smoke.py",
      "python -X utf8 tests/runtime_order_smoke.py --non-ascii-profile",
      "npm run package:unpacked",
      "python -X utf8 tests/packaged_smoke.py",
      "python -X utf8 tests/packaged_smoke.py --non-ascii-profile",
    ]);
    // The macOS smokes need the temporary keychain the release workflow sets up.
    for (const step of steps) expect(step.if).toBe("${{ runner.os == 'Windows' }}");
    const scripts = (JSON.parse(read("package.json")) as { scripts: Record<string, string> }).scripts;
    expect(scripts["package:unpacked"]).toBe("electron-builder --dir --publish never");
    const evidence = job.steps.find((step) => step.with?.name === "qa-windows-smoke");
    expect(evidence?.if).toBe("${{ always() && runner.os == 'Windows' }}");
  });

  test("Node typings match the Node major in .nvmrc", () => {
    const major = read(".nvmrc").trim();
    expect(major).toMatch(/^\d+$/);
    const manifest = JSON.parse(read("package.json")) as { devDependencies: Record<string, string> };
    expect(manifest.devDependencies["@types/node"]).toMatch(new RegExp(`^\\^${major}\\.`));
  });
});
