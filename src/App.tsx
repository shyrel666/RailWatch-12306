import { useCallback, useEffect, useMemo, useState } from "react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useThemePreference } from "./lib/useThemePreference";
import { ThemeContext } from "./components/ThemeControl";
import { AboutPage } from "./components/AboutPage";
import { DashboardPage } from "./components/DashboardPage";
import { EventPanel } from "./components/EventPanel";
import { MonitorPage } from "./components/MonitorPage";
import { SettingsPage } from "./components/SettingsPage";
import { ShellLayout } from "./components/Shell";
import { TripSetupPage } from "./components/TripSetupPage";
import { railwatchApi } from "./lib/railwatchApi";
import { exportEventLog } from "./lib/exportEventLog";
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
  return Boolean(
    value &&
      typeof value === "object" &&
      (value as ConfirmationRequest).requires_confirmation,
  );
}

function isStatusPayload(value: unknown): value is RailWatchStatus {
  return Boolean(
    value &&
      typeof value === "object" &&
      "phase" in value &&
      "monitoring" in value,
  );
}

export function RailWatchApp() {
  const appearance = useThemePreference();
  return (
    <ConfigProvider locale={zhCN} theme={appearance.design.config}>
      <AntApp>
        <RailWatchAppContent appearance={appearance} />
      </AntApp>
    </ConfigProvider>
  );
}

type RailWatchAppContentProps = {
  appearance: ReturnType<typeof useThemePreference>;
};

function RailWatchAppContent({ appearance }: RailWatchAppContentProps) {
  const runtime = useRailWatchStore((state) => state.runtime);
  const status = useRailWatchStore((state) => state.status);
  const activePage = useRailWatchStore((state) => state.activePage);
  const eventPanelVisible = useRailWatchStore(
    (state) => state.eventPanelVisible,
  );
  const setActivePage = useRailWatchStore((state) => state.setActivePage);
  const setEventPanelVisible = useRailWatchStore(
    (state) => state.setEventPanelVisible,
  );
  const { modal, message, notification } = AntApp.useApp();
  const [busy, setBusy] = useState<string | null>(null);

  const applyEvent = useCallback(
    (event: BridgeEvent) => {
      const state = railwatchStore.getState();
      const owner = (event.payload as { run_id?: string })?.run_id;
      if (
        event.event !== "state" &&
        owner &&
        owner !== state.status.task?.run_id
      )
        return;
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
          const notifyPayload = event.payload as {
            title: string;
            message: string;
            hit?: TicketHit;
            priority?: string;
          };
          state.applyNotify(notifyPayload);
          const notifyApi =
            notifyPayload.priority === "urgent"
              ? notification.warning
              : notification.success;
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
          state.applyState({
            ...state.status,
            monitoring: false,
            task: undefined,
            phase: "error",
            status_message: "运行时中断，请核对原订单",
            error_message: "运行时中断",
          });
          notification.error({
            message: "Python 运行时异常",
            description:
              (event.payload as { message?: string }).message || "请稍后重试。",
            placement: "topRight",
            duration: 0,
          });
          break;
        case "runtimeRestarted":
          void railwatchApi
            .command<RuntimeInfo>("getRuntimeInfo")
            .then((info) => railwatchStore.getState().applyRuntimeInfo(info))
            .catch(() => undefined);
          notification.info({
            message: "Python 运行时已恢复",
            description: (event.payload as { message?: string }).message || "",
            placement: "topRight",
          });
          break;
        case "logsCleared":
          state.clearLogs();
          break;
        case "orderDismissed":
          state.clearHumanAction();
          notification.destroy("railwatch-human-action");
          notification.destroy("railwatch-notify");
          void railwatchApi.stopUrgentAlert();
          break;
        case "labels":
          state.applyRuntimeLabels(
            event.payload as {
              chromedriver_path?: string;
              chrome_version?: string;
            },
          );
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
    async <T,>(
      command: string,
      payload: Record<string, unknown> = {},
      successText?: string,
    ): Promise<T | undefined> => {
      setBusy(command);
      try {
        const result = await railwatchApi.command<
          T | ConfirmationRequest | { cancelled?: boolean }
        >(command, payload);
        if (
          result &&
          typeof result === "object" &&
          "cancelled" in result &&
          result.cancelled
        ) {
          return undefined;
        }
        if (isConfirmation(result)) {
          const accepted = await confirm(result.title, result.message);
          if (!accepted) {
            return undefined;
          }
          const confirmedResult = await railwatchApi.command<T>(command, {
            ...payload,
            confirmed: true,
          });
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

  const saveTheme = async (
    mode: Parameters<typeof appearance.saveTheme>[0],
  ) => {
    try {
      await appearance.saveTheme(mode);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "主题保存失败，请重试。",
      );
    }
  };

  const exportLog = useCallback(async () => {
    const defaultPath = runtime.data_dir
      ? `${runtime.data_dir}/railwatch-events.txt`
      : undefined;
    try {
      await exportEventLog(defaultPath, runCommand);
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [message, runCommand, runtime.data_dir]);

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
      return (
        <TripSetupPage busy={busy} confirm={confirm} runCommand={runCommand} />
      );
    }
    if (activePage === "购票监控") {
      return <MonitorPage busy={busy} runCommand={runCommand} />;
    }
    if (activePage === "系统设置") {
      return <SettingsPage busy={busy} runCommand={runCommand} />;
    }
    if (activePage === "关于") {
      return <AboutPage />;
    }
    return <DashboardPage />;
  }, [activePage, busy, confirm, runCommand]);

  return (
    <ThemeContext.Provider
      value={{
        mode: appearance.mode,
        disabled: appearance.disabled,
        onChange: (mode) => void saveTheme(mode),
      }}
    >
      <ShellLayout
        activePage={activePage}
        darkMode={appearance.darkMode}
        eventPanel={
          <EventPanel
            runCommand={runCommand}
            onExport={() => void exportLog()}
            onClose={() => setEventPanelVisible(false)}
          />
        }
        eventPanelVisible={eventPanelVisible}
        runtime={runtime}
        status={status}
        onPageChange={setActivePage}
        onExportLog={() => void exportLog()}
        onToggleEventPanel={() => setEventPanelVisible(!eventPanelVisible)}
      >
        {content}
      </ShellLayout>
    </ThemeContext.Provider>
  );
}
