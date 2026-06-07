import { useCallback, useEffect, useMemo, useState } from "react";
import { App as AntApp, ConfigProvider, theme } from "antd";
import { DashboardPage } from "./components/DashboardPage";
import { EventPanel } from "./components/EventPanel";
import { MonitorPage } from "./components/MonitorPage";
import { SettingsPage } from "./components/SettingsPage";
import { ShellLayout } from "./components/Shell";
import { TripSetupPage } from "./components/TripSetupPage";
import { railwatchApi } from "./lib/railwatchApi";
import { railwatchStore } from "./store/railwatchStore";
import { useRailWatchStore } from "./store/useRailWatchStore";
import type {
  BridgeEvent,
  ConfirmationRequest,
  LogEntry,
  QueryResultRow,
  RailWatchConfig,
  RailWatchStatus,
  RuntimeInfo,
  TicketHit,
} from "./types";

function isConfirmation(value: unknown): value is ConfirmationRequest {
  return Boolean(value && typeof value === "object" && (value as ConfirmationRequest).requires_confirmation);
}

function isStatusPayload(value: unknown): value is RailWatchStatus {
  return Boolean(value && typeof value === "object" && "phase" in value && "monitoring" in value);
}

export function RailWatchApp() {
  const runtime = useRailWatchStore((state) => state.runtime);
  const status = useRailWatchStore((state) => state.status);
  const activePage = useRailWatchStore((state) => state.activePage);
  const eventPanelVisible = useRailWatchStore((state) => state.eventPanelVisible);
  const setActivePage = useRailWatchStore((state) => state.setActivePage);
  const setEventPanelVisible = useRailWatchStore((state) => state.setEventPanelVisible);
  const { modal, message, notification } = AntApp.useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [darkMode, setDarkMode] = useState(false);

  const applyEvent = useCallback(
    (event: BridgeEvent) => {
      const state = railwatchStore.getState();
      switch (event.event) {
        case "log":
          state.applyLog(event.payload as LogEntry);
          break;
        case "state":
          state.applyState(event.payload as RailWatchStatus);
          break;
        case "results":
          state.applyResults(event.payload as { rows: QueryResultRow[] });
          break;
        case "notify":
          state.applyNotify(event.payload as { title: string; message: string; hit?: TicketHit });
          notification.success({
            message: (event.payload as { title: string }).title,
            description: (event.payload as { message: string }).message,
            placement: "topRight",
          });
          break;
        case "logsCleared":
          state.clearLogs();
          break;
        default:
          break;
      }
    },
    [notification],
  );

  const confirm = useCallback(
    (title: string, content: string) =>
      new Promise<boolean>((resolve) => {
        modal.confirm({
          title,
          content,
          okText: "确认",
          cancelText: "取消",
          centered: true,
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      }),
    [modal],
  );

  const runCommand = useCallback(
    async <T,>(command: string, payload: Record<string, unknown> = {}, successText?: string): Promise<T | undefined> => {
      setBusy(command);
      try {
        const result = await railwatchApi.command<T | ConfirmationRequest>(command, payload);
        if (isConfirmation(result)) {
          const accepted = await confirm(result.title, result.message);
          if (!accepted) {
            return undefined;
          }
          const confirmedResult = await railwatchApi.command<T>(command, { ...payload, confirmed: true });
          if (isStatusPayload(confirmedResult)) {
            railwatchStore.getState().applyState(confirmedResult);
          }
          if (successText) {
            message.success(successText);
          }
          return confirmedResult;
        }
        if (isStatusPayload(result)) {
          railwatchStore.getState().applyState(result);
        }
        if (successText) {
          message.success(successText);
        }
        return result as T;
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
        return undefined;
      } finally {
        setBusy(null);
      }
    },
    [confirm, message],
  );

  useEffect(() => {
    const unsubscribe = railwatchApi.onEvent(applyEvent);
    void (async () => {
      const runtimeInfo = await runCommand<RuntimeInfo>("getRuntimeInfo");
      if (runtimeInfo) {
        railwatchStore.getState().applyRuntimeInfo(runtimeInfo);
      }
      const config = await runCommand<RailWatchConfig>("loadConfig");
      if (config) {
        railwatchStore.getState().setConfig(config);
      }
      const preferences = await runCommand<{ theme: "light" | "dark" }>("loadPreferences");
      setDarkMode(preferences?.theme === "dark");
    })();
    return unsubscribe;
  }, [applyEvent, runCommand]);

  const content = useMemo(() => {
    if (activePage === "行程设置") {
      return <TripSetupPage busy={busy} confirm={confirm} runCommand={runCommand} />;
    }
    if (activePage === "监控") {
      return <MonitorPage busy={busy} runCommand={runCommand} />;
    }
    if (activePage === "设置") {
      return <SettingsPage busy={busy} darkMode={darkMode} runCommand={runCommand} setDarkMode={setDarkMode} />;
    }
    return <DashboardPage />;
  }, [activePage, busy, confirm, darkMode, runCommand]);

  return (
    <ConfigProvider
      theme={{
        algorithm: darkMode ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: darkMode ? "#59d6b0" : "#0f8f62",
          colorBgBase: darkMode ? "#0d1117" : "#eef2f0",
          colorTextBase: darkMode ? "#eef4f1" : "#17201c",
          borderRadius: 8,
          fontFamily: '"Microsoft YaHei UI", "Noto Sans SC", "Segoe UI", sans-serif',
        },
        components: {
          Button: { controlHeight: 34, borderRadius: 8 },
          Input: { controlHeight: 34, borderRadius: 8 },
          Select: { controlHeight: 34, borderRadius: 8 },
          Table: { borderColor: darkMode ? "#25313d" : "#dce3df" },
        },
      }}
    >
      <ShellLayout
        activePage={activePage}
        darkMode={darkMode}
        eventPanel={
          eventPanelVisible ? <EventPanel runCommand={runCommand} onClose={() => setEventPanelVisible(false)} /> : null
        }
        eventPanelVisible={eventPanelVisible}
        runtime={runtime}
        status={status}
        onPageChange={setActivePage}
        onToggleEventPanel={() => setEventPanelVisible(!eventPanelVisible)}
      >
        {content}
      </ShellLayout>
    </ConfigProvider>
  );
}
