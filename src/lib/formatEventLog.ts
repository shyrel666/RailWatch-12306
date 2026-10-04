import type { LogEntry } from "../types";

export function formatEventTime(value: string) {
  // Legacy logs contain only a clock time; preserve those and unknown formats.
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/);
  if (!match) return value;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  // Date.parse rolls overflowing fields forward (02-30 becomes 03-02).
  const [, date, clock, sign, hours, minutes] = match;
  const offset = sign ? (sign === "-" ? -1 : 1) * (Number(hours) * 60 + Number(minutes)) : 0;
  if (new Date(timestamp + offset * 60 * 1000).toISOString().slice(0, 19) !== `${date}T${clock}`) return value;

  // Beijing is UTC+8, regardless of the computer's local timezone.
  return new Date(timestamp + 8 * 60 * 60 * 1000)
    .toISOString().slice(0, 19).replace("T", " ");
}

export type EventTone = "info" | "success" | "warn" | "error";

export type PresentedEvent = LogEntry & {
  tone: EventTone;
  label: string;
  title: string;
  detail: string | null;
  category: string;
  /** Consecutive identical log lines collapse into one entry. */
  repeat: number;
  firstTime: string;
};

// Ordered: the first match wins, so specific topics come before broad ones.
const categories: Array<[RegExp, string]> = [
  [/订单|候补|支付|提交|核验|乘客|兑现/, "订单"],
  [/通知|推送|Server酱|邮件|企业微信|钥匙串/, "通知"],
  [/登录|会话|保活|RAIL_DEVICEID|设备标识/, "登录"],
  [/站点编码|站码|车站/, "站码"],
  [/彩排/, "彩排"],
  [/定时|起售|开售|冲刺/, "定时"],
  [/监控|命中|目标车次|目标席别|自动提交|自动候补/, "监控"],
  [/查询|余票|车次|刷新/, "查询"],
  [/Chrome|浏览器|[Dd]river|Python|Selenium|环境|平台|用户数据目录|设备指纹/, "环境"],
  [/设置|配置|偏好|路线|收藏/, "设置"],
  [/更新|版本|安装/, "更新"],
  [/导出|日志|事件/, "日志"],
];

export function eventCategory(message: string) {
  return categories.find(([pattern]) => pattern.test(message))?.[1] ?? "系统";
}

const filterLevels: Record<string, string[] | undefined> = {
  全部: undefined,
  信息: ["INFO", "SUCCESS"],
  警告: ["WARN"],
  错误: ["ERROR"],
};

const levelMeta: Record<string, { label: string; tone: EventTone }> = {
  ERROR: { label: "错误", tone: "error" },
  WARN: { label: "警告", tone: "warn" },
  SUCCESS: { label: "信息", tone: "success" },
  INFO: { label: "信息", tone: "info" },
};

const emojiPrefix = /^[\s\u2600-\u27BF\u{1F300}-\u{1FAFF}]+\s*/u;

const technicalDetailPatterns = [
  /^Python \d/,
  /^平台 /,
  /^Chrome 版本/,
  /^ChromeDriver 已找到/,
  /^未找到 ChromeDriver/,
  /^使用本地 ChromeDriver/,
  /^undetected-chromedriver 版本/,
  /^用户数据目录/,
  /^已加载设备指纹/,
  /^已生成并保存新的设备指纹/,
  /^使用 undetected-chromedriver 模式/,
  /^正在初始化 undetected-chromedriver/,
  /^已启用反检测浏览器配置/,
  /^使用自动下载模式/,
  /^提示: /,
];

const queryRowPattern = /^[GDCKTZS]\d+[A-Z0-9]*\s+\|/;
const queryStepPatterns = [
  /^正在打开 12306/,
  /^等待查询输入框/,
  /^自动填参/,
  /^自动点击【查询】/,
  /^等待查询结果/,
];

const titleOverrides: Array<{ pattern: RegExp; title: string; detail?: (message: string) => string | null }> = [
  {
    pattern: /^解析到 \d+ 条车次结果/,
    title: "查询完成",
    detail: (message) => {
      const match = message.match(/解析到 (\d+) 条车次结果/);
      return match ? `共 ${match[1]} 条车次结果` : message;
    },
  },
  {
    pattern: /^正在检查 Python/,
    title: "环境检查",
    detail: (message) => message,
  },
  {
    pattern: /^undetected-chromedriver 初始化成功/,
    title: "环境检查通过",
    detail: () => "浏览器驱动已就绪",
  },
  {
    pattern: /^标准 selenium WebDriver 初始化成功/,
    title: "环境检查通过",
    detail: () => "浏览器驱动已就绪",
  },
  {
    pattern: /^登录页面已打开/,
    title: "打开登录",
    detail: (message) => message,
  },
  {
    pattern: /^ChromeDriver 下载完成/,
    title: "驱动更新",
    detail: (message) => message.replace(/^ChromeDriver 下载完成[，,]?/, "").trim() || "可以运行环境检查",
  },
];

function stripEmoji(message: string) {
  return message.replace(emojiPrefix, "").trim();
}

function splitMessage(message: string) {
  const clean = stripEmoji(message);

  for (const override of titleOverrides) {
    if (override.pattern.test(clean)) {
      return {
        title: override.title,
        detail: override.detail?.(clean) ?? clean,
      };
    }
  }

  const colonIndex = clean.search(/[：:]/);
  if (colonIndex >= 0) {
    return {
      title: clean.slice(0, colonIndex).trim(),
      detail: clean.slice(colonIndex + 1).trim() || null,
    };
  }

  return { title: clean, detail: null };
}

function isTechnicalDetail(message: string) {
  const clean = stripEmoji(message);
  return technicalDetailPatterns.some((pattern) => pattern.test(clean));
}

function isQueryNoise(message: string) {
  const clean = stripEmoji(message);
  if (queryRowPattern.test(clean)) {
    return true;
  }
  return queryStepPatterns.some((pattern) => pattern.test(clean));
}

export function countEventsByFilter(logs: LogEntry[], filter: string) {
  return presentEventLogs(logs, filter).length;
}

export function summarizeEventLogs(logs: LogEntry[], verbose = false) {
  const entries = presentEventLogs(logs, "全部", verbose);
  const counts: Record<string, number> = { 全部: entries.length, 信息: 0, 警告: 0, 错误: 0 };
  for (const entry of entries) {
    if (entry.level === "INFO" || entry.level === "SUCCESS") counts.信息++;
    else if (entry.level === "WARN") counts.警告++;
    else if (entry.level === "ERROR") counts.错误++;
  }
  return { entries, counts };
}

export function filterPresentedEvents(entries: PresentedEvent[], filter: string) {
  const levels = filterLevels[filter];
  return levels ? entries.filter(entry => levels.includes(entry.level)) : entries;
}

const entryIds = new WeakMap<object, number>();
let fallbackEntryId = -1;

/**
 * Turns raw log lines into feed entries. By default query steps and result rows
 * are hidden and environment details fold into their check; `verbose` keeps
 * every line as its own entry.
 */
export function presentEventLogs(logs: LogEntry[], filter: string, verbose = false): PresentedEvent[] {
  const levels = filterLevels[filter];
  const presented: PresentedEvent[] = [];

  for (const entry of logs) {
    const meta = levelMeta[entry.level] ?? levelMeta.INFO;
    const clean = stripEmoji(entry.message);
    const informational = entry.level === "INFO" || entry.level === "SUCCESS";

    if (!verbose && informational && isQueryNoise(clean)) {
      continue;
    }

    const previous = presented[presented.length - 1];
    if (previous && previous.level === entry.level && previous.message === entry.message && previous.run_id === entry.run_id) {
      previous.repeat += 1;
      previous.time = entry.time;
      continue;
    }
    if (
      !verbose && informational && isTechnicalDetail(clean) && previous &&
      (previous.level === "INFO" || previous.level === "SUCCESS") &&
      previous.run_id === entry.run_id &&
      (previous.title === "环境检查" || previous.title === "环境检查通过" || isTechnicalDetail(previous.message))
    ) {
      previous.detail = previous.detail ? `${previous.detail} · ${clean}` : clean;
      continue;
    }

    const { title, detail } = splitMessage(entry.message);
    if (entry.id === undefined && !entryIds.has(entry)) entryIds.set(entry, fallbackEntryId--);
    presented.push({
      ...entry,
      id: entry.id ?? entryIds.get(entry),
      tone: meta.tone,
      label: meta.label,
      title,
      detail,
      category: eventCategory(clean),
      repeat: 1,
      firstTime: entry.time,
    });
  }

  return (levels ? presented.filter((entry) => levels.includes(entry.level)) : presented).reverse();
}
