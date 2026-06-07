// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { SettingsPage } from "./SettingsPage";
import type { CommandRunner } from "./componentTypes";

function resetStore() {
  railwatchStore.setState({
    runtime: {
      ...defaultRuntimeInfo,
      data_dir: "C:/RailWatch/data",
      chromedriver_path: "D:/RailWatch/chromedriver.exe",
      chrome_version: "Chrome 148",
      state: { ...defaultStatus },
    },
    status: { ...defaultStatus },
  });
}

describe("SettingsPage", () => {
  beforeEach(resetStore);

  test("shows appearance, local runtime data, and separated maintenance actions", () => {
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    const setDarkMode = vi.fn();

    render(<SettingsPage busy={null} darkMode={false} runCommand={runCommand} setDarkMode={setDarkMode} />);

    expect(screen.getByRole("heading", { name: "外观" })).toBeTruthy();
    expect(screen.getByText("暗色模式")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "本地运行" })).toBeTruthy();
    expect(screen.getByText("C:/RailWatch/data")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "维护操作" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /清除数据/ })).toBeTruthy();
  });
});
