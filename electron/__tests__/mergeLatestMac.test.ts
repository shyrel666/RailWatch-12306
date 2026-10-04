import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import yaml from "js-yaml";
import { describe, expect, test } from "vitest";
import { mergeLatestMac } from "../../scripts/merge-latest-mac.mjs";

const script = path.resolve(__dirname, "../../scripts/merge-latest-mac.mjs");

function manifest(arch: "arm64" | "x64", releaseDate: string, version = "0.6.0") {
  const name = `RailWatch-12306-${version}-${arch}`;
  return {
    version,
    files: [
      { url: `${name}.zip`, sha512: `${arch}-zip`, size: 100 },
      { url: `${name}.dmg`, sha512: `${arch}-dmg`, size: 200 },
    ],
    path: `${name}.zip`,
    sha512: `${arch}-zip`,
    releaseDate,
  };
}

describe("mergeLatestMac", () => {
  test("keeps both architectures and uses x64 for the legacy top-level entry", () => {
    const merged = mergeLatestMac(manifest("arm64", "2026-10-04T10:00:00.000Z"), manifest("x64", "2026-10-04T09:00:00.000Z"));
    expect(merged.files.map((file: { url: string }) => file.url)).toEqual([
      "RailWatch-12306-0.6.0-arm64.zip", "RailWatch-12306-0.6.0-arm64.dmg",
      "RailWatch-12306-0.6.0-x64.zip", "RailWatch-12306-0.6.0-x64.dmg",
    ]);
    expect(merged.path).toBe("RailWatch-12306-0.6.0-x64.zip");
    expect(merged.sha512).toBe("x64-zip");
    expect(merged.releaseDate).toBe("2026-10-04T10:00:00.000Z");
    expect(merged.version).toBe("0.6.0");
  });

  test("rejects mismatched versions and swapped architectures", () => {
    expect(() => mergeLatestMac(manifest("arm64", "a"), manifest("x64", "b", "0.6.1"))).toThrow("Version mismatch");
    expect(() => mergeLatestMac(manifest("x64", "a"), manifest("arm64", "b"))).toThrow("non-arm64");
    expect(() => mergeLatestMac(manifest("arm64", "a"), { version: "0.6.0", files: [] })).toThrow("malformed");
  });

  test("removes duplicate file entries", () => {
    const arm64 = manifest("arm64", "a");
    arm64.files.push({ ...arm64.files[0] });
    expect(mergeLatestMac(arm64, manifest("x64", "b")).files).toHaveLength(4);
  });

  test("the command line writes YAML that keeps the release date a string", () => {
    const directory = mkdtempSync(path.join(tmpdir(), "railwatch-merge-"));
    try {
      const arm64 = path.join(directory, "latest-mac-arm64.yml");
      const x64 = path.join(directory, "latest-mac-x64.yml");
      writeFileSync(arm64, yaml.dump(manifest("arm64", "2026-10-04T10:00:00.000Z")));
      writeFileSync(x64, yaml.dump(manifest("x64", "2026-10-04T09:00:00.000Z")));
      const output = execFileSync(process.execPath, [script, arm64, x64], { encoding: "utf8" });
      const parsed = yaml.load(output) as { files: unknown[]; releaseDate: unknown };
      expect(parsed.files).toHaveLength(4);
      expect(parsed.releaseDate).toBe("2026-10-04T10:00:00.000Z");
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
});
