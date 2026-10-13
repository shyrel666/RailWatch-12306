import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, expect, test } from "vitest";
import { MAX_SOUND_BYTES, prepareSoundImport, readImportedSound, storeImportedSound } from "../alertSoundFiles";

const temporaryDirectories: string[] = [];
async function workspace() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "railwatch-sound-test-"));
  temporaryDirectories.push(directory);
  return directory;
}
afterEach(async () => {
  for (const directory of temporaryDirectories.splice(0)) {
    if (path.dirname(directory) !== path.resolve(os.tmpdir()) || !path.basename(directory).startsWith("railwatch-sound-test-")) {
      throw new Error("Refused cleanup outside the sound test directory.");
    }
    await rm(directory, { recursive: true });
  }
});

test("imports are independent of the original filename and survive the original file being removed", async () => {
  const directory = await workspace();
  const original = path.join(directory, "我的提示音🎵.WAV");
  const content = Buffer.from("audio fixture");
  await writeFile(original, content);
  const asset = await prepareSoundImport(original);
  const imported = path.join(directory, "notification-sounds");
  await storeImportedSound(asset, imported);
  await storeImportedSound(asset, imported);
  await rm(original);
  expect(asset.name).toBe("我的提示音🎵.WAV");
  expect(await readImportedSound(asset.file, imported)).toBe(content.toString("base64"));
  expect(await readFile(path.join(imported, asset.file))).toEqual(content);
});

test("rejects unsupported, empty and oversized files", async () => {
  const directory = await workspace();
  await expect(prepareSoundImport(path.join(directory, "video.mp4"))).rejects.toThrow("WAV");
  const empty = path.join(directory, "empty.wav");
  await writeFile(empty, "");
  await expect(prepareSoundImport(empty)).rejects.toThrow("非空");
  const large = path.join(directory, "large.mp3");
  await writeFile(large, Buffer.alloc(MAX_SOUND_BYTES + 1));
  await expect(prepareSoundImport(large)).rejects.toThrow("10 MB");
});

test("rejects traversal and modified imported content, and reports missing files", async () => {
  const directory = await workspace();
  await expect(readImportedSound("../secrets.wav", directory)).rejects.toThrow("先导入");
  await expect(readImportedSound("a".repeat(64) + ".wav", directory)).rejects.toThrow("已丢失");
  const original = path.join(directory, "fixture.wav");
  await writeFile(original, "first");
  const asset = await prepareSoundImport(original);
  const imported = path.join(directory, "sounds");
  await storeImportedSound(asset, imported);
  await writeFile(path.join(imported, asset.file), "changed");
  await expect(readImportedSound(asset.file, imported)).rejects.toThrow("已变更");
});
