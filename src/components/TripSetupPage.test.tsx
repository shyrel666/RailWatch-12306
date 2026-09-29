// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { isoDaysFromToday, todayIso } from "../lib/tripDate";
import {
  defaultConfig,
  defaultRuntimeInfo,
  defaultStatus,
  railwatchStore,
} from "../store/railwatchStore";
import { TripSetupPage } from "./TripSetupPage";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";

function resetStore() {
  railwatchStore.setState({
    runtime: { ...defaultRuntimeInfo, state: { ...defaultStatus } },
    status: { ...defaultStatus, query_ready: true },
    config: { ...defaultConfig, train_code: "" },
    savedConfig: null,
    savedAt: null,
    configSaveError: null,
    draftRead: { status: "missing", draft: null, warning: null },
    tripInitialized: false,
    editRevision: 0,
    draftRevision: 0,
    draftSaveState: "idle",
    draftSavedAt: null,
    draftError: null,
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
  afterEach(cleanup);

  test("offers deadline choices and preserves manually entered dates on remount", async () => {
    const user = userEvent.setup();
    const renderPage = () => render(<TripSetupPage busy={null} confirm={async () => false}
      runCommand={(async () => undefined) as CommandRunner} />);
    let page = renderPage();
    await user.click(screen.getByText("自动化", { selector: "h2" }));
    const input = screen.getByRole("combobox", { name: "候补截止" });
    expect((input as HTMLInputElement).value).toBe("开车前1小时");
    await user.click(input);
    expect(screen.queryByText("开车前30分钟")).toBeNull();
    expect(await screen.findByText("开车前3小时", { selector: ".ant-select-item-option-content" })).toBeTruthy();
    await user.click(await screen.findByText("开车前1天", { selector: ".ant-select-item-option-content" }));
    expect(railwatchStore.getState().config.alternate_deadline).toBe("开车前1天");
    await user.click(input);
    await user.click(await screen.findByText("开车前20分钟", { selector: ".ant-select-item-option-content" }));
    expect(railwatchStore.getState().config.alternate_deadline).toBe("开车前20分钟");
    await user.clear(input);
    await user.type(input, "2026-10-01 18:00");
    await user.tab();
    expect(railwatchStore.getState().config.alternate_deadline).toBe("2026-10-01 18:00");
    page.unmount();
    page = renderPage();
    await user.click(screen.getByText("自动化", { selector: "h2" }));
    expect((screen.getByRole("combobox", { name: "候补截止" }) as HTMLInputElement).value).toBe("2026-10-01 18:00");
  });

  test("shows the automation seat requirement before leaving trip settings", () => {
    railwatchStore.setState({ config: { ...defaultConfig, auto_submit: true,
      train_code: "G9", passengers: "测试乘客", seat_keyword: "" } });
    render(<TripSetupPage busy={null} confirm={async () => false} runCommand={vi.fn(async () => undefined)} />);
    expect(screen.getByText(/请选择明确席别/)).toBeTruthy();
    expect(screen.getByText("自动化配置待完善")).toBeTruthy();
  });

  test("priority applies a complete preset, persists on remount, and leaves trip choices intact", async () => {
    const user = userEvent.setup();
    railwatchStore.setState({ config: { ...defaultConfig, interval: 20, query_timeout: 70,
      smart_rate: false, keep_alive: false, seat_prefer: "靠窗优先", train_code: "G101" } });
    const renderPage = () => render(<TripSetupPage busy={null} confirm={async () => false}
      runCommand={(async () => undefined) as CommandRunner} />);
    let page = renderPage();
    await user.click(screen.getByText("查询策略", { selector: "h2" }));
    await user.click(screen.getByRole("button", { name: "速度优先" }));
    expect(railwatchStore.getState().config).toMatchObject({ query_priority: "speed", request_mode: "fast",
      interval: 3, query_timeout: 20, smart_rate: true, keep_alive: true,
      seat_prefer: "靠窗优先", train_code: "G101", auto_submit: false, auto_alternate: false });
    expect(screen.getByText("3.0 ~ 3.6 秒")).toBeTruthy();
    await user.click(screen.getByLabelText("增加超时时间"));
    expect(screen.getByText(/已自定义/)).toBeTruthy();
    page.unmount();
    page = renderPage();
    await user.click(screen.getByText("查询策略", { selector: "h2" }));
    expect(screen.getByRole("button", { name: "速度优先" }).getAttribute("aria-pressed")).toBe("true");
    expect(railwatchStore.getState().config.query_timeout).toBe(21);
    await user.click(screen.getByRole("button", { name: "成功率优先" }));
    expect(railwatchStore.getState().config).toMatchObject({ query_priority: "reliability", request_mode: "conservative",
      interval: 6, query_timeout: 40, smart_rate: true, keep_alive: true });
    expect(screen.getByText("5.0 ~ 7.2 秒")).toBeTruthy();
  });

  test("restoring saved settings updates the selected priority and request mode", async () => {
    const user = userEvent.setup();
    const saved = { ...defaultConfig, query_priority: "speed" as const, request_mode: "balanced" as const,
      interval: 7.5, query_timeout: 51 };
    render(<TripSetupPage busy={null} confirm={async () => false}
      runCommand={(async () => saved) as CommandRunner} />);
    await user.click(screen.getByRole("button", { name: "恢复上次保存" }));
    await user.click(screen.getByText("查询策略", { selector: "h2" }));
    expect(screen.getByRole("button", { name: "速度优先" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("均衡模式")).toBeTruthy();
    expect(screen.getByText(/已自定义/)).toBeTruthy();
    expect(railwatchStore.getState().config.query_timeout).toBe(51);
  });

  test("normalizes train code input and keeps automation guarded by confirmation", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.type(screen.getByLabelText("车次"), "g101");

    expect(railwatchStore.getState().config.train_code).toBe("G101");

    await user.click(screen.getByText("自动化", { selector: "h2" }));
    const autoSubmitSwitch = screen.getByRole("switch", {
      name: /自动提交关闭.*无需人工点击确认/,
    });
    await user.click(autoSubmitSwitch);

    expect(confirm).toHaveBeenCalledWith(
      "启用自动提交",
      expect.stringContaining("自动提交"),
    );
    expect(railwatchStore.getState().config.auto_submit).toBe(false);
    expect(vi.mocked(runCommand).mock.calls.some(([command]) => command === "startMonitor")).toBe(false);
  });

  test("route favorites use saved personal trains and preserve their order", async () => {
    const user = userEvent.setup();
    railwatchStore.setState({ config: { ...defaultConfig, train_code: "" } });
    const runCommand = vi.fn(async (command: string) => command === "loadTripChoices" ? {
      recent_routes: [], favorites: [{ from_station: "北京", to_station: "上海", trains: ["G101", "D21"] }],
    } : undefined) as CommandRunner;

    render(
      <TripSetupPage
        busy={null}
        confirm={(async () => false) as ConfirmDialog}
        runCommand={runCommand}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /应用 G101、D21/ }));
    expect(railwatchStore.getState().config.train_code).toBe("G101, D21");
    await user.click(screen.getByRole("button", { name: "上移 D21" }));
    expect(railwatchStore.getState().config.train_code).toBe("D21, G101");
    await user.click(screen.getByRole("button", { name: "交换出发站与到达站" }));
    expect(screen.queryByRole("button", { name: /应用 G101、D21/ })).toBeNull();
    expect(screen.getByText(/现有目标车次会保留/)).toBeTruthy();
  });

  test("official adult candidate can be selected while ambiguous and unsupported types stay disabled", async () => {
    const user = userEvent.setup();
    const runCommand = vi.fn(async (command: string) => command === "readPassengers" ? { items: [
      { name: "张三", ticket_type: "adult", identity_hint: "11***22", ambiguous: false },
      { name: "李四", ticket_type: "student", identity_hint: "33***44", ambiguous: false },
      { name: "王五", ticket_type: "adult", identity_hint: "55***66", ambiguous: true },
      { name: "赵六", ticket_type: "unknown", identity_hint: "", ambiguous: false },
    ], warning: null } : undefined) as CommandRunner;
    render(<TripSetupPage busy={null} confirm={async () => false} runCommand={runCommand} />);
    await user.click(screen.getByRole("button", { name: "从官方页面读取乘客" }));
    await user.click(await screen.findByRole("button", { name: /张三.*成人/ }));
    expect(railwatchStore.getState().config.passengers).toBe("张三");
    expect(railwatchStore.getState().config.passenger_selections).toEqual([
      { name: "张三", ticket_type: "adult", identity_hint: "11***22" },
    ]);
    expect(screen.getByRole("button", { name: /李四.*票种不支持自动交易/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: /王五.*同名需人工核对/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: /赵六.*列表未标票种/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.queryByText("张三 成人")).toBeNull();
  });

  test("passenger import disables repeat clicks, clears stale candidates and recovers after failure", async () => {
    const user = userEvent.setup();
    let rejectRead!: (reason: Error) => void;
    const read = vi.fn().mockResolvedValueOnce({ items: [
      { name: "张三", ticket_type: "adult", identity_hint: "11***22", ambiguous: false },
    ], warning: null }).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRead = reject; }));
    const runCommand = vi.fn(async (command: string) => command === "readPassengers" ? read() : undefined) as CommandRunner;
    render(<TripSetupPage busy={null} confirm={async () => false} runCommand={runCommand} />);
    await user.click(screen.getByRole("button", { name: "从官方页面读取乘客" }));
    expect(await screen.findByRole("button", { name: /张三.*成人/ })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "从官方页面读取乘客" }));
    const loading = screen.getByRole("button", { name: "正在读取官方乘客…" });
    expect(loading.hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: /张三.*成人/ })).toBeNull();
    await user.click(loading);
    expect(read).toHaveBeenCalledTimes(2);
    await act(async () => rejectRead(new Error("unavailable")));
    expect(screen.getByText("读取未完成，请检查浏览器状态后重试。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "从官方页面读取乘客" }).hasAttribute("disabled")).toBe(false);
  });

  test("passenger import is unavailable while monitoring owns the browser", async () => {
    const user = userEvent.setup();
    railwatchStore.setState({ status: { ...defaultStatus, monitoring: true } });
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    render(<TripSetupPage busy={null} confirm={async () => false} runCommand={runCommand} />);
    await user.click(screen.getByRole("button", { name: "从官方页面读取乘客" }));
    expect(vi.mocked(runCommand).mock.calls.some(([command]) => command === "readPassengers")).toBe(false);
    expect(screen.getByText("监控运行中，请停止监控后读取乘客。")).toBeTruthy();
  });

  test("draft recovery changes editing config without starting a task", async () => {
    const user = userEvent.setup();
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({ savedConfig: { ...defaultConfig }, tripInitialized: true,
      draftRead: { status: "available", warning: null, draft: { schema_version: 1, revision: 4,
        saved_at: Date.now() / 1000, config: { from_station_cn: "杭州", date: "bad-date", auto_submit: true } } } });
    render(<TripSetupPage busy={null} confirm={async () => false} runCommand={runCommand} />);
    await user.click(screen.getByRole("button", { name: "恢复草稿" }));
    expect(railwatchStore.getState().config).toMatchObject({ from_station_cn: "杭州", date: "bad-date", auto_submit: true });
    expect(screen.getByText("有未正式保存的修改")).toBeTruthy();
    expect(vi.mocked(runCommand).mock.calls.some(([command]) => command === "startMonitor")).toBe(false);
  });

  test("groups all preferences without dashboard workflow", async () => {
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    expect(screen.getByRole("heading", { name: "路线与乘客" })).toBeTruthy();
    expect(screen.getByText("配置查询条件与监控策略")).toBeTruthy();
    expect(screen.getByRole("button", { name: "恢复上次保存" })).toBeTruthy();
    expect(screen.getByLabelText("出发站")).toBeTruthy();
    expect(screen.getByLabelText("到达站")).toBeTruthy();
    expect(screen.getByLabelText("出发日期")).toBeTruthy();
    expect(screen.getByRole("group", { name: "日期范围" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "席别" })).toBeTruthy();
    await userEvent.click(screen.getByText("查询策略", { selector: "h2" }));
    await userEvent.click(screen.getByText("定时启动", { selector: "h2" }));
    await userEvent.click(screen.getByText("自动化", { selector: "h2" }));
    expect(screen.getByRole("group", { name: "优先级" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存配置" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "查询余票" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "开始监控" })).toBeNull();
    expect(screen.queryByRole("button", { name: /高级选项/ })).toBeNull();
    expect(screen.queryByRole("list", { name: "监控流程" })).toBeNull();
    expect(screen.queryByText("高级选项")).toBeNull();
    expect(screen.getByText("自动提交关闭")).toBeTruthy();
    expect(screen.getByText("候补排队关闭")).toBeTruthy();
    expect(screen.getByRole("radiogroup", { name: "开始方式" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "保持会话" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "智能轮询" })).toBeTruthy();
  });

  test("swaps departure and arrival stations", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.click(
      screen.getByRole("button", { name: "交换出发站与到达站" }),
    );

    expect(railwatchStore.getState().config.from_station_cn).toBe("上海");
    expect(railwatchStore.getState().config.to_station_cn).toBe("北京");
  });

  test("writes query timeout and supported date range into backend config shape", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.click(screen.getByRole("button", { name: "±2天" }));
    await user.click(screen.getByText("查询策略", { selector: "h2" }));
    await user.click(screen.getByLabelText("增加超时时间"));

    expect(railwatchStore.getState().config.date_range).toBe("±2天");
    expect(railwatchStore.getState().config.query_timeout).toBe(41);
    expect(screen.queryByRole("button", { name: "自定义" })).toBeNull();
  });

  test("date picker cannot start before today and shows no hint for a valid date", () => {
    railwatchStore.setState({
      config: { ...defaultConfig, date: isoDaysFromToday(3) },
    });

    render(
      <TripSetupPage
        busy={null}
        confirm={(async () => false) as ConfirmDialog}
        runCommand={(async () => undefined) as CommandRunner}
      />,
    );

    expect(screen.getByLabelText("出发日期").getAttribute("min")).toBe(
      todayIso(),
    );
    expect(screen.queryByText(/出发日期已过去/)).toBeNull();
    expect(screen.queryByText(/超出.*预售/)).toBeNull();
  });

  test("saving an expired departure date requires confirmation and respects a decline", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({
      config: { ...defaultConfig, date: "2020-01-01" },
    });

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    expect(screen.getByText(/出发日期已过去/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "保存配置" }));

    expect(confirm).toHaveBeenCalledWith(
      "出发日期已过期",
      expect.stringContaining("2020-01-01"),
    );
    expect(vi.mocked(runCommand).mock.calls.some(([command]) => command === "saveConfig")).toBe(false);
  });

  test("saving an expired departure date proceeds after explicit confirmation", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => true) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({
      config: { ...defaultConfig, date: "2020-01-01" },
    });

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.click(screen.getByRole("button", { name: "保存配置" }));

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(runCommand).toHaveBeenCalledWith(
      "saveConfig",
      { config: expect.objectContaining({ date: "2020-01-01" }) },
      "设置已保存",
    );
  });

  test("saving a valid date does not trigger the expired-date confirmation", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({
      config: { ...defaultConfig, date: isoDaysFromToday(3) },
    });

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.click(screen.getByRole("button", { name: "保存配置" }));

    expect(confirm).not.toHaveBeenCalled();
    expect(runCommand).toHaveBeenCalledWith(
      "saveConfig",
      { config: expect.anything() },
      "设置已保存",
    );
  });
});
