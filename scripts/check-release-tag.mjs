#!/usr/bin/env node
// Release jobs must run from a version tag whose version matches the app and
// runtime versions. Exports RELEASE_TAG and PACKAGE_VERSION to later steps.
import { appendFileSync, readFileSync } from "node:fs";

function fail(message) {
  console.error(`::error::${message}`);
  process.exit(1);
}

const ref = process.env.GITHUB_REF || "";
if (!ref.startsWith("refs/tags/v")) {
  fail(`Run the release workflow from a version tag (refs/tags/v*), not ${ref || "an unknown ref"}.`);
}
const tag = ref.slice("refs/tags/".length);
const version = JSON.parse(readFileSync("package.json", "utf8")).version;
const runtimeVersion = /^version\s*=\s*"([^"]+)"/m.exec(readFileSync("pyproject.toml", "utf8"))?.[1];
if (tag !== `v${version}`) fail(`Tag ${tag} does not match package.json version ${version}.`);
if (runtimeVersion !== version) fail(`pyproject.toml version ${runtimeVersion} does not match package.json version ${version}.`);
if (process.env.GITHUB_ENV) {
  appendFileSync(process.env.GITHUB_ENV, `RELEASE_TAG=${tag}\nPACKAGE_VERSION=${version}\n`);
}
console.log(`Release ${tag} matches app and runtime version ${version}.`);
