import { describe, expect, test } from "vitest";
import type { LogEntry } from "../types";
import { countEventsByFilter, eventCategory, presentEventLogs, summarizeEventLogs, filterPresentedEvents, formatEventTime } from "./formatEventLog";

test.each([
  ["2026-09-28T14:01:01+08:00", "2026-09-28 14:01:01"],
  ["2026-09-28T14:01:01.123456+08:00", "2026-09-28 14:01:01"],
  ["2026-09-27T20:01:01Z", "2026-09-28 04:01:01"],
  ["2026-09-27T20:01:01-04:00", "2026-09-28 08:01:01"],
  ["14:01:01", "14:01:01"],
  ["unknown", "unknown"],
  ["2026-13-28T14:01:01+08:00", "2026-13-28T14:01:01+08:00"],
  ["2026-02-30T14:01:01+08:00", "2026-02-30T14:01:01+08:00"],
  ["2026-09-28T24:00:00+08:00", "2026-09-28T24:00:00+08:00"],
])("formats event time %s for display in Beijing time", (input, expected) => {
  expect(formatEventTime(input)).toBe(expected);
});

test("one presentation preserves every filter and merged-entry count", () => {
  const logs: LogEntry[] = [
    { time: "12:00", level: "INFO", message: "环境检查" },
    { time: "12:01", level: "INFO", message: "Python 3.10.8" },
    { time: "12:02", level: "WARN", message: "需要核验" },
    { time: "12:03", level: "ERROR", message: "连接失败" },
    { time: "12:04", level: "SUCCESS", message: "已完成" },
  ];
  const summary = summarizeEventLogs(logs);
  for (const filter of ["全部", "信息", "警告", "错误"]) {
    expect(filterPresentedEvents(summary.entries, filter)).toEqual(presentEventLogs(logs, filter));
    expect(summary.counts[filter]).toBe(countEventsByFilter(logs, filter));
  }
});

const envCheckLogs: LogEntry[] = [
  { time: "19:54:17", level: "INFO", message: "正在检查 Python、Selenium 和 ChromeDriver..." },
  { time: "19:54:17", level: "INFO", message: "Python 3.10.8" },
  { time: "19:54:17", level: "INFO", message: "平台 win32" },
  { time: "19:54:17", level: "INFO", message: "Chrome 版本: 148" },
  { time: "19:54:17", level: "SUCCESS", message: "ChromeDriver 已找到: D:/driver/chromedriver.exe" },
  { time: "19:54:18", level: "SUCCESS", message: "✅ undetected-chromedriver 初始化成功" },
  { time: "19:54:18", level: "INFO", message: "📁 用户数据目录: C:/profile" },
];

describe("presentEventLogs", () => {
  test("shows newest events first", () => {
    const logs: LogEntry[] = [
      { time: "09:00:01", level: "INFO", message: "应用启动：RailWatch 12306 已启动" },
      { time: "09:00:02", level: "ERROR", message: "登录状态失效" },
    ];

    const events = presentEventLogs(logs, "全部");

    expect(events[0]?.title).toBe("登录状态失效");
    expect(events[1]?.title).toBe("应用启动");
  });

  test("filters non-G query result rows out of the event feed", () => {
    const events = presentEventLogs(
      [
        { time: "09:00:00", level: "INFO", message: "🚄 D321 | 北京 上海 二等座 有" },
        { time: "09:00:01", level: "INFO", message: "系统就绪" },
      ],
      "全部",
    );

    expect(events.map((event) => event.title)).toEqual(["系统就绪"]);
  });

  test("collapses technical environment logs into one entry", () => {
    const events = presentEventLogs(envCheckLogs, "全部");

    expect(events).toHaveLength(2);
    expect(events[0]?.title).toBe("环境检查通过");
    expect(events[1]?.title).toBe("环境检查");
    expect(events[1]?.detail).toContain("正在检查 Python");
    expect(events[1]?.detail).toContain("Python 3.10.8");
    expect(events[1]?.detail).toContain("平台 win32");
    expect(events[1]?.detail).toContain("Chrome 版本: 148");
    expect(events[1]?.detail).toContain("D:/driver/chromedriver.exe");
    expect(events[0]?.detail).toContain("C:/profile");
  });

  test("splits colon separated messages into title and detail", () => {
    const events = presentEventLogs(
      [{ time: "15:42:18", level: "INFO", message: "查询就绪：已准备就绪，等待启动监控" }],
      "全部",
    );

    expect(events[0]?.title).toBe("查询就绪");
    expect(events[0]?.detail).toBe("已准备就绪，等待启动监控");
  });

  test("filters train row noise from the event feed", () => {
    const logs: LogEntry[] = [
      { time: "20:02:18", level: "INFO", message: "解析到 53 条车次结果（展示前 10 条）：" },
      { time: "20:02:18", level: "INFO", message: "G599 | 北京南 06:30 -> 上海虹桥 12:20 ..." },
      { time: "20:02:18", level: "INFO", message: "G37 | 北京南 07:00 -> 上海虹桥 11:30 ..." },
    ];

    const events = presentEventLogs(logs, "全部");

    expect(events).toHaveLength(1);
    expect(events[0]?.title).toBe("查询完成");
    expect(events[0]?.detail).toBe("共 53 条车次结果");
  });

  test("counts SUCCESS entries under the info filter", () => {
    expect(countEventsByFilter(envCheckLogs, "信息")).toBe(2);
    expect(countEventsByFilter(envCheckLogs, "警告")).toBe(0);
  });

  test("never hides warning or error messages matching technical or query prefixes", () => {
    const logs: LogEntry[] = [
      envCheckLogs[0],
      { time: "19:54:18", level: "WARN", message: "未找到 ChromeDriver。" },
      { time: "19:54:19", level: "ERROR", message: "等待查询结果：超时" },
      { time: "19:54:20", level: "INFO", message: "提示: 请下载驱动" },
    ];
    const all = presentEventLogs(logs, "全部");
    expect(all.find(entry => entry.level === "WARN")?.message).toBe(logs[1].message);
    expect(all.find(entry => entry.level === "ERROR")?.message).toBe(logs[2].message);
    expect(all.find(entry => entry.level === "ERROR")?.detail).toBe("超时");
    for (const filter of ["全部", "信息", "警告", "错误"]) {
      const visible = presentEventLogs(logs, filter);
      expect(countEventsByFilter(logs, filter)).toBe(visible.length);
      for (const entry of visible) expect(all).toContainEqual(entry);
    }
    expect(countEventsByFilter(logs, "警告")).toBe(1);
    expect(countEventsByFilter(logs, "错误")).toBe(1);
  });

  test("collapses consecutive identical lines and keeps the first occurrence", () => {
    const line = { level: "INFO", message: "站点编码缓存已加载：3404 条" };
    const events = presentEventLogs([
      { ...line, time: "21:49:39" },
      { ...line, time: "21:49:40" },
      { time: "21:49:41", level: "INFO", message: "已加载保存的设置。" },
      { ...line, time: "21:49:42" },
    ], "全部");
    expect(events.map((event) => [event.title, event.repeat])).toEqual([
      ["站点编码缓存已加载", 1], ["已加载保存的设置。", 1], ["站点编码缓存已加载", 2],
    ]);
    expect(events[2]?.time).toBe("21:49:40");
    expect(events[2]?.firstTime).toBe("21:49:39");
    expect(countEventsByFilter([{ ...line, time: "1" }, { ...line, time: "2", run_id: "other" }], "全部")).toBe(2);
  });

  test("labels each entry with its topic", () => {
    expect(eventCategory("站点编码缓存已加载：3404 条")).toBe("站码");
    expect(eventCategory("已加载保存的设置。")).toBe("设置");
    expect(eventCategory("起售前登录检查通过，最后10秒停止保活检查。")).toBe("登录");
    expect(eventCategory("监控已启动：正在查询目标车次")).toBe("监控");
    expect(eventCategory("ChromeDriver 已自动更新到匹配版本。")).toBe("环境");
    expect(eventCategory("应用启动")).toBe("系统");
  });

  test("verbose mode keeps query steps and technical lines as separate entries", () => {
    const logs: LogEntry[] = [
      ...envCheckLogs,
      { time: "20:02:18", level: "INFO", message: "G599 | 北京南 06:30 -> 上海虹桥 12:20 ..." },
    ];
    expect(presentEventLogs(logs, "全部")).toHaveLength(2);
    expect(presentEventLogs(logs, "全部", true)).toHaveLength(logs.length);
    expect(summarizeEventLogs(logs, true).counts.全部).toBe(logs.length);
  });

  test("does not attach technical details to unrelated events or another run", () => {
    const logs: LogEntry[] = [
      { time: "09:00:00", level: "SUCCESS", message: "已加载保存的设置。" },
      { ...envCheckLogs[1], run_id: "old" },
      { ...envCheckLogs[2], run_id: "new" },
    ];
    expect(presentEventLogs(logs, "全部")).toHaveLength(3);
  });
});
