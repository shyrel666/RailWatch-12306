import { Button, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Play, Square } from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { QueryResultRow } from "../types";
import type { CommandRunner } from "./componentTypes";
import { SectionTitle } from "./FormPrimitives";

export function MonitorPage({ busy, runCommand }: { busy: string | null; runCommand: CommandRunner }) {
  const config = useRailWatchStore((state) => state.config);
  const status = useRailWatchStore((state) => state.status);
  const results = useRailWatchStore((state) => state.results);
  const columns: ColumnsType<QueryResultRow & { key: string }> = [
    { title: "车次", dataIndex: "train", width: 120 },
    { title: "快照", render: () => <Tag color="blue">已解析</Tag>, width: 100 },
    { title: "结果", dataIndex: "raw" },
  ];
  return (
    <div className="monitor-stack monitor-workspace">
      <section className="content-band monitor-control-band">
        <div className="monitor-header">
          <SectionTitle eyebrow="Live Monitor" title="购票监控" />
          <div className="button-row">
            <Button
              disabled={!status.query_ready || status.monitoring}
              icon={<Play size={16} />}
              loading={busy === "startMonitor"}
              onClick={() => void runCommand("startMonitor", { config })}
              type="primary"
            >
              启动监控
            </Button>
            <Button
              danger
              disabled={!status.monitoring}
              icon={<Square size={16} />}
              loading={busy === "stopMonitor"}
              onClick={() => void runCommand("stopMonitor")}
            >
              停止监控
            </Button>
          </div>
        </div>
        <div className="inline-status">{status.summary}</div>
      </section>

      <section className="content-band">
        <SectionTitle title="查询结果" />
        <Table
          columns={columns}
          dataSource={results.map((row, index) => ({ ...row, key: `${row.train}-${index}` }))}
          locale={{ emptyText: "还没有查询结果" }}
          pagination={{ pageSize: 8, hideOnSinglePage: true }}
          size="middle"
        />
      </section>
    </div>
  );
}
