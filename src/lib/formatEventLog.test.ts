import { describe, expect, test } from "vitest";
import type { LogEntry } from "../types";
import { countEventsByFilter, presentEventLogs } from "./formatEventLog";

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
    expect(countEventsByFilter(envCheckLogs, "信息")).toBe(7);
    expect(countEventsByFilter(envCheckLogs, "警告")).toBe(0);
  });
});
