import type { ReactNode } from "react";
import { ConfigProvider, Tooltip } from "antd";
import { getBoardTheme } from "../lib/theme";

export type BoardTone = "go" | "wait" | "stop" | "idle";
export type BoardFact = { label: string; value: ReactNode };

// The board keeps a dark, station-display look in both themes, so Ant Design
// controls inside it always use the dark algorithm.
export function DepartureBoard({
  label,
  id,
  className,
  kicker,
  tone,
  live = false,
  status,
  message,
  from,
  to,
  fromNote,
  toNote,
  trackLabel,
  display,
  facts,
  actions,
  children,
}: {
  label: string;
  id?: string;
  className?: string;
  kicker?: ReactNode;
  tone: BoardTone;
  live?: boolean;
  status: ReactNode;
  message?: ReactNode;
  from: string;
  to: string;
  fromNote?: ReactNode;
  toNote?: ReactNode;
  trackLabel?: ReactNode;
  display?: {
    caption: ReactNode;
    value: ReactNode;
    note?: ReactNode;
    tone?: "led" | "go" | "stop" | "dim";
  };
  facts: BoardFact[];
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <ConfigProvider theme={getBoardTheme()}>
      <section
        className={["departure-board", className].filter(Boolean).join(" ")}
        aria-label={label}
        id={id}
        tabIndex={id ? -1 : undefined}
      >
        <div className="board-main">
          <div className="board-trip">
            <div className="board-kicker">
              {kicker ? <span className="board-kicker-label">{kicker}</span> : null}
              <span className={"board-pill " + tone}>
                <i
                  className={"lamp " + tone + (live ? " live" : "")}
                  aria-hidden="true"
                />
                {status}
              </span>
            </div>
            {message ? <div className="board-message">{message}</div> : null}
            <div className="board-route">
              <div className="board-station">
                <strong>{from}</strong>
                {fromNote ? <small>{fromNote}</small> : null}
              </div>
              <div className="board-track">
                <span className="sr-only">至</span>
                {trackLabel ? <em>{trackLabel}</em> : null}
              </div>
              <div className="board-station">
                <strong>{to}</strong>
                {toNote ? <small>{toNote}</small> : null}
              </div>
            </div>
            {children}
          </div>
          {display ? (
            <div className="board-display">
              <span>{display.caption}</span>
              <strong className={"board-led " + (display.tone ?? "led")}>
                {display.value}
              </strong>
              {display.note ? <small>{display.note}</small> : null}
            </div>
          ) : null}
        </div>
        <div className="board-foot">
          <dl className="board-facts">
            {facts.map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            ))}
          </dl>
          {actions ? <div className="board-actions">{actions}</div> : null}
        </div>
      </section>
    </ConfigProvider>
  );
}

export function TrainCodes({
  codes,
  highlighted = [],
  limit = 4,
}: {
  codes: string[];
  highlighted?: string[];
  limit?: number;
}) {
  if (!codes.length) return <>不限</>;
  const shown = codes.slice(0, limit);
  const rest = codes.length - shown.length;
  return (
    <span className="board-codes">
      {shown.map((code) => (
        <b
          className={"board-code" + (highlighted.includes(code) ? " hit" : "")}
          key={code}
        >
          {code}
        </b>
      ))}
      {rest > 0 ? (
        <Tooltip title={codes.join("、")}>
          <span className="board-code more" tabIndex={0}>
            +{rest}
          </span>
        </Tooltip>
      ) : null}
    </span>
  );
}
