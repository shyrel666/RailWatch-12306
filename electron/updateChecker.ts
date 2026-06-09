import { createHash } from "node:crypto";
import { createWriteStream, promises as fs } from "node:fs";
import path from "node:path";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";

export type UpdateAsset = {
  name: string;
  url: string;
  size: number;
  sha256?: string;
};

export type UpdateCheckSuccess = {
  ok: true;
  currentVersion: string;
  latestVersion: string;
  hasUpdate: boolean;
  releaseName: string;
  releaseNotes: string;
  publishedAt: string;
  releaseUrl: string;
  assets: UpdateAsset[];
  cached?: boolean;
  stale?: boolean;
  warning?: string;
  source?: "api" | "manifest" | "redirect" | "cache" | "stale-cache" | "updater";
};

export type UpdateCheckFailure = {
  ok: false;
  currentVersion: string;
  error: string;
  code: "network" | "parse" | "no-assets" | "rate-limit" | "unknown";
};

export type UpdateCheckResult = UpdateCheckSuccess | UpdateCheckFailure;

export type UpdateDownloadResult =
  | { ok: true; filePath: string; fileName: string }
  | { ok: false; error: string; code: "network" | "hash-mismatch" | "no-asset" | "unknown" };

export type UpdateCheckerConfig = {
  owner: string;
  repo: string;
  currentVersion: string;
  cachePath: string;
  cacheTtlMs?: number;
  includePrerelease?: boolean;
  githubToken?: string;
  manifestUrl?: string;
  productName?: string;
  fetchImpl?: typeof fetch;
};

type ReleaseManifest = {
  version?: string;
  tag?: string;
  name?: string;
  notes?: string;
  releaseNotes?: string;
  publishedAt?: string;
  releaseUrl?: string;
  assets?: UpdateAsset[];
};

type VersionParts = {
  major: number;
  minor: number;
  patch: number;
  prerelease: string;
};

type GitHubReleaseAsset = {
  name?: string;
  browser_download_url?: string;
  size?: number;
};

type GitHubRelease = {
  tag_name?: string;
  name?: string;
  body?: string;
  published_at?: string;
  html_url?: string;
  prerelease?: boolean;
  assets?: GitHubReleaseAsset[];
};

const DEFAULT_CACHE_TTL_MS = 6 * 60 * 60 * 1000;
const DEFAULT_PRODUCT_NAME = "RailWatch 12306";
const ALLOWED_DOWNLOAD_HOSTS = new Set(["github.com", "objects.githubusercontent.com", "api.github.com"]);

const PLATFORM_EXTENSIONS: Record<NodeJS.Platform, string[]> = {
  win32: [".exe", ".msi"],
  darwin: [".dmg", ".zip"],
  linux: [".appimage", ".deb"],
  aix: [],
  android: [],
  freebsd: [],
  haiku: [],
  openbsd: [],
  sunos: [],
  cygwin: [],
  netbsd: [],
};

let lastSuccessfulCheck: UpdateCheckSuccess | null = null;

export function normalizeVersion(version: string): string {
  return version.replace(/^v/i, "").trim();
}

export function parseVersionParts(version: string): VersionParts {
  const normalized = normalizeVersion(version);
  const [core, prerelease = ""] = normalized.split("-");
  const [major = "0", minor = "0", patch = "0"] = core.split(".");
  return {
    major: Number.parseInt(major, 10) || 0,
    minor: Number.parseInt(minor, 10) || 0,
    patch: Number.parseInt(patch, 10) || 0,
    prerelease,
  };
}

export function compareVersions(left: string, right: string): -1 | 0 | 1 {
  const a = parseVersionParts(left);
  const b = parseVersionParts(right);

  if (a.major !== b.major) {
    return a.major < b.major ? -1 : 1;
  }
  if (a.minor !== b.minor) {
    return a.minor < b.minor ? -1 : 1;
  }
  if (a.patch !== b.patch) {
    return a.patch < b.patch ? -1 : 1;
  }
  if (a.prerelease && !b.prerelease) {
    return -1;
  }
  if (!a.prerelease && b.prerelease) {
    return 1;
  }
  if (a.prerelease !== b.prerelease) {
    return a.prerelease < b.prerelease ? -1 : 1;
  }
  return 0;
}

export function isAllowedDownloadUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") {
      return false;
    }
    return ALLOWED_DOWNLOAD_HOSTS.has(parsed.hostname);
  } catch {
    return false;
  }
}

export function parseGitHubRelease(data: unknown, includePrerelease = false): UpdateCheckSuccess | UpdateCheckFailure {
  if (!data || typeof data !== "object") {
    return { ok: false, currentVersion: "", error: "Invalid release payload.", code: "parse" };
  }

  const release = data as GitHubRelease;
  if (!includePrerelease && release.prerelease) {
    return { ok: false, currentVersion: "", error: "Latest release is a prerelease.", code: "parse" };
  }

  const latestVersion = normalizeVersion(release.tag_name || "");
  if (!latestVersion) {
    return { ok: false, currentVersion: "", error: "Release is missing tag_name.", code: "parse" };
  }

  const assets = (release.assets || [])
    .filter((asset): asset is Required<Pick<GitHubReleaseAsset, "name" | "browser_download_url">> & GitHubReleaseAsset =>
      Boolean(asset?.name && asset?.browser_download_url && isAllowedDownloadUrl(asset.browser_download_url)),
    )
    .map((asset) => ({
      name: asset.name,
      url: asset.browser_download_url,
      size: typeof asset.size === "number" ? asset.size : 0,
    }));

  return {
    ok: true,
    currentVersion: "",
    latestVersion,
    hasUpdate: false,
    releaseName: release.name || latestVersion,
    releaseNotes: release.body || "",
    publishedAt: release.published_at || "",
    releaseUrl: release.html_url || "",
    assets,
  };
}

export function selectAssetForPlatform(assets: UpdateAsset[], platform: NodeJS.Platform = process.platform): UpdateAsset | null {
  const extensions = PLATFORM_EXTENSIONS[platform] || [];
  if (extensions.length === 0) {
    return null;
  }

  for (const extension of extensions) {
    const match = assets.find((asset) => asset.name.toLowerCase().endsWith(extension));
    if (match) {
      return match;
    }
  }
  return null;
}

type CacheEnvelope = {
  checkedAt: number;
  result: UpdateCheckSuccess;
};

async function readCacheEnvelope(cachePath: string): Promise<CacheEnvelope | null> {
  try {
    const raw = await fs.readFile(cachePath, "utf8");
    const parsed = JSON.parse(raw) as CacheEnvelope;
    if (!parsed?.checkedAt || !parsed?.result?.latestVersion) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

async function readCache(cachePath: string, ttlMs: number): Promise<UpdateCheckSuccess | null> {
  const envelope = await readCacheEnvelope(cachePath);
  if (!envelope) {
    return null;
  }
  if (Date.now() - envelope.checkedAt > ttlMs) {
    return null;
  }
  return { ...envelope.result, cached: true, source: "cache" };
}

async function readStaleCache(cachePath: string): Promise<UpdateCheckSuccess | null> {
  const envelope = await readCacheEnvelope(cachePath);
  if (!envelope) {
    return null;
  }
  return {
    ...envelope.result,
    cached: true,
    stale: true,
    source: "stale-cache",
    warning: "无法连接更新源，已显示上次缓存的版本信息。",
  };
}

async function writeCache(cachePath: string, result: UpdateCheckSuccess): Promise<void> {
  const envelope: CacheEnvelope = {
    checkedAt: Date.now(),
    result: { ...result, cached: false },
  };
  await fs.mkdir(path.dirname(cachePath), { recursive: true });
  await fs.writeFile(cachePath, JSON.stringify(envelope, null, 2), "utf8");
}

function buildGithubApiHeaders(githubToken?: string): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "User-Agent": "RailWatch-12306-Updater",
  };
  if (githubToken) {
    headers.Authorization = `Bearer ${githubToken}`;
  }
  return headers;
}

function isGithubRateLimit(response: Response): boolean {
  const remaining = response.headers.get("x-ratelimit-remaining");
  if (remaining === "0") {
    return true;
  }
  return response.status === 403;
}

function finalizeCheckResult(
  config: UpdateCheckerConfig,
  partial: Omit<UpdateCheckSuccess, "currentVersion" | "hasUpdate">,
): UpdateCheckSuccess {
  return {
    ...partial,
    currentVersion: config.currentVersion,
    hasUpdate: compareVersions(config.currentVersion, partial.latestVersion) < 0,
  };
}

export function buildFallbackAssets(
  owner: string,
  repo: string,
  version: string,
  productName = DEFAULT_PRODUCT_NAME,
): UpdateAsset[] {
  const tag = /^v/i.test(version) ? version : `v${version}`;
  const baseUrl = `https://github.com/${owner}/${repo}/releases/download/${tag}`;
  const fileVersion = normalizeVersion(version);
  const templates = [
    `${productName}-${fileVersion}-x64.exe`,
    `${productName}-${fileVersion}-x64.msi`,
    `${productName}-${fileVersion}-x64.dmg`,
    `${productName}-${fileVersion}-x64.zip`,
    `${productName}-${fileVersion}-x64.AppImage`,
    `${productName}-${fileVersion}-x64.deb`,
  ];

  return templates.map((name) => ({
    name,
    url: `${baseUrl}/${encodeURIComponent(name)}`,
    size: 0,
  }));
}

export function parseReleaseManifest(data: unknown): UpdateCheckSuccess | UpdateCheckFailure {
  if (!data || typeof data !== "object") {
    return { ok: false, currentVersion: "", error: "Invalid release manifest.", code: "parse" };
  }

  const manifest = data as ReleaseManifest;
  const latestVersion = normalizeVersion(manifest.version || manifest.tag || "");
  if (!latestVersion) {
    return { ok: false, currentVersion: "", error: "Manifest is missing version.", code: "parse" };
  }

  const assets = (manifest.assets || []).filter(
    (asset) => Boolean(asset?.name && asset?.url && isAllowedDownloadUrl(asset.url)),
  );

  return {
    ok: true,
    currentVersion: "",
    latestVersion,
    hasUpdate: false,
    releaseName: manifest.name || latestVersion,
    releaseNotes: manifest.releaseNotes || manifest.notes || "",
    publishedAt: manifest.publishedAt || "",
    releaseUrl: manifest.releaseUrl || "",
    assets,
    source: "manifest",
  };
}

export async function fetchLatestVersionViaRedirect(
  owner: string,
  repo: string,
  fetchImpl: typeof fetch,
): Promise<{ version: string; releaseUrl: string } | null> {
  const response = await fetchImpl(`https://github.com/${owner}/${repo}/releases/latest`, {
    method: "GET",
    redirect: "manual",
    headers: { "User-Agent": "RailWatch-12306-Updater" },
  });

  const location = response.headers.get("location");
  const targetUrl = location
    ? new URL(location, `https://github.com/${owner}/${repo}/`).toString()
    : response.url;
  const tagMatch = targetUrl.match(/\/releases\/tag\/([^/?#]+)/i);
  if (!tagMatch?.[1]) {
    return null;
  }

  const tag = decodeURIComponent(tagMatch[1]);
  return {
    version: normalizeVersion(tag),
    releaseUrl: `https://github.com/${owner}/${repo}/releases/tag/${encodeURIComponent(tag)}`,
  };
}

async function fetchFromGitHubApi(config: UpdateCheckerConfig, fetchImpl: typeof fetch): Promise<UpdateCheckSuccess | null> {
  const endpoint = `https://api.github.com/repos/${config.owner}/${config.repo}/releases/latest`;
  const response = await fetchImpl(endpoint, {
    headers: buildGithubApiHeaders(config.githubToken),
  });

  if (!response.ok) {
    if (isGithubRateLimit(response)) {
      return null;
    }
    return null;
  }

  const payload = (await response.json()) as unknown;
  const parsed = parseGitHubRelease(payload, config.includePrerelease);
  if (!parsed.ok || parsed.assets.length === 0) {
    return null;
  }

  return finalizeCheckResult(config, { ...parsed, source: "api" });
}

async function fetchFromManifest(config: UpdateCheckerConfig, fetchImpl: typeof fetch): Promise<UpdateCheckSuccess | null> {
  if (!config.manifestUrl) {
    return null;
  }

  const response = await fetchImpl(config.manifestUrl, {
    headers: { "User-Agent": "RailWatch-12306-Updater" },
  });
  if (!response.ok) {
    return null;
  }

  const payload = (await response.json()) as unknown;
  const parsed = parseReleaseManifest(payload);
  if (!parsed.ok) {
    return null;
  }

  const tag = /^v/i.test(parsed.latestVersion) ? parsed.latestVersion : `v${parsed.latestVersion}`;
  const releaseUrl =
    parsed.releaseUrl || `https://github.com/${config.owner}/${config.repo}/releases/tag/${encodeURIComponent(tag)}`;
  const assets =
    parsed.assets.length > 0
      ? parsed.assets
      : buildFallbackAssets(config.owner, config.repo, parsed.latestVersion, config.productName);

  return finalizeCheckResult(config, { ...parsed, releaseUrl, assets, source: "manifest" });
}

async function fetchFromRedirect(config: UpdateCheckerConfig, fetchImpl: typeof fetch): Promise<UpdateCheckSuccess | null> {
  const latest = await fetchLatestVersionViaRedirect(config.owner, config.repo, fetchImpl);
  if (!latest) {
    return null;
  }

  return finalizeCheckResult(config, {
    ok: true,
    latestVersion: latest.version,
    releaseName: `${config.productName ?? DEFAULT_PRODUCT_NAME} ${latest.version}`,
    releaseNotes: "",
    publishedAt: "",
    releaseUrl: latest.releaseUrl,
    assets: buildFallbackAssets(config.owner, config.repo, latest.version, config.productName),
    source: "redirect",
  });
}

function classifyFetchError(error: unknown): UpdateCheckFailure["code"] {
  if (error instanceof Error) {
    if (/rate limit/i.test(error.message)) {
      return "rate-limit";
    }
    if (/fetch|network|ENOTFOUND|ECONNRESET|ETIMEDOUT/i.test(error.message)) {
      return "network";
    }
  }
  return "unknown";
}

export async function checkForUpdates(config: UpdateCheckerConfig, options: { force?: boolean } = {}): Promise<UpdateCheckResult> {
  const ttlMs = config.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
  const fetchImpl = config.fetchImpl ?? fetch;

  if (!options.force) {
    const cached = await readCache(config.cachePath, ttlMs);
    if (cached) {
      const result = finalizeCheckResult(config, cached);
      lastSuccessfulCheck = result;
      return result;
    }
  }

  try {
    const sources = [
      () => fetchFromGitHubApi(config, fetchImpl),
      () => fetchFromManifest(config, fetchImpl),
      () => fetchFromRedirect(config, fetchImpl),
    ];

    for (const loadSource of sources) {
      const result = await loadSource();
      if (!result) {
        continue;
      }

      lastSuccessfulCheck = result;
      await writeCache(config.cachePath, result);
      return result;
    }

    const stale = await readStaleCache(config.cachePath);
    if (stale) {
      const result = finalizeCheckResult(config, stale);
      lastSuccessfulCheck = result;
      return result;
    }

    return {
      ok: false,
      currentVersion: config.currentVersion,
      error: "无法获取最新版本信息。GitHub API 可能已达限额，请稍后重试或前往发布页查看。",
      code: "rate-limit",
    };
  } catch (error) {
    const stale = await readStaleCache(config.cachePath);
    if (stale) {
      const result = finalizeCheckResult(config, stale);
      lastSuccessfulCheck = result;
      return result;
    }

    return {
      ok: false,
      currentVersion: config.currentVersion,
      error: error instanceof Error ? error.message : "Failed to check for updates.",
      code: classifyFetchError(error),
    };
  }
}

export function getLastSuccessfulCheck(): UpdateCheckSuccess | null {
  return lastSuccessfulCheck;
}

export function resetLastSuccessfulCheck(): void {
  lastSuccessfulCheck = null;
}

async function verifySha256(filePath: string, expectedSha256: string): Promise<boolean> {
  const hash = createHash("sha256");
  const data = await fs.readFile(filePath);
  hash.update(data);
  return hash.digest("hex").toLowerCase() === expectedSha256.toLowerCase();
}

export async function downloadUpdateAsset(
  asset: UpdateAsset,
  downloadDir: string,
  fetchImpl: typeof fetch = fetch,
): Promise<UpdateDownloadResult> {
  if (!isAllowedDownloadUrl(asset.url)) {
    return { ok: false, error: "Download URL is not allowed.", code: "unknown" };
  }

  await fs.mkdir(downloadDir, { recursive: true });
  const tempPath = path.join(downloadDir, `${asset.name}.download`);
  const finalPath = path.join(downloadDir, asset.name);

  try {
    const response = await fetchImpl(asset.url, {
      headers: { "User-Agent": "RailWatch-12306-Updater" },
    });
    if (!response.ok || !response.body) {
      return {
        ok: false,
        error: `Download failed with status ${response.status}.`,
        code: "network",
      };
    }

    const nodeStream = Readable.fromWeb(response.body as import("node:stream/web").ReadableStream);
    await pipeline(nodeStream, createWriteStream(tempPath));

    if (asset.sha256) {
      const valid = await verifySha256(tempPath, asset.sha256);
      if (!valid) {
        await fs.rm(tempPath, { force: true });
        return { ok: false, error: "Downloaded file failed SHA-256 verification.", code: "hash-mismatch" };
      }
    }

    await fs.rm(finalPath, { force: true });
    await fs.rename(tempPath, finalPath);
    return { ok: true, filePath: finalPath, fileName: asset.name };
  } catch (error) {
    await fs.rm(tempPath, { force: true });
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Download failed.",
      code: "network",
    };
  }
}

export function createDefaultUpdateConfig(currentVersion: string, userDataPath: string): UpdateCheckerConfig {
  const owner = "railwatch";
  const repo = "railwatch-12306";
  const githubToken = process.env.RAILWATCH_GITHUB_TOKEN || process.env.GITHUB_TOKEN || undefined;

  return {
    owner,
    repo,
    currentVersion,
    cachePath: path.join(userDataPath, "update-cache.json"),
    githubToken,
    productName: DEFAULT_PRODUCT_NAME,
    manifestUrl: `https://raw.githubusercontent.com/${owner}/${repo}/main/releases/latest.json`,
  };
}
