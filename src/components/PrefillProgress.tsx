import type { PrefillProgress as Progress } from "../types";
import { taskLabels } from "../lib/taskDisplay";

export function prefillStageLabel(item: Progress["candidates"][number]) {
  if (item.status === "armed") return "预填已就绪";
  if (item.status === "submitting") return item.confirmed ? "已确认提交，等待结果" : "正在打开购票入口";
  return taskLabels[item.status] || "结果待核对";
}

export function PrefillProgress({ progress }: { progress: Progress }) {
  return <div className="prefill-progress">
    <p className="query-context">{progress.fallback
      ? "预填流程已转入常规余票查询，已执行的预填记录保留在下方。"
      : "通过官方预填直接购票，无需轮询余票。入口可用不代表购票成功，结果以官方订单为准。"}</p>
    <div className="query-table-scroll" tabIndex={0} aria-label="官方预填进度">
      <table className="query-table">
        <thead><tr><th scope="col">车次／日期</th><th scope="col">实际区间</th><th scope="col">席别</th><th scope="col">进度</th></tr></thead>
        <tbody>{progress.candidates.map((item, index) => <tr key={`${item.train}-${item.seat}-${index}`}>
          <th scope="row">{item.train}<br /><small>{item.date}</small></th>
          <td>{item.from} → {item.to}</td><td>{item.seat}</td>
          <td>{prefillStageLabel(item)}{item.bound ? <small>已绑定官方订单</small> : null}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </div>;
}
