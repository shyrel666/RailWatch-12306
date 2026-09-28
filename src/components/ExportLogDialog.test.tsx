// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { useExportLogDialog } from "./ExportLogDialog";

const chosen = vi.fn();
function Harness() {
  const { choosePath, dialog } = useExportLogDialog();
  return <><button onClick={() => void choosePath().then(chosen)}>打开导出</button>{dialog}</>;
}
beforeEach(() => {
  chosen.mockClear();
  vi.spyOn(railwatchApi, "getExportLocations").mockResolvedValue({ directory: "C:/logs", fileName: "events.txt", shortcuts: [{ name: "下载", path: "C:/downloads" }] });
  vi.spyOn(railwatchApi, "listExportDirectory").mockImplementation(async directory => ({
    directory, parent: "C:/", folders: [], files: ["old.txt"],
  }));
  vi.spyOn(railwatchApi, "prepareLogExport").mockResolvedValue("C:/logs/events.txt");
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("Escape cancels without granting or exporting a path", async () => {
  render(<Harness />);
  await userEvent.click(screen.getByText("打开导出"));
  await screen.findByText("old.txt");
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(chosen).toHaveBeenCalledWith(null));
  expect(railwatchApi.prepareLogExport).not.toHaveBeenCalled();
});

test("saving resolves only an approved path and declining overwrite keeps the picker open", async () => {
  vi.mocked(railwatchApi.prepareLogExport).mockResolvedValueOnce(null);
  render(<Harness />);
  await userEvent.click(screen.getByText("打开导出"));
  await screen.findByText("old.txt");
  await userEvent.click(screen.getByRole("button", { name: "导出日志" }));
  expect(chosen).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeTruthy();
  await waitFor(() => expect(screen.getByRole("button", { name: "导出日志" }).hasAttribute("disabled")).toBe(false));
  await userEvent.click(screen.getByRole("button", { name: "导出日志" }));
  await waitFor(() => expect(chosen).toHaveBeenCalledWith("C:/logs/events.txt"));
});

test("a manually edited directory must be opened before saving", async () => {
  render(<Harness />);
  await userEvent.click(screen.getByText("打开导出"));
  await screen.findByText("old.txt");
  const location = screen.getByRole("textbox", { name: "保存文件夹" });
  await userEvent.clear(location);
  await userEvent.type(location, "C:/downloads");
  expect(screen.getByRole("button", { name: "导出日志" }).hasAttribute("disabled")).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "前往" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "导出日志" }).hasAttribute("disabled")).toBe(false));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "导出日志" }));
  expect(railwatchApi.prepareLogExport).toHaveBeenCalledWith("C:/downloads", "events.txt");
});

test("unmount cancels an outstanding picker", async () => {
  const view = render(<Harness />);
  await userEvent.click(screen.getByText("打开导出"));
  view.unmount();
  await waitFor(() => expect(chosen).toHaveBeenCalledWith(null));
});
