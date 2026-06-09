import { readFile } from "node:fs/promises";
import { describe, expect, test } from "vitest";

describe("package-windows workflow", () => {
  test("publishes updater metadata and installer assets to a GitHub Release", async () => {
    const workflow = await readFile(
      new URL("../../.github/workflows/package-windows.yml", import.meta.url),
      "utf8",
    );

    expect(workflow).toContain("contents: write");
    expect(workflow).toContain("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}");
    expect(workflow).toContain("release/latest.yml");
    expect(workflow).toContain("gh release view");
    expect(workflow).toContain("gh release upload");
    expect(workflow).toContain("gh release create");
  });
});
