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
    // The pinned interpreter is checked before the version bump or any cleanup.
    expect(script.indexOf("node scripts/build-runtime.mjs --check || goto missing_python")).toBeGreaterThan(-1);
    expect(script.indexOf("node scripts/build-runtime.mjs --check")).toBeLessThan(script.indexOf("npm version"));
    expect(script).toContain("if exist \"build\\python-venv\" rmdir /s /q \"build\\python-venv\"");
    // Python packages only ever go into the build environment made by build-runtime.mjs.
    expect(script).not.toContain("pip install");
    expect(script).toContain("if exist \"release\" rmdir /s /q \"release\"");
    expect(script).toContain("npm ci");
    expect(script).toContain("npm run package");
    expect(script).toContain("Validating updater metadata assets");
    expect(script).toContain("release/latest.yml references missing asset");
    expect(script).toContain("release\\latest.yml");
    expect(script).toContain("release\\*.exe");
  });
});

describe("local macOS packaging script", () => {
  test("builds the same ad-hoc package as CI for this Mac's architecture", async () => {
    const script = await readFile(new URL("../../package-macos.sh", import.meta.url), "utf8");

    expect(script.startsWith("#!/usr/bin/env bash")).toBe(true);
    expect(script).toContain("set -euo pipefail");
    expect(script).toContain("for tool in node npm; do");
    expect(script.indexOf("node scripts/build-runtime.mjs --check")).toBeGreaterThan(-1);
    expect(script.indexOf("node scripts/build-runtime.mjs --check")).toBeLessThan(script.indexOf("npm version"));
    expect(script).toContain('PACKAGE_VERSION="${1:-}"');
    expect(script).toContain('INSTALL_DEPS="${2:-}"');
    expect(script).toContain('npm version "$PACKAGE_VERSION" --no-git-tag-version --allow-same-version');
    expect(script).toContain('if [ "$INSTALL_DEPS" = "--install-deps" ]');
    expect(script).toContain("node_modules/.package-lock.json");
    expect(script).toContain("rm -rf build/python-venv");
    expect(script).not.toContain("pip install");
    expect(script).toContain("rm -rf release");
    expect(script).toContain("arm64) ARCH=arm64 ;;");
    expect(script).toContain("x86_64) ARCH=x64 ;;");
    expect(script).toContain('npm run package:mac -- "--$ARCH"');
    expect(script).toContain("-c.mac.identity=-");
    expect(script).toContain("-c.mac.notarize=false");
    expect(script).toContain("-c.extraMetadata.railwatchMacUpdateMode=manual");
    expect(script).toContain("CSC_IDENTITY_AUTO_DISCOVERY=false");
    expect(script).toContain('node scripts/verify-update-metadata.mjs --version "$PACKAGE_VERSION" --arch "$ARCH" release/latest-mac.yml');
  });
});
