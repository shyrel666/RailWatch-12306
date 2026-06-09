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
  HumanActionPayload,
  LogEntry,
  MonitorTickPayload,
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
  const [darkMode, setDarkMode] = useState(true);
  const runtimeTheme = useMemo(
    () => ({
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
    }),
    [darkMode],
  );

  return (
    <ConfigProvider theme={runtimeTheme}>
      <AntApp>
        <RailWatchAppContent darkMode={darkMode} setDarkMode={setDarkMode} />
      </AntApp>
    </ConfigProvider>
  );
}

type RailWatchAppContentProps = {
  darkMode: boolean;
  setDarkMode: (darkMode: boolean) => void;
};

function RailWatchAppContent({ darkMode, setDarkMode }: RailWatchAppContentProps) {
  const runtime = useRailWatchStore((state) => state.runtime);
  const status = useRailWatchStore((state) => state.status);
  const activePage = useRailWatchStore((state) => state.activePage);
  const eventPanelVisible = useRailWatchStore((state) => state.eventPanelVisible);
  const setActivePage = useRailWatchStore((state) => state.setActivePage);
  const setEventPanelVisible = useRailWatchStore((state) => state.setEventPanelVisible);
  const { modal, message, notification } = AntApp.useApp();
  const [busy, setBusy] = useState<string | null>(null);

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
        case "monitorTick":
          state.applyMonitorTick(event.payload as MonitorTickPayload);
          break;
        case "humanAction": {
          const human = event.payload as HumanActionPayload;
          state.applyHumanAction(human);
          notification.warning({
            key: "railwatch-human-action",
            message: human.title,
            description: human.message,
            placement: "topRight",
            duration: 0,
            onClose: () => railwatchApi.stopUrgentAlert(),
          });
          break;
        }
        case "notify": {
          const notifyPayload = event.payload as { title: string; message: string; hit?: TicketHit; priority?: string };
          state.applyNotify(notifyPayload);
          const notifyApi =
            notifyPayload.priority === "urgent" ? notification.warning : notification.success;
          notifyApi({
            key: "railwatch-notify",
            message: notifyPayload.title,
            description: notifyPayload.message,
            placement: "topRight",
            duration: notifyPayload.priority === "urgent" ? 0 : 4.5,
            onClose:
              notifyPayload.priority === "urgent"
                ? () => railwatchApi.stopUrgentAlert()
                : undefined,
          });
          break;
        }
        case "runtimeError":
        case "runtimeExit":
          notification.error({
            message: "Python 运行时异常",
            description: (event.payload as { message?: string }).message || "请稍后重试。",
            placement: "topRight",
            duration: 0,
          });
          break;
        case "runtimeRestarted":
          notification.info({
            message: "Python 运行时已恢复",
            description: (event.payload as { message?: string }).message || "",
            placement: "topRight",
          });
          break;
        case "logsCleared":
          state.clearLogs();
          break;
        case "labels":
          state.applyRuntimeLabels(event.payload as { chromedriver_path?: string; chrome_version?: string });
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
        const result = await railwatchApi.command<T | ConfirmationRequest | { cancelled?: boolean }>(command, payload);
        if (result && typeof result === "object" && "cancelled" in result && result.cancelled) {
          return undefined;
        }
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

  const saveTheme = useCallback(
    async (nextDarkMode: boolean) => {
      if (nextDarkMode === darkMode) {
        return;
      }
      setDarkMode(nextDarkMode);
      await runCommand("savePreferences", { theme: nextDarkMode ? "dark" : "light" });
    },
    [darkMode, runCommand, setDarkMode],
  );

  const exportLog = useCallback(async () => {
    const defaultPath = runtime.data_dir ? `${runtime.data_dir}/railwatch-events.txt` : undefined;
    const path = await railwatchApi.showSaveDialog(defaultPath);
    if (path) {
      await runCommand("exportLog", { path }, "事件已导出");
    }
  }, [runCommand, runtime.data_dir]);

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
      if (preferences?.theme) {
        setDarkMode(preferences.theme === "dark");
      }
    })();

    const refreshRuntime = window.setInterval(() => {
      void railwatchApi
        .command<RuntimeInfo>("getRuntimeInfo")
        .then((runtimeInfo) => {
          if (runtimeInfo) {
            railwatchStore.getState().applyRuntimeInfo(runtimeInfo);
          }
        })
        .catch(() => undefined);
    }, 30000);

    return () => {
      window.clearInterval(refreshRuntime);
      unsubscribe();
    };
  }, [applyEvent, runCommand]);

  const content = useMemo(() => {
    if (activePage === "行程设置") {
      return <TripSetupPage busy={busy} confirm={confirm} runCommand={runCommand} />;
    }
    if (activePage === "购票监控") {
      return <MonitorPage busy={busy} runCommand={runCommand} />;
    }
    if (activePage === "系统设置") {
      return <SettingsPage busy={busy} runCommand={runCommand} />;
    }
    return <DashboardPage />;
  }, [activePage, busy, confirm, runCommand]);

  return (
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
      onExportLog={() => void exportLog()}
      onThemeChange={saveTheme}
      onToggleEventPanel={() => setEventPanelVisible(!eventPanelVisible)}
    >
      {content}
    </ShellLayout>
  );
}
