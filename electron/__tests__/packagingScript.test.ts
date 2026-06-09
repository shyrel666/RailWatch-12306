import { readFile } from "node:fs/promises";
import { describe, expect, test } from "vitest";

describe("local Windows packaging script", () => {
  test("wraps the existing package pipeline with dependency checks", async () => {
    const script = await readFile(new URL("../../package-windows.cmd", import.meta.url), "utf8");

    expect(script).toContain("set \"PACKAGE_VERSION=%~1\"");
    expect(script).toContain("set \"INSTALL_DEPS=%~2\"");
    expect(script).toContain("set /p PACKAGE_VERSION=");
    expect(script).toContain("npm version \"%PACKAGE_VERSION%\" --no-git-tag-version");
    expect(script).toContain("if /i \"%INSTALL_DEPS%\"==\"--install-deps\"");
    expect(script).toContain("if exist \"node_modules\\.package-lock.json\"");
    expect(script).toContain("Skipping Node dependencies");
    expect(script).toContain("python -c \"import PyInstaller\"");
    expect(script).toContain("Skipping Python packaging dependencies");
    expect(script).toContain("if exist \"release\" rmdir /s /q \"release\"");
    expect(script).toContain("npm ci");
    expect(script).toContain("python -m pip install -r requirements.txt pyinstaller");
    expect(script).toContain("npm run package");
    expect(script).toContain("Validating updater metadata assets");
    expect(script).toContain("release/latest.yml references missing asset");
    expect(script).toContain("release\\latest.yml");
    expect(script).toContain("release\\*.exe");
  });
});
