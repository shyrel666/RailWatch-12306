import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import { describe, expect, test } from "vitest";

type Step = { name?: string; run?: string; uses?: string; with?: Record<string, unknown>; env?: Record<string, string>; if?: string };
type Job = { if?: string; needs?: string[]; "runs-on": string; steps: Step[]; strategy?: { "fail-fast": boolean; matrix: { include: Record<string, string>[] } }; env?: Record<string, string> };
type Workflow = {
  on: { push: { tags: string[] }; workflow_dispatch: { inputs: { platforms: { options: string[]; default: string } } } };
  permissions: Record<string, string>;
  concurrency: { group: string; "cancel-in-progress": boolean };
  jobs: Record<"windows" | "macos" | "publish", Job>;
};

const workflow = yaml.load(readFileSync(new URL("../../.github/workflows/package-release.yml", import.meta.url), "utf8")) as Workflow;
const { windows, macos, publish } = workflow.jobs;
const runs = (job: Job) => job.steps.map((step) => step.run ?? "").join("\n");
const stepIndex = (job: Job, name: string) => job.steps.findIndex((step) => step.name === name);
const normalize = (value: string | undefined) => (value ?? "").replace(/\s+/g, " ").trim();

describe("package-release workflow", () => {
  test("runs from version tags or a manual platform choice, one run per tag", () => {
    expect(workflow.on.push.tags).toEqual(["v*"]);
    expect(workflow.on.workflow_dispatch.inputs.platforms.options).toEqual(["all", "windows", "macos"]);
    expect(workflow.on.workflow_dispatch.inputs.platforms.default).toBe("all");
    expect(workflow.permissions.contents).toBe("write");
    expect(workflow.concurrency).toEqual({ group: "package-release-${{ github.ref }}", "cancel-in-progress": false });
    for (const job of [windows, macos, publish]) expect(runs(job)).toContain("node scripts/check-release-tag.mjs");
  });

  test("builds Windows and both macOS architectures on pinned native runners", () => {
    expect(windows["runs-on"]).toBe("windows-latest");
    expect(normalize(windows.if)).toBe("${{ github.event_name == 'push' || inputs.platforms != 'macos' }}");
    expect(normalize(macos.if)).toBe("${{ github.event_name == 'push' || inputs.platforms != 'windows' }}");
    expect(macos.strategy?.["fail-fast"]).toBe(false);
    expect(macos.strategy?.matrix.include).toEqual([
      { arch: "arm64", runner: "macos-15" },
      { arch: "x64", runner: "macos-15-intel" },
    ]);
    expect(macos["runs-on"]).toBe("${{ matrix.runner }}");
    expect(macos.env?.SIGN_MODE).toBe("adhoc");
    expect(runs(macos)).toContain("-c.mac.identity=-");
    expect(runs(macos)).toContain("-c.extraMetadata.railwatchMacUpdateMode=manual");
  });

  test("only the publish job touches the GitHub Release", () => {
    expect(runs(windows)).not.toContain("gh release");
    expect(runs(macos)).not.toContain("gh release");
    expect(runs(publish)).toContain("gh release create");
    expect(runs(publish)).toContain("gh release upload");
    expect(publish.needs).toEqual(["windows", "macos"]);
    expect(normalize(publish.if)).toBe(normalize(`\${{
      !cancelled() &&
      (needs.windows.result == 'success' ||
        (github.event_name == 'workflow_dispatch' && inputs.platforms == 'macos' && needs.windows.result == 'skipped')) &&
      (needs.macos.result == 'success' ||
        (github.event_name == 'workflow_dispatch' && inputs.platforms == 'windows' && needs.macos.result == 'skipped'))
    }}`));
  });

  test("verifies the exact .app and smokes it with a probed keychain before uploading", () => {
    const script = runs(macos);
    expect(script).toContain('arm64) APP_PATH="$PWD/release/mac-arm64/RailWatch 12306.app"');
    expect(script).toContain('x64) APP_PATH="$PWD/release/mac/RailWatch 12306.app"');
    expect(script).toContain('codesign --verify --deep --strict --verbose=2 "$APP_PATH"');
    const verify = stepIndex(macos, "Verify app signature");
    const smoke = stepIndex(macos, "Smoke the final app with a temporary keychain");
    const reverify = stepIndex(macos, "Re-verify the app and update metadata after smoke tests");
    const upload = stepIndex(macos, "Upload release assets");
    expect(verify).toBeGreaterThan(-1);
    expect(verify).toBeLessThan(smoke);
    expect(smoke).toBeLessThan(reverify);
    expect(reverify).toBeLessThan(upload);
    const smokeScript = macos.steps[smoke].run ?? "";
    const probe = smokeScript.indexOf("scripts/keychain_probe.py");
    expect(probe).toBeGreaterThan(smokeScript.indexOf("security default-keychain -d user -s"));
    expect(probe).toBeLessThan(smokeScript.indexOf('tests/runtime_order_smoke.py --exe "$RUNTIME_PATH"'));
    expect(smokeScript).toContain('tests/packaged_smoke.py --exe "$APP_PATH/Contents/MacOS/RailWatch 12306"');
    expect(smokeScript).toContain("trap restore_keychains EXIT");
    expect(stepIndex(windows, "Verify packaged runtime starts and restores orders")).toBeLessThan(stepIndex(windows, "Upload release assets"));
  });

  test("uploads only release assets under release-* names and keeps QA output apart", () => {
    const uploads = [...windows.steps, ...macos.steps].filter((step) => step.uses?.startsWith("actions/upload-artifact"));
    const names = uploads.map((step) => step.with?.name);
    expect(names).toEqual(["release-windows", "qa-windows-unpacked", "release-macos-${{ matrix.arch }}", "qa-macos-${{ matrix.arch }}"]);
    expect(String(uploads[0].with?.path)).not.toContain("win-unpacked");
    expect(String(uploads[2].with?.path)).toContain("latest-mac-${{ matrix.arch }}.yml");
    const download = publish.steps.find((step) => step.uses?.startsWith("actions/download-artifact"));
    expect(download?.with).toMatchObject({ pattern: "release-*", "merge-multiple": true });
    expect(runs(publish)).toContain("node scripts/merge-latest-mac.mjs release/latest-mac-arm64.yml release/latest-mac-x64.yml");
    const merge = publish.steps.find((step) => step.name === "Merge macOS update metadata");
    expect(merge?.if).toBe("${{ needs.macos.result == 'success' }}");
  });

  test("an existing release keeps its latest marker and new releases compare versions", () => {
    const script = runs(publish);
    expect(script).toContain("--clobber");
    expect(script).toContain("releases/latest");
    expect(script).toContain("--prerelease --latest=false");
    expect(script).toContain("docs/releases/$tag.md");
  });
});
