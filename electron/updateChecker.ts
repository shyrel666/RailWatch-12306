// electron-updater performs the checks; this module keeps the result shape the
// renderer receives and the release page used for manual downloads.

export type UpdateAsset = {
  name: string;
  url: string;
  size: number;
  sha256?: string;
};

export type MacArch = "arm64" | "x64";

export type UpdateFileMetadata = {
  url?: string;
  size?: number;
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
  downloadUrl?: string;
  targetArch?: MacArch;
  assets: UpdateAsset[];
  source?: "updater";
};

export type UpdateCheckFailure = {
  ok: false;
  currentVersion: string;
  error: string;
  code: "network" | "no-assets" | "unknown";
};

export type UpdateCheckResult = UpdateCheckSuccess | UpdateCheckFailure;

const RELEASE_OWNER = "shyrel666";
const RELEASE_REPO = "RailWatch-12306";
export const LATEST_RELEASE_URL = `https://github.com/${RELEASE_OWNER}/${RELEASE_REPO}/releases/latest`;

/** Selects the native macOS architecture, steering Rosetta-translated x64 apps to arm64. */
export function resolveMacTargetArch(processArch: string, runningUnderARM64Translation = false): MacArch {
  return processArch === "arm64" || runningUnderARM64Translation ? "arm64" : "x64";
}

/** The release page users open to inspect release notes or browse all installers. */
export function releaseTagUrl(version: string): string {
  const tag = version.startsWith("v") ? version : `v${version}`;
  return `https://github.com/${RELEASE_OWNER}/${RELEASE_REPO}/releases/tag/${encodeURIComponent(tag)}`;
}

/** Direct GitHub release asset download URL for a specific release tag and asset file name. */
export function releaseAssetUrl(versionOrTag: string, assetName: string): string {
  const tag = versionOrTag.startsWith("v") ? versionOrTag : `v${versionOrTag}`;
  const normalizedAsset = assetName.replace(/^\/+/, "");
  return `https://github.com/${RELEASE_OWNER}/${RELEASE_REPO}/releases/download/${encodeURIComponent(tag)}/${encodeURIComponent(normalizedAsset)}`;
}

/** Finds the architecture-matching macOS DMG metadata entry from electron-updater files. */
export function findMacDmgAsset(
  files: readonly UpdateFileMetadata[] | undefined,
  arch: MacArch,
): { fileName: string; url?: string; size?: number } | undefined {
  if (!Array.isArray(files)) return undefined;
  const archPattern = new RegExp(`[-_.]${arch}\\.dmg$`, "i");
  for (const file of files) {
    const rawUrl = typeof file?.url === "string" ? file.url.trim() : "";
    if (!rawUrl) continue;
    const cleanPath = rawUrl.split(/[?#]/, 1)[0];
    const fileName = cleanPath.split("/").pop() || cleanPath;
    if (archPattern.test(fileName)) {
      return {
        fileName,
        url: rawUrl.startsWith("https://") ? rawUrl : undefined,
        size: typeof file.size === "number" && file.size > 0 ? file.size : undefined,
      };
    }
  }
  return undefined;
}

/** Resolves a direct DMG download URL and package size for the target macOS architecture. */
export function resolveMacDmgDownload(options: {
  version: string;
  tag?: string;
  arch: MacArch;
  files?: readonly UpdateFileMetadata[];
}): { downloadUrl: string; targetArch: MacArch; packageSize?: number; fileName: string } {
  const rawVersion = options.version.trim();
  const normalizedVersion = rawVersion.startsWith("v") ? rawVersion.slice(1) : rawVersion;
  const matched = findMacDmgAsset(options.files, options.arch);
  if (!normalizedVersion && !matched) {
    return {
      downloadUrl: LATEST_RELEASE_URL,
      targetArch: options.arch,
      fileName: "",
    };
  }
  const tag = options.tag?.trim() || (rawVersion.startsWith("v") ? rawVersion : `v${normalizedVersion}`);
  const fileName = matched?.fileName || `RailWatch-12306-${normalizedVersion}-${options.arch}.dmg`;
  const downloadUrl = matched?.url || (tag ? releaseAssetUrl(tag, fileName) : LATEST_RELEASE_URL);
  return {
    downloadUrl,
    targetArch: options.arch,
    packageSize: matched?.size,
    fileName,
  };
}
