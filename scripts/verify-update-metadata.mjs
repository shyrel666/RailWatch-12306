#!/usr/bin/env node
// Check an electron-builder update manifest (latest.yml / latest-mac.yml) against
// the files next to it: version, referenced files, sizes and SHA-512 hashes.
//
// Usage: node scripts/verify-update-metadata.mjs --version 0.6.0 [--arch arm64|x64] <manifest.yml>
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import yaml from "js-yaml";

export function verifyUpdateMetadata(manifestPath, { version, arch } = {}) {
  const directory = path.dirname(manifestPath);
  const manifest = yaml.load(readFileSync(manifestPath, "utf8"), { schema: yaml.JSON_SCHEMA });
  const problems = [];
  if (!manifest || typeof manifest !== "object" || !Array.isArray(manifest.files) || manifest.files.length === 0) {
    throw new Error(`${manifestPath} has no files`);
  }
  if (version && manifest.version !== version) problems.push(`version ${manifest.version} is not ${version}`);
  for (const file of manifest.files) {
    const filePath = path.join(directory, String(file.url));
    let size;
    try {
      size = statSync(filePath).size;
    } catch {
      problems.push(`missing ${file.url}`);
      continue;
    }
    if (file.size !== size) problems.push(`${file.url} is ${size} bytes, metadata says ${file.size}`);
    const sha512 = createHash("sha512").update(readFileSync(filePath)).digest("base64");
    if (file.sha512 !== sha512) problems.push(`${file.url} SHA-512 does not match`);
    if (arch === "arm64" && !String(file.url).includes("arm64")) problems.push(`${file.url} is not an arm64 file`);
    if (arch === "x64" && String(file.url).includes("arm64")) problems.push(`${file.url} is an arm64 file`);
  }
  if (manifest.path && !manifest.files.some((file) => file.url === manifest.path)) {
    problems.push(`top-level path ${manifest.path} is not listed in files`);
  }
  if (problems.length) throw new Error(`${manifestPath}: ${problems.join("; ")}`);
  return manifest.files.map((file) => String(file.url));
}

function main(argv) {
  const options = {};
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--version") options.version = argv[++index];
    else if (argv[index] === "--arch") options.arch = argv[++index];
    else positional.push(argv[index]);
  }
  if (positional.length !== 1 || !options.version) {
    throw new Error("Usage: node scripts/verify-update-metadata.mjs --version <version> [--arch arm64|x64] <manifest.yml>");
  }
  for (const file of verifyUpdateMetadata(positional[0], options)) console.log(file);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`::error::${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}
