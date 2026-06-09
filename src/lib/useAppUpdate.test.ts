import { describe, expect, test } from "vitest";
import { getUpdateStatusLabel } from "./useAppUpdate";
import type { UpdateRuntimeState } from "../types";

describe("getUpdateStatusLabel", () => {
  test("describes downloaded update state", () => {
    const state: UpdateRuntimeState = {
      phase: "downloaded",
      currentVersion: "0.1.0",
      latestVersion: "1.2.0",
    };

    expect(getUpdateStatusLabel(state)).toBe("新版本 1.2.0 已下载，等待重启安装");
  });

  test("describes download progress", () => {
    const state: UpdateRuntimeState = {
      phase: "downloading",
      currentVersion: "0.1.0",
      latestVersion: "1.2.0",
      downloadPercent: 42.4,
    };

    expect(getUpdateStatusLabel(state)).toBe("正在下载更新 42%");
  });
});
