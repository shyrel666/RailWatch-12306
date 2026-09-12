import { describe, expect, test } from "vitest";
import { defaultConfig } from "../store/railwatchStore";
import { delayPreview, isStrategyCustomized, modeDefaults, priorityDefaults, queryPriority } from "./queryStrategy";

describe("query strategies", () => {
  test("speed and reliability retain adaptive backoff and session checks", () => {
    for (const priority of ["speed", "reliability"] as const) {
      const config = { ...defaultConfig, ...priorityDefaults(priority) };
      expect(config.smart_rate && config.keep_alive).toBe(true);
      expect(isStrategyCustomized(config)).toBe(false);
      expect(queryPriority(config)).toBe(priority);
      expect(isStrategyCustomized({ ...config, query_timeout: 51 })).toBe(true);
      expect(config.auto_submit || config.auto_alternate).toBe(false);
    }
  });
  test.each([
    ["fast", "3.0 ~ 3.6"], ["balanced", "4.0 ~ 6.0"], ["conservative", "5.0 ~ 7.2"],
  ] as const)("%s shows the actual bounded initial jitter", (mode, label) => {
    expect(delayPreview({ ...defaultConfig, ...modeDefaults(mode) }).label).toBe(label);
  });
  test("manual intervals and disabled adaptive polling show their actual ranges", () => {
    expect(delayPreview({ ...defaultConfig, interval: 60 }).label).toBe("48.0 ~ 60.0");
    expect(delayPreview({ ...defaultConfig, interval: 1, smart_rate: false }).label).toBe("0.7 ~ 1.3");
    expect(delayPreview({ ...defaultConfig, interval: 1, smart_rate: true }).label).toBe("5.0 ~ 6.0");
  });
});
