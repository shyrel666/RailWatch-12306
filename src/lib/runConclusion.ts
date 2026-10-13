export type ConclusionTone = "go" | "wait" | "stop" | "info" | "neutral";

// Conclusions come from railwatch_run_review.run_conclusion.
export function conclusionTone(conclusion: string): ConclusionTone {
  if (conclusion === "进行中") return "info";
  if (/购票成功|候补已生效|已命中/.test(conclusion)) return "go";
  if (/待支付|需要核验|结果待核对|人工处理/.test(conclusion)) return "wait";
  if (/取消|过期|失败|异常|未成功|售罄/.test(conclusion)) return "stop";
  return "neutral";
}
