import { useClock } from "../lib/useClock";
import { officialReadTime } from "../lib/alternateOptions";
import type { AlternateReview } from "../types";

function PaymentCountdown({ deadline, observed }: { deadline: number; observed?: number }) {
  const remaining = deadline - useClock() / 1000;
  const seconds = Math.max(0, Math.ceil(remaining));
  const countdown = [Math.floor(seconds / 60), seconds % 60].map(value => String(value).padStart(2, "0")).join(":");
  return <div title={Number.isFinite(observed) ? `官网读取于 ${officialReadTime(observed)}` : undefined}>
    <dt>支付倒计时</dt>
    <dd className={remaining < 300 ? "is-urgent" : undefined}>
      {remaining <= 0 ? <span role="status">倒计时已到，请核对官方状态</span>
        : <span className="mono" role="timer">{countdown}</span>}
    </dd>
  </div>;
}

export function PaymentMeta({ review, pendingPayment = false }: { review?: AlternateReview; pendingPayment?: boolean }) {
  const deadline = review?.payment_deadline_at;
  const showCountdown = pendingPayment && typeof deadline === "number" && Number.isFinite(deadline);
  const price = review?.ticket_price;
  const hasPrice = typeof price === "string" && /^\d+(?:\.\d+)?$/.test(price);
  const seats = Array.isArray(review?.seat_assignments)
    ? review.seat_assignments.filter(seat => typeof seat === "string" && seat.trim())
    : [];
  if (!showCountdown && !hasPrice && !seats.length) return null;

  return <dl className="payment-meta" aria-label="官网支付与座次">
    {showCountdown ? <PaymentCountdown deadline={deadline} observed={review?.payment_countdown_observed_at} /> : null}
    {hasPrice ? <div><dt>票价</dt><dd className="mono">¥{price}</dd></div> : null}
    {seats.length ? <div><dt>已分配座次</dt><dd>
      <ul className="payment-seat-list">{seats.map((seat, index) => <li key={`${seat}-${index}`}>{seat}</li>)}</ul>
    </dd></div> : null}
  </dl>;
}
