// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { defaultConfig, defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { TripSetupPage } from "./TripSetupPage";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";

function resetStore() {
  railwatchStore.setState({
    runtime: { ...defaultRuntimeInfo, state: { ...defaultStatus } },
    status: { ...defaultStatus },
    config: { ...defaultConfig, train_code: "" },
    logs: [],
    results: [],
    hits: [],
    notifications: [],
    activePage: "行程设置",
    logPaused: false,
    eventPanelVisible: true,
  });
}

describe("TripSetupPage", () => {
  beforeEach(resetStore);

  test("normalizes train code input and keeps automation guarded by confirmation", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    const { container } = render(<TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />);

    await user.type(screen.getByLabelText("车次"), "g101");

    expect(railwatchStore.getState().config.train_code).toBe("G101");

    const autoSubmitSwitch = screen.getByText("有票时自动提交").closest("label")?.querySelector("button");
    expect(autoSubmitSwitch).toBeTruthy();

    await user.click(autoSubmitSwitch ?? container);

    expect(confirm).toHaveBeenCalledWith("启用自动提交", expect.stringContaining("自动提交"));
    expect(railwatchStore.getState().config.auto_submit).toBe(false);
    expect(runCommand).not.toHaveBeenCalled();
  });
});
