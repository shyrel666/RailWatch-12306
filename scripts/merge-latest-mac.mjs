#!/usr/bin/env node
// Merge the latest-mac.yml files written by the arm64 and x64 macOS builds into
// one updater manifest. electron-updater picks files by "arm64" in their name.
//
// Usage: node scripts/merge-latest-mac.mjs <arm64 latest-mac.yml> <x64 latest-mac.yml> > latest-mac.yml
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import yaml from "js-yaml";

const isArm64File = (file) => String(file.url).includes("arm64");

function checkManifest(manifest, label) {
  if (!manifest || typeof manifest !== "object" || typeof manifest.version !== "string" || !Array.isArray(manifest.files)
      || manifest.files.length === 0 || manifest.files.some((file) => !file || typeof file.url !== "string")) {
    throw new Error(`${label} latest-mac.yml is malformed`);
  }
}

export function mergeLatestMac(arm64, x64) {
  checkManifest(arm64, "arm64");
  checkManifest(x64, "x64");
  if (arm64.version !== x64.version) {
    throw new Error(`Version mismatch: arm64 ${arm64.version}, x64 ${x64.version}`);
  }
  if (!arm64.files.every(isArm64File)) throw new Error("arm64 latest-mac.yml lists non-arm64 files");
  if (x64.files.some(isArm64File)) throw new Error("x64 latest-mac.yml lists arm64 files");
  const files = [];
  const seen = new Set();
  for (const file of [...arm64.files, ...x64.files]) {
    if (seen.has(file.url)) continue;
    seen.add(file.url);
    files.push(file);
  }
  const releaseDates = [arm64.releaseDate, x64.releaseDate].filter(Boolean).map(String).sort();
  return {
    ...x64,
    files,
    // Older updaters without architecture filtering read the top-level entry;
    // x64 runs on both architectures (Apple Silicon through Rosetta).
    path: x64.path,
    sha512: x64.sha512,
    ...(releaseDates.length ? { releaseDate: releaseDates[releaseDates.length - 1] } : {}),
  };
}

function main(argv) {
  if (argv.length !== 2) {
    throw new Error("Usage: node scripts/merge-latest-mac.mjs <arm64 latest-mac.yml> <x64 latest-mac.yml>");
  }
  // JSON_SCHEMA keeps releaseDate a string instead of turning it into a Date.
  const [arm64, x64] = argv.map((file) => yaml.load(readFileSync(file, "utf8"), { schema: yaml.JSON_SCHEMA }));
  process.stdout.write(yaml.dump(mergeLatestMac(arm64, x64), { lineWidth: -1 }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}
