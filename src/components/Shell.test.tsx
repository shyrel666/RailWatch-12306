// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { RAILWATCH_PAGES, SidebarNav } from "./Shell";

describe("SidebarNav", () => {
  test("keeps the Electron page names and reports navigation clicks", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();

    expect(RAILWATCH_PAGES.map((page) => page.name)).toEqual(["仪表盘", "行程设置", "监控", "设置"]);

    render(
      <SidebarNav
        activePage="仪表盘"
        appName="RailWatch 12306"
        dataDir="D:/RailWatch/data"
        phase="就绪"
        onPageChange={onPageChange}
      />,
    );

    expect(screen.getByText("RailWatch 12306")).toBeTruthy();
    expect(screen.getByText("D:/RailWatch/data")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /行程设置/ }));

    expect(onPageChange).toHaveBeenCalledWith("行程设置");
  });
});
