import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { CircleHelp, Info, TriangleAlert } from "lucide-react";
import { useExportLogDialog } from "./components/ExportLogDialog";
import { useThemePreference } from "./lib/useThemePreference";
import { ThemeContext } from "./components/ThemeControl";
import { AboutPage } from "./components/AboutPage";
import { DashboardPage } from "./components/DashboardPage";
import { EventPanel } from "./components/EventPanel";
import { MonitorPage } from "./components/MonitorPage";
import { OrderCenterPage } from "./components/OrderCenterPage";
import { SettingsPage } from "./components/SettingsPage";
import { ShellLayout } from "./components/Shell";
import { TripSetupPage } from "./components/TripSetupPage";
import { railwatchApi } from "./lib/railwatchApi";
import { exportEventLog } from "./lib/exportEventLog";
import {
  useConfirmationBridge,
  useUpdateReadyPrompt,
  type ThemedDialog,
} from "./lib/useThemedDialogs";
import { railwatchStore, tripFingerprint } from "./store/railwatchStore";
import { useRailWatchStore } from "./store/useRailWatchStore";
import type {
  BridgeEvent,
  ConfirmationRequest,
  HumanActionPayload,
  LogEntry,
  MonitorTickPayload,
  QueryResultRow,
  RailWatchConfig,
  RailWatchPreferences,
  RailWatchStatus,
  RuntimeInfo,
  TicketHit,
  TripDraft,
  TripState,
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
  const { choosePath, dialog: exportDialog } = useExportLogDialog();
  const exportingRef = useRef(false);
  const [busy, setBusy] = useState<string | null>(null);
  const editRevision = useRailWatchStore(state => state.editRevision);
  const tripInitialized = useRailWatchStore(state => state.tripInitialized);
  const savedConfig = useRailWatchStore(state => state.savedConfig);
  const draftRevisionBase = useRef(0);
  const draftWriteChain = useRef<Promise<void>>(Promise.resolve());
  const clearingDataRef = useRef(false);
  const tripLoadRef = useRef<Promise<void> | null>(null);
  const loadTripRef = useRef<() => Promise<void>>(async () => undefined);

  useEffect(() => {
    let alive = true;
    void railwatchApi.command<RailWatchPreferences>("loadPreferences")
      .then(result => { if (alive) railwatchStore.getState().setRehearsalEnabled(result.auto_rehearsal === true); }).catch(() => undefined);
    void railwatchApi.command<{ items: import("./lib/rehearsal").RehearsalReport[] }>("rehearsalHistory")
      .then(result => { if (result.items[0]) railwatchStore.getState().loadRehearsalHistory(result.items[0]); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);

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
        case "rehearsalStarted":
          state.applyRehearsalStarted(event.payload as import("./lib/rehearsal").RehearsalStarted); break;
        case "rehearsalStep":
          state.applyRehearsalStep(event.payload as { rehearsal_id: string; check: import("./lib/rehearsal").RehearsalCheck }); break;
        case "rehearsalFinished":
          state.applyRehearsalFinished(event.payload as { report: import("./lib/rehearsal").RehearsalReport }); break;
        case "queryStarted":
          state.applyQueryStarted(event.payload as import("./types").QueryAttempt);
          break;
        case "log":
          state.applyLog(event.payload as LogEntry);
          break;
        case "state":
          state.applyState(event.payload as RailWatchStatus);
          if (state.lastHumanAction && !railwatchStore.getState().lastHumanAction) {
            notification.destroy("railwatch-human-action");
          }
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
        case "protocolError":
          notification.warning({ message: "请求格式错误", description: "已忽略无效请求，当前任务继续运行。" });
          break;
        case "runtimeError":
        case "runtimeExit":
        case "runtimeUnavailable":
          state.resetRehearsalProgress();
          state.applyState({
            ...state.status,
            monitoring: false,
            task: undefined,
            phase: "error",
            status_message: "运行时中断，请核对原订单",
            error_message: "运行时中断",
          });
          notification.error({
            key: "runtime-state",
            message: "Python 运行时异常",
            description: <span>{(event.payload as { message?: string }).message || "请稍后重试。"}
              {event.event === "runtimeUnavailable" ? <button type="button" onClick={() => {
                void railwatchApi.command("retryRuntime").catch(() => undefined);
              }}>重试运行时</button> : null}</span>,
            placement: "topRight",
            duration: 0,
          });
          break;
        case "runtimeRestarted":
          state.resetRehearsalProgress();
          notification.destroy("runtime-state");
          void loadTripRef.current();
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

  const showThemedDialog = useCallback<ThemedDialog>(
    ({ title, content, okText, cancelText, kind, danger }) =>
      new Promise<boolean>((resolve) => {
        modal.confirm({
          title,
          content: <div className="dialog-copy">{content}</div>,
          icon: kind === "info" ? <Info className="dialog-symbol" size={20} /> : danger
            ? <TriangleAlert className="dialog-symbol danger" size={20} /> : <CircleHelp className="dialog-symbol" size={20} />,
          okText,
          cancelText,
          centered: true,
          className: "railwatch-dialog",
          width: 480,
          zIndex: 1200,
          okCancel: kind !== "info",
          okButtonProps: { danger, style: danger ? { color: "var(--surface)" } : undefined },
          focusable: { autoFocusButton: kind === "info" ? "ok" : "cancel" },
          mask: { closable: false },
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      }),
    [modal],
  );

  const confirm = useCallback(
    (title: string, content: string) =>
      showThemedDialog({ title, content, okText: "确认", cancelText: "取消" }),
    [showThemedDialog],
  );

  useConfirmationBridge(showThemedDialog);
  useUpdateReadyPrompt(showThemedDialog);

  const runCommand = useCallback(
    async <T,>(
      command: string,
      payload: Record<string, unknown> = {},
      successText?: string,
    ): Promise<T | undefined> => {
      if (clearingDataRef.current) return undefined;
      if (command === "clearLocalData") {
        clearingDataRef.current = true;
        await draftWriteChain.current;
      }
      setBusy(command);
      const finishClear = async (value: unknown) => {
        if (command !== "clearLocalData" || !value || typeof value !== "object" || !("cleared" in value) || !value.cleared) return;
        railwatchApi.stageDraft(null);
        try { localStorage.removeItem("railwatch.theme"); } catch { /* The preferences file is authoritative. */ }
        const result = value as { cleanup_pending?: boolean; warning?: string; remaining_paths?: string[] };
        await showThemedDialog({ kind: "info", title: result.cleanup_pending ? "部分旧文件尚未清除" : "本地数据已清除",
          content: result.cleanup_pending ? `${result.warning}\n旧文件位置：\n${(result.remaining_paths ?? []).join("\n")}`
            : `${result.warning ? `${result.warning}
` : ""}应用将重新加载，请重新检查运行环境并登录。`, okText: "重新加载", cancelText: "关闭" });
        window.location.reload();
      };
      const queryRequestId = command === "analyzeQuery" ? crypto.randomUUID() : null;
      if (queryRequestId) {
        railwatchStore.getState().beginManualQuery(queryRequestId, (payload.config ?? railwatchStore.getState().config) as RailWatchConfig);
        payload = { ...payload, request_id: queryRequestId };
      }
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
          await finishClear(confirmedResult);
          return confirmedResult;
        }
        if (isStatusPayload(result)) {
          railwatchStore.getState().applyState(result);
        }
        if (command === "saveConfig" && result) {
          const saved = structuredClone((payload.config ?? railwatchStore.getState().config) as RailWatchConfig);
          railwatchStore.getState().markConfigSaved(saved, Date.now() / 1000);
          const revision = ++draftRevisionBase.current;
          railwatchApi.stageDraft({ config: saved, revision });
          draftWriteChain.current = draftWriteChain.current.then(async () => {
            try {
              const draft = await railwatchApi.command<TripDraft>("saveTripDraft", { config: saved, revision });
              railwatchStore.getState().markDraftSaved(railwatchStore.getState().editRevision, draft.revision, draft.saved_at);
            } catch (error) {
              railwatchStore.getState().markDraftError(railwatchStore.getState().editRevision,
                error instanceof Error ? error.message : String(error));
            }
          });
        }
        if (successText) {
          message.success(successText);
        }
        await finishClear(result);
        return result as T;
      } catch (error) {
        if (command === "saveConfig") railwatchStore.getState().markConfigSaveError(error instanceof Error ? error.message : String(error));
        if (queryRequestId) railwatchStore.getState().endManualQuery(queryRequestId, error instanceof Error ? error.message : String(error));
        const errorText = error instanceof Error ? error.message : String(error);
        message.error(command === "clearLocalData" ? errorText.replace(/^Error invoking remote method ['"]railwatch:command['"]:\s*(?:Error:\s*)?/, "") : errorText);
        return undefined;
      } finally {
        if (queryRequestId && railwatchStore.getState().manualQueryPending) railwatchStore.getState().endManualQuery(queryRequestId);
        setBusy(null);
        if (command === "clearLocalData") clearingDataRef.current = false;
      }
    },
    [confirm, message, showThemedDialog],
  );

  const saveTheme = async (
    mode: Parameters<typeof appearance.saveTheme>[0],
    origin?: Parameters<typeof appearance.saveTheme>[1],
  ) => {
    try {
      await appearance.saveTheme(mode, origin);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "主题保存失败，请重试。",
      );
    }
  };

  const exportLog = useCallback(async () => {
    if (exportingRef.current) return;
    exportingRef.current = true;
    const defaultPath = runtime.data_dir
      ? `${runtime.data_dir}/railwatch-events.txt`
      : undefined;
    try {
      await exportEventLog(defaultPath, runCommand, choosePath);
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      exportingRef.current = false;
    }
  }, [message, runCommand, runtime.data_dir, choosePath]);

  const loadTrip = useCallback((): Promise<void> => {
    if (railwatchStore.getState().tripInitialized) return Promise.resolve();
    tripLoadRef.current ??= (async () => {
      try {
        const trip = await runCommand<TripState>("loadTripState");
        if (!trip || railwatchStore.getState().tripInitialized) return;
        const draft = trip.draft.status === "available" &&
          (trip.draft.draft.saved_at <= (trip.saved_at ?? 0) ||
           tripFingerprint({ ...trip.saved_config, ...trip.draft.draft.config }) === tripFingerprint(trip.saved_config))
          ? { status: "missing" as const, draft: null, warning: null } : trip.draft;
        railwatchStore.getState().initializeTrip(trip.saved_config, trip.saved_at, draft);
        draftRevisionBase.current = trip.draft.status === "available" ? trip.draft.draft.revision : 0;
      } finally {
        tripLoadRef.current = null;
      }
    })();
    return tripLoadRef.current;
  }, [runCommand]);
  loadTripRef.current = loadTrip;

  useEffect(() => {
    if (activePage === "行程设置" && !tripInitialized) void loadTrip();
  }, [activePage, tripInitialized, loadTrip]);

  useEffect(() => {
    const unsubscribe = railwatchApi.onEvent(applyEvent);
    void (async () => {
      const runtimeInfo = await runCommand<RuntimeInfo>("getRuntimeInfo");
      if (runtimeInfo) {
        railwatchStore.getState().applyRuntimeInfo(runtimeInfo);
      }
      await loadTrip();
    })();

    const refreshRuntime = window.setInterval(() => {
      if (clearingDataRef.current) return;
      void railwatchApi
        .command<RuntimeInfo>("getRuntimeInfo")
        .then((runtimeInfo) => {
          if (runtimeInfo) {
            railwatchStore.getState().applyRuntimeMetadata(runtimeInfo);
          }
        })
        .catch(() => undefined);
    }, 30000);

    return () => {
      window.clearInterval(refreshRuntime);
      unsubscribe();
    };
  }, [applyEvent, loadTrip, runCommand]);

  useEffect(() => {
    if (!tripInitialized || editRevision === 0 || clearingDataRef.current) return;
    const state = railwatchStore.getState();
    const snapshot = structuredClone(state.config);
    const revision = ++draftRevisionBase.current;
    railwatchApi.stageDraft({ config: snapshot, revision });
    const timer = window.setTimeout(() => {
      draftWriteChain.current = draftWriteChain.current.then(async () => {
        if (clearingDataRef.current) return;
        const current = railwatchStore.getState();
        current.markDraftSaving(editRevision);
        try {
          const saved = await railwatchApi.command<TripDraft>("saveTripDraft", { config: snapshot, revision });
          railwatchStore.getState().markDraftSaved(editRevision, saved.revision, saved.saved_at);
        } catch (error) {
          railwatchStore.getState().markDraftError(editRevision, error instanceof Error ? error.message : String(error));
        }
      });
    }, 650);
    return () => window.clearTimeout(timer);
  }, [editRevision, tripInitialized, savedConfig]);

  const content = useMemo(() => {
    if (activePage === "行程设置") {
      return (
        <TripSetupPage busy={busy} confirm={confirm} runCommand={runCommand} />
      );
    }
    if (activePage === "购票监控") {
      return <MonitorPage busy={busy} runCommand={runCommand} />;
    }
    if (activePage === "订单中心") {
      return <OrderCenterPage busy={busy} runCommand={runCommand} />;
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
        onChange: (mode, origin) => void saveTheme(mode, origin),
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
      {exportDialog}
    </ThemeContext.Provider>
  );
}
