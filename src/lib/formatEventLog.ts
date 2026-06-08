import type { LogEntry } from "../types";

export type EventTone = "info" | "success" | "warn" | "error";

export type PresentedEvent = LogEntry & {
  tone: EventTone;
  label: string;
  title: string;
  detail: string | null;
};

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

function summarizeMergedDetails(details: string[]) {
  if (details.length === 0) {
    return null;
  }
  return details[0];
}

export function countEventsByFilter(logs: LogEntry[], filter: string) {
  const levels = filterLevels[filter];
  if (!levels) {
    return logs.length;
  }
  return logs.filter((entry) => levels.includes(entry.level)).length;
}

export function presentEventLogs(logs: LogEntry[], filter: string): PresentedEvent[] {
  const levels = filterLevels[filter];
  const filtered = levels ? logs.filter((entry) => levels.includes(entry.level)) : logs;
  const presented: PresentedEvent[] = [];

  for (const entry of filtered) {
    const meta = levelMeta[entry.level] ?? levelMeta.INFO;
    const clean = stripEmoji(entry.message);

    if (isQueryNoise(clean)) {
      continue;
    }

    if (isTechnicalDetail(clean) && presented.length > 0) {
      const previous = presented[presented.length - 1];
      const merged = previous.detail ? `${previous.detail} · ${clean}` : clean;
      previous.detail = summarizeMergedDetails(merged.split(" · ")) ?? merged;
      continue;
    }

    const { title, detail } = splitMessage(entry.message);
    presented.push({
      ...entry,
      tone: meta.tone,
      label: meta.label,
      title,
      detail,
    });
  }

  return presented.reverse();
}
