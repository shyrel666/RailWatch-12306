// electron-updater performs the checks; this module keeps the result shape the
// renderer receives and the release page used for manual downloads.

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

/** The release page users open to download an installer by hand. */
export function releaseTagUrl(version: string): string {
  const tag = version.startsWith("v") ? version : `v${version}`;
  return `https://github.com/${RELEASE_OWNER}/${RELEASE_REPO}/releases/tag/${encodeURIComponent(tag)}`;
}
