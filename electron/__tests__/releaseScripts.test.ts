import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import yaml from "js-yaml";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { verifyUpdateMetadata } from "../../scripts/verify-update-metadata.mjs";

const root = path.resolve(__dirname, "../..");

describe("verifyUpdateMetadata", () => {
  let directory: string;
  beforeEach(() => { directory = mkdtempSync(path.join(tmpdir(), "railwatch-metadata-")); });
  afterEach(() => rmSync(directory, { recursive: true, force: true }));

  function asset(name: string, content: string) {
    writeFileSync(path.join(directory, name), content);
    return { url: name, sha512: createHash("sha512").update(content).digest("base64"), size: Buffer.byteLength(content) };
  }

  function manifest(files: object[], extra: object = {}) {
    const file = path.join(directory, "latest-mac.yml");
    writeFileSync(file, yaml.dump({ version: "0.6.0", files, ...extra }));
    return file;
  }

  test("accepts matching files and lists them", () => {
    const zip = asset("RailWatch-12306-0.6.0-arm64.zip", "zip");
    const dmg = asset("RailWatch-12306-0.6.0-arm64.dmg", "dmg");
    const file = manifest([zip, dmg], { path: zip.url, sha512: zip.sha512 });
    expect(verifyUpdateMetadata(file, { version: "0.6.0", arch: "arm64" })).toEqual([zip.url, dmg.url]);
  });

  test("rejects version, size, hash, missing file and architecture mismatches", () => {
    const zip = asset("RailWatch-12306-0.6.0-x64.zip", "zip");
    expect(() => verifyUpdateMetadata(manifest([zip]), { version: "0.6.1" })).toThrow("version 0.6.0 is not 0.6.1");
    expect(() => verifyUpdateMetadata(manifest([{ ...zip, size: 1 }]), { version: "0.6.0" })).toThrow("metadata says 1");
    expect(() => verifyUpdateMetadata(manifest([{ ...zip, sha512: "x" }]), { version: "0.6.0" })).toThrow("SHA-512");
    expect(() => verifyUpdateMetadata(manifest([{ ...zip, url: "gone.zip" }]), { version: "0.6.0" })).toThrow("missing gone.zip");
    expect(() => verifyUpdateMetadata(manifest([zip]), { version: "0.6.0", arch: "arm64" })).toThrow("not an arm64 file");
  });
});

describe("check-release-tag", () => {
  const run = (ref: string) => execFileSync(process.execPath, [path.join(root, "scripts/check-release-tag.mjs")], {
    cwd: root, encoding: "utf8", env: { ...process.env, GITHUB_REF: ref, GITHUB_ENV: "" }, stdio: "pipe",
  });
  const version = (JSON.parse(execFileSync(process.execPath, ["-p", "JSON.stringify(require('./package.json'))"], { cwd: root, encoding: "utf8" })) as { version: string }).version;

  test("accepts the tag of the current version", () => {
    expect(run(`refs/tags/v${version}`)).toContain(`v${version}`);
  });

  test("refuses branches and other versions", () => {
    expect(() => run("refs/heads/main")).toThrow();
    expect(() => run("refs/tags/v0.0.1")).toThrow();
  });
});
