import type { AlternateReview as Review, NewTrainWindow } from "../types";
import { canonicalDeadline, officialReadTime } from "../lib/alternateOptions";
import { useClock } from "../lib/useClock";

export function AlternateReview({ review, deadline, windows = [] }: {
  review?: Review; deadline?: string; windows?: NewTrainWindow[];
}) {
  const now = useClock();
  const rate = review?.success_rate;
  const hasRate = typeof rate === "number" && Number.isFinite(rate) && rate >= 0 && rate <= 100;
  const stale = review?.success_rate_status === "stale" ||
    (hasRate && (!review?.success_rate_observed_at || now / 1000 - review.success_rate_observed_at > 300));
  // Values the official site has not provided stay visible but recede, so known facts stand out.
  return <dl className="alternate-review" aria-label="候补条件与官网数据">
    <div><dt>截止兑现</dt><dd className={deadline ? undefined : "is-empty"}>{deadline ? canonicalDeadline(deadline) : "未记录"}</dd></div>
    <div><dt>新增列车</dt><dd>{windows.length
      ? windows.map(w => `${w.date.slice(5)} ${w.start_hour}–${w.end_hour}点`).join("、") : "不接受"}</dd></div>
    <div title={hasRate ? `官网读取于 ${officialReadTime(review?.success_rate_observed_at)}，为历史估计，仅供参考` : undefined}>
      <dt>预估成功率</dt>
      <dd className={hasRate ? stale ? undefined : "alternate-rate" : "is-empty"}>{hasRate ? `${rate}%${stale ? "（已失效，待重新读取）" : ""}` :
        review?.success_rate_status === "loading" ? "官网计算中" : "官网暂未提供"}</dd>
    </div>
    <div title={review?.amount_observed_at ? `官网核对于 ${officialReadTime(review.amount_observed_at)}` : undefined}>
      <dt>预付款</dt><dd className={review?.prepay_amount != null ? "alternate-amount" : "is-empty"}>
        {review?.prepay_amount != null ? `${review.prepay_amount} 元` : "官网暂未提供"}</dd>
    </div>
    {review?.standing ? <div><dt>接受无座</dt><dd>{review.standing}{review.quiet_car ? " · 可能含静音车厢" : ""}</dd></div> : null}
  </dl>;
}
