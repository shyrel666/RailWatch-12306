import { readFile } from "node:fs/promises";
import { describe, expect, test } from "vitest";

describe("update publishing config", () => {
  test("points packaged auto-updates at the public GitHub Release repository", async () => {
    const config = await readFile(new URL("../../electron-builder.yml", import.meta.url), "utf8");

    expect(config).toContain("provider: github");
    expect(config).toContain("owner: shyrel666");
    expect(config).toContain("repo: RailWatch-12306");
    expect(config).toContain('artifactName: "RailWatch-12306-${version}-${arch}.${ext}"');
    expect(config).not.toContain("owner: railwatch");
    expect(config).not.toContain("repo: railwatch-12306");
    expect(config).not.toContain('artifactName: "${productName}-${version}-${arch}.${ext}"');
  });
});
