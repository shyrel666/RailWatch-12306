export function formatAppVersion(version: string) {
  const trimmed = version.trim();
  if (!trimmed || trimmed === "未知") {
    return "未知";
  }
  return trimmed.startsWith("v") ? trimmed : `v${trimmed}`;
}

export function formatDataDirPath(path: string) {
  const trimmed = path.trim();
  if (!trimmed) {
    return "正在加载...";
  }
  return trimmed.replace(/([/\\])/g, "$1\u200b");
}

export function formatDataDirFreeSpace(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "未知";
  }

  const gb = bytes / 1024 ** 3;
  if (gb >= 1) {
    return `${gb.toFixed(1)} GB`;
  }

  const mb = bytes / 1024 ** 2;
  return `${Math.max(mb, 0.1).toFixed(0)} MB`;
}

const phaseLabels: Record<string, string> = {
  idle: "就绪",
  environment: "环境就绪",
  login: "已登录",
  query_ready: "查询就绪",
  monitoring: "监控中",
  hit: "有命中",
  alternate: "候补中",
  error: "需处理",
};

export function formatRuntimePhaseLabel(statusMessage: string, phase: string) {
  if (phase === "error") {
    return "需处理";
  }
  if (phase === "monitoring") {
    return "监控中";
  }
  if (phase === "query_ready" || /^已解析\s+\d+\s+行查询结果/.test(statusMessage.trim())) {
    return "查询就绪";
  }
  if (phase in phaseLabels) {
    return phaseLabels[phase];
  }
  const trimmed = statusMessage.trim();
  return trimmed.length <= 8 ? trimmed : "就绪";
}

export function formatRuntimePhaseDetail(statusMessage: string, phase: string) {
  const trimmed = statusMessage.trim();
  const parsedRows = trimmed.match(/^已解析\s+(\d+)\s+行查询结果$/);
  if (parsedRows) {
    return `已解析 ${parsedRows[1]} 行查询结果`;
  }
  const label = formatRuntimePhaseLabel(trimmed, phase);
  if (trimmed && trimmed !== label) {
    return trimmed;
  }
  return null;
}

export function formatRuntimePhase(statusMessage: string, phase: string) {
  return formatRuntimePhaseDetail(statusMessage, phase) ?? formatRuntimePhaseLabel(statusMessage, phase);
}

export function formatStatusClock(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  const year = date.getFullYear();
  const month = pad(date.getMonth() + 1);
  const day = pad(date.getDate());
  const hours = pad(date.getHours());
  const minutes = pad(date.getMinutes());
  const seconds = pad(date.getSeconds());
  const weekdayLabels = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

  return {
    date: `${year}-${month}-${day}`,
    yearMonth: `${year}-${month}`,
    day,
    weekday: weekdayLabels[date.getDay()],
    hours,
    minutes,
    seconds,
    time: `${hours}:${minutes}:${seconds}`,
  };
}

export function getRuntimePhaseTone(phase: string) {
  if (phase === "error") {
    return "error";
  }
  if (phase === "monitoring" || phase === "hit" || phase === "alternate") {
    return "active";
  }
  return "ready";
}
