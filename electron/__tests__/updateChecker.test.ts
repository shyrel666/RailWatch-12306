import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import {
  buildFallbackAssets,
  checkForUpdates,
  compareVersions,
  createDefaultUpdateConfig,
  downloadUpdateAsset,
  fetchLatestVersionViaRedirect,
  isAllowedDownloadUrl,
  parseGitHubRelease,
  parseReleaseManifest,
  resetLastSuccessfulCheck,
  selectAssetForPlatform,
  type UpdateAsset,
} from "../updateChecker";

const sampleRelease = {
  tag_name: "v1.2.0",
  name: "RailWatch 1.2.0",
  body: "Bug fixes and improvements.",
  published_at: "2026-06-01T00:00:00Z",
  html_url: "https://github.com/railwatch/railwatch-12306/releases/tag/v1.2.0",
  prerelease: false,
  assets: [
    {
      name: "RailWatch 12306-1.2.0-x64.exe",
      browser_download_url: "https://github.com/railwatch/railwatch-12306/releases/download/v1.2.0/app.exe",
      size: 1024,
    },
    {
      name: "RailWatch 12306-1.2.0-x64.AppImage",
      browser_download_url: "https://github.com/railwatch/railwatch-12306/releases/download/v1.2.0/app.AppImage",
      size: 2048,
    },
  ],
};

describe("updateChecker", () => {
  let tempDir = "";

  beforeEach(async () => {
    resetLastSuccessfulCheck();
    tempDir = await mkdtemp(path.join(os.tmpdir(), "railwatch-update-"));
  });

  afterEach(async () => {
    if (tempDir) {
      await rm(tempDir, { recursive: true, force: true });
    }
  });

  test("compares semantic versions with prerelease ordering", () => {
    expect(compareVersions("0.1.0", "1.0.0")).toBe(-1);
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0);
    expect(compareVersions("1.2.0", "1.1.9")).toBe(1);
    expect(compareVersions("1.0.0-beta", "1.0.0")).toBe(-1);
    expect(compareVersions("v1.0.0", "1.0.0")).toBe(0);
  });

  test("uses the public GitHub Release repository in default config", () => {
    const config = createDefaultUpdateConfig("0.1.0", tempDir);

    expect(config.owner).toBe("shyrel666");
    expect(config.repo).toBe("RailWatch-12306");
    expect(config.manifestUrl).toContain("shyrel666/RailWatch-12306");
  });

  test("parses GitHub release payloads and filters unsafe download URLs", () => {
    const parsed = parseGitHubRelease(sampleRelease);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) {
      return;
    }
    expect(parsed.latestVersion).toBe("1.2.0");
    expect(parsed.assets).toHaveLength(2);
    expect(isAllowedDownloadUrl("https://evil.example/installer.exe")).toBe(false);
    expect(isAllowedDownloadUrl("https://github.com/railwatch/railwatch-12306/releases/download/v1.2.0/app.exe")).toBe(true);
  });

  test("rejects prerelease payloads unless explicitly enabled", () => {
    const parsed = parseGitHubRelease({ ...sampleRelease, prerelease: true });
    expect(parsed.ok).toBe(false);
    if (parsed.ok) {
      return;
    }
    expect(parsed.code).toBe("parse");
  });

  test("selects platform-specific installer assets", () => {
    const assets: UpdateAsset[] = [
      { name: "RailWatch 12306-1.2.0-x64.exe", url: "https://github.com/a/b/releases/download/v1.2.0/app.exe", size: 1 },
      { name: "RailWatch 12306-1.2.0-x64.AppImage", url: "https://github.com/a/b/releases/download/v1.2.0/app.AppImage", size: 2 },
    ];

    expect(selectAssetForPlatform(assets, "win32")?.name).toContain(".exe");
    expect(selectAssetForPlatform(assets, "linux")?.name).toContain(".AppImage");
    expect(selectAssetForPlatform(assets, "darwin")).toBeNull();
  });

  test("checks for updates and writes cache when remote version is newer", async () => {
    const cachePath = path.join(tempDir, "update-cache.json");
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sampleRelease,
    })) as unknown as typeof fetch;

    const result = await checkForUpdates(
      {
        owner: "railwatch",
        repo: "railwatch-12306",
        currentVersion: "0.1.0",
        cachePath,
        fetchImpl,
      },
      { force: true },
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      return;
    }
    expect(result.hasUpdate).toBe(true);
    expect(result.latestVersion).toBe("1.2.0");
    expect(fetchImpl).toHaveBeenCalledOnce();

    const cachedRaw = await readFile(cachePath, "utf8");
    expect(cachedRaw).toContain("1.2.0");
  });

  test("returns cached result without refetching within TTL", async () => {
    const cachePath = path.join(tempDir, "update-cache.json");
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sampleRelease,
    })) as unknown as typeof fetch;

    await checkForUpdates(
      {
        owner: "railwatch",
        repo: "railwatch-12306",
        currentVersion: "0.1.0",
        cachePath,
        fetchImpl,
      },
      { force: true },
    );

    const cached = await checkForUpdates(
      {
        owner: "railwatch",
        repo: "railwatch-12306",
        currentVersion: "0.1.0",
        cachePath,
        fetchImpl,
      },
      { force: false },
    );

    expect(cached.ok).toBe(true);
    if (!cached.ok) {
      return;
    }
    expect(cached.cached).toBe(true);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  test("parses release manifest payloads", () => {
    const parsed = parseReleaseManifest({
      version: "1.3.0",
      name: "RailWatch 1.3.0",
      notes: "Manifest release",
      releaseUrl: "https://github.com/railwatch/railwatch-12306/releases/tag/v1.3.0",
      assets: [
        {
          name: "RailWatch 12306-1.3.0-x64.exe",
          url: "https://github.com/railwatch/railwatch-12306/releases/download/v1.3.0/app.exe",
          size: 10,
        },
      ],
    });

    expect(parsed.ok).toBe(true);
    if (!parsed.ok) {
      return;
    }
    expect(parsed.latestVersion).toBe("1.3.0");
    expect(parsed.assets).toHaveLength(1);
  });

  test("builds fallback assets from release tag naming", () => {
    const assets = buildFallbackAssets("railwatch", "railwatch-12306", "1.2.0");
    expect(assets.some((asset) => asset.name.endsWith(".exe"))).toBe(true);
    expect(assets[0]?.url).toContain("/releases/download/v1.2.0/");
  });

  test("reads latest version from GitHub releases redirect", async () => {
    const fetchImpl = vi.fn(async () => ({
      status: 302,
      url: "",
      headers: {
        get: (key: string) => (key === "location" ? "/railwatch/railwatch-12306/releases/tag/v1.2.0" : null),
      },
    })) as unknown as typeof fetch;

    const latest = await fetchLatestVersionViaRedirect("railwatch", "railwatch-12306", fetchImpl);
    expect(latest).toEqual({
      version: "1.2.0",
      releaseUrl: "https://github.com/railwatch/railwatch-12306/releases/tag/v1.2.0",
    });
  });

  test("falls back to releases redirect when GitHub API is rate limited", async () => {
    const cachePath = path.join(tempDir, "update-cache.json");
    const fetchImpl = vi.fn(async (url: string | URL) => {
      const target = String(url);
      if (target.includes("api.github.com")) {
        return {
          ok: false,
          status: 403,
          headers: { get: (key: string) => (key === "x-ratelimit-remaining" ? "0" : null) },
          json: async () => ({}),
        };
      }
      if (target.includes("/releases/latest")) {
        return {
          ok: false,
          status: 302,
          url: "",
          headers: {
            get: (key: string) => (key === "location" ? "/railwatch/railwatch-12306/releases/tag/v1.2.0" : null),
          },
        };
      }
      return {
        ok: false,
        status: 404,
        headers: { get: () => null },
        json: async () => ({}),
      };
    }) as unknown as typeof fetch;

    const result = await checkForUpdates(
      {
        owner: "railwatch",
        repo: "railwatch-12306",
        currentVersion: "0.1.0",
        cachePath,
        fetchImpl,
      },
      { force: true },
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      return;
    }
    expect(result.latestVersion).toBe("1.2.0");
    expect(result.source).toBe("redirect");
    expect(result.hasUpdate).toBe(true);
  });

  test("downloads update assets and verifies sha256 when provided", async () => {
    const payload = Buffer.from("installer-bytes");
    const sha256 = "2c26b46b68ffc68ff99b453c1d30413408e30a8c8c2a8b8b8b8b8b8b8b8b8b8b";
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(payload);
          controller.close();
        },
      }),
    })) as unknown as typeof fetch;

    const asset: UpdateAsset = {
      name: "RailWatch 12306-1.2.0-x64.exe",
      url: "https://github.com/railwatch/railwatch-12306/releases/download/v1.2.0/app.exe",
      size: payload.length,
      sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    };

    const result = await downloadUpdateAsset(asset, tempDir, fetchImpl);
    expect(result.ok).toBe(false);
    if (result.ok) {
      return;
    }
    expect(result.code).toBe("hash-mismatch");

    const validAsset = { ...asset, sha256: "204676736cea68d6411da9d3aa3fab0a5e70b023ba30cd560cfa9c8e7250f4df" };
    const validResult = await downloadUpdateAsset(validAsset, tempDir, fetchImpl);
    expect(validResult.ok).toBe(true);
    if (!validResult.ok) {
      return;
    }
    expect(validResult.fileName).toBe(asset.name);
  });
});
