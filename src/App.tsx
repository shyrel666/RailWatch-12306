import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { App as AntApp, Button, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { CircleHelp, Info, TriangleAlert } from "lucide-react";
import { useExportLogDialog } from "./components/ExportLogDialog";
import { useThemePreference } from "./lib/useThemePreference";
import { finishStartupSplash } from "./lib/startupSplash";
import { ThemeContext } from "./components/ThemeControl";
import { AboutPage } from "./components/AboutPage";
import { DashboardPage } from "./components/DashboardPage";
import { EventPanel } from "./components/EventPanel";
import { MonitorPage } from "./components/MonitorPage";
import { OrderCenterPage } from "./components/OrderCenterPage";
import { RunReviews } from "./components/RunReviews";
import { SettingsPage } from "./components/SettingsPage";
import { EnvironmentProgressDialog } from "./components/EnvironmentProgressDialog";
import { ShellLayout } from "./components/Shell";
import { TripSetupPage } from "./components/TripSetupPage";
import { railwatchApi } from "./lib/railwatchApi";
import { exportEventLog } from "./lib/exportEventLog";
import { isRosettaMacApp, resolveNativeArm64DownloadUrl } from "./lib/updateDisplay";
import {
  useConfirmationBridge,
  type ThemedDialog,
} from "./lib/useThemedDialogs";
import { railwatchStore, tripFingerprint } from "./store/railwatchStore";
import { useRailWatchStore } from "./store/useRailWatchStore";
import type {
  BridgeEvent,
  ConfirmationRequest,
  EnvironmentProgress,
  HumanActionPayload,
  LogEntry,
  MonitorTickPayload,
  QueryResultRow,
  RailWatchConfig,
  RailWatchPreferences,
  RailWatchStatus,
  RuntimeInfo,
  RuntimeLabelsPatch,
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

function draftErrorText(error: unknown): string {
  return (error instanceof Error ? error.message : String(error))
    .replace(/^Error invoking remote method ['"]railwatch:command['"]:\s*(?:Error:\s*)?/, "");
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

type DraftSnapshot = {
  config: RailWatchConfig;
  revision: number;
  editRevision: number;
};

function RailWatchAppContent({ appearance }: RailWatchAppContentProps) {
  const runtime = useRailWatchStore((state) => state.runtime);
  const status = useRailWatchStore((state) => state.status);
  const environmentProgress = useRailWatchStore(state => state.environmentProgress);
  const environmentProgressVisible = useRailWatchStore(state => state.environmentProgressVisible);
  const setEnvironmentProgressVisible = useRailWatchStore(state => state.setEnvironmentProgressVisible);
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
  const [pendingCommands, setPendingCommands] = useState<{ command: string }[]>([]);
  const environmentOperationRef = useRef(false);
  // Startup and other commands can finish while Chrome is still downloading.
  const busy = pendingCommands.find(pending => pending.command === "checkEnvironment" || pending.command === "downloadChromeDriver")?.command
    ?? pendingCommands.at(-1)?.command ?? null;
  const [startupReady, setStartupReady] = useState(false);
  useEffect(() => {
    if (startupReady && appearance.ready) finishStartupSplash();
  }, [startupReady, appearance.ready]);
  const [autoCheckEnvironment, setAutoCheckEnvironment] = useState(false);
  const prepareEnvironmentCheck = useCallback(() => setAutoCheckEnvironment(true), []);
  const finishEnvironmentPreparation = useCallback(() => setAutoCheckEnvironment(false), []);
  useEffect(() => {
    if (activePage !== "系统设置") setAutoCheckEnvironment(false);
  }, [activePage]);
  const editRevision = useRailWatchStore(state => state.editRevision);
  const tripInitialized = useRailWatchStore(state => state.tripInitialized);
  const savedConfig = useRailWatchStore(state => state.savedConfig);
  const draftRevisionBase = useRef(0);
  const draftWriteChain = useRef<Promise<void>>(Promise.resolve());
  const latestDraft = useRef<DraftSnapshot | null>(null);
  const clearingDataRef = useRef(false);
  const tripLoadRef = useRef<Promise<void> | null>(null);
  const loadTripRef = useRef<() => Promise<void>>(async () => undefined);

  // The ref resets when this component remounts while the store (and the disk
  // draft) keep their revision, so always allocate above both.
  const nextDraftRevision = useCallback(() => {
    draftRevisionBase.current = Math.max(draftRevisionBase.current, railwatchStore.getState().draftRevision) + 1;
    return draftRevisionBase.current;
  }, []);

  const stageCurrentDraft = useCallback(() => {
    const state = railwatchStore.getState();
    const snapshot = { config: structuredClone(state.config), revision: nextDraftRevision(), editRevision: state.editRevision };
    latestDraft.current = snapshot;
    railwatchApi.stageDraft({ config: snapshot.config, revision: snapshot.revision });
    return snapshot;
  }, [nextDraftRevision]);

  const writeDraft = useCallback(async (queued: DraftSnapshot) => {
    if (clearingDataRef.current || queued !== latestDraft.current) return;
    let snapshot = queued;
    try {
      railwatchStore.getState().markDraftSaving(snapshot.editRevision);
      let saved: TripDraft;
      try {
        saved = await railwatchApi.command<TripDraft>("saveTripDraft", { config: snapshot.config, revision: snapshot.revision });
      } catch (error) {
        const current = error instanceof Error ? /草稿修订号已过期（当前为 (\d+)）/.exec(error.message) : null;
        if (!current) throw error;
        // Edits may have arrived while this write was pending. Rebase the latest
        // config for both the retry and Electron's exit flush, superseding queued snapshots.
        draftRevisionBase.current = Math.max(draftRevisionBase.current, Number(current[1]));
        snapshot = stageCurrentDraft();
        railwatchStore.getState().markDraftSaving(snapshot.editRevision);
        saved = await railwatchApi.command<TripDraft>("saveTripDraft", { config: snapshot.config, revision: snapshot.revision });
      }
      railwatchStore.getState().markDraftSaved(snapshot.editRevision, saved.revision, saved.saved_at);
    } catch (error) {
      railwatchStore.getState().markDraftError(snapshot.editRevision, draftErrorText(error));
    }
  }, [stageCurrentDraft]);

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
        case "environmentProgress":
          state.applyEnvironmentProgress(event.payload as EnvironmentProgress);
          break;
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
          // Notices (a lapsed login, a sale reminder) stay until closed, without the urgent sound loop.
          const lasting = notifyPayload.priority === "urgent" || notifyPayload.priority === "notice";
          const notifyApi = lasting ? notification.warning : notification.success;
          notifyApi({
            // Its own slot: a notice must not replace an unclosed urgent alert and its onClose.
            key: notifyPayload.priority === "notice" ? "railwatch-notice" : "railwatch-notify",
            message: notifyPayload.title,
            description: notifyPayload.message,
            placement: "topRight",
            duration: lasting ? 0 : 4.5,
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
          finishStartupSplash();
          if (state.environmentProgress?.status === "running") {
            state.finishEnvironmentOperation(state.environmentProgress.operation, "运行时中断，环境准备未完成，请重试。");
          }
          state.resetRehearsalProgress();
          state.applyState({
            ...state.status,
            monitoring: false,
            task: undefined,
            phase: "error",
            risk_level: "critical",
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
            .command<RuntimeInfo>("getRuntimeInfo", { probe: false })
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
          state.applyRuntimeLabels(event.payload as RuntimeLabelsPatch);
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

  const runCommand = useCallback(
    async <T,>(
      command: string,
      payload: Record<string, unknown> = {},
      successText?: string,
    ): Promise<T | undefined> => {
      if (clearingDataRef.current) return undefined;
      const environmentOperation = command === "checkEnvironment" || command === "downloadChromeDriver" ? command : null;
      if (environmentOperation) {
        if (environmentOperationRef.current) {
          railwatchStore.getState().setEnvironmentProgressVisible(true);
          return undefined;
        }
        environmentOperationRef.current = true;
        message.destroy("environment-check");
        message.destroy("environment-download");
        railwatchStore.getState().beginEnvironmentOperation(environmentOperation);
      }
      if (command === "clearLocalData") {
        clearingDataRef.current = true;
        await draftWriteChain.current;
      }
      const pendingCommand = { command };
      setPendingCommands(current => [...current, pendingCommand]);
      const finishClear = async (value: unknown) => {
        if (command !== "clearLocalData" || !value || typeof value !== "object" || !("cleared" in value) || !value.cleared) return;
        latestDraft.current = null;
        railwatchApi.stageDraft(null);
        try {
          for (let index = localStorage.length - 1; index >= 0; index -= 1) {
            const storageKey = localStorage.key(index);
            if (storageKey?.startsWith("railwatch.")) localStorage.removeItem(storageKey);
          }
          localStorage.removeItem("railwatch.theme");
          localStorage.removeItem("railwatch.sidebarCollapsed");
        } catch {
          /* The preferences file is authoritative. */
        }
        const result = value as { cleanup_pending?: boolean; warning?: string; remaining_paths?: string[] };
        await showThemedDialog({ kind: "info", title: result.cleanup_pending ? "部分旧文件尚未清除" : "本地数据已清除",
          content: result.cleanup_pending ? `${result.warning}${result.remaining_paths?.length ? `\n旧文件位置：\n${result.remaining_paths.join("\n")}` : ""}`
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
          if (environmentOperation) railwatchStore.getState().finishEnvironmentOperation(environmentOperation, "操作未完成，请重试。");
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
          if (environmentOperation) {
            railwatchStore.getState().finishEnvironmentOperation(environmentOperation,
              result.phase === "error" || result.error_message || !result.environment_ready
                ? result.error_message || result.status_message || "环境检查未完成，请重试。" : undefined);
          }
          if (
            command === "checkEnvironment" &&
            result.environment_ready &&
            result.phase !== "error" &&
            !result.error_message
          ) {
            message.success({
              key: "environment-check",
              content: "环境检查完成，运行环境已就绪。",
              className: "railwatch-environment-success",
              duration: 3,
            });
          }
        }
        if (environmentOperation) {
          railwatchStore.getState().finishEnvironmentOperation(environmentOperation);
          const completed = railwatchStore.getState();
          if (!completed.environmentProgressVisible && completed.environmentProgress) {
            const key = environmentOperation === "checkEnvironment" ? "environment-check" : "environment-download";
            if (completed.environmentProgress.status === "error") message.error({ key, content: completed.environmentProgress.message });
            else if (environmentOperation === "downloadChromeDriver") message.success({ key, content: completed.environmentProgress.message });
          }
        }
        if (command === "saveConfig" && result) {
          const saved = structuredClone((payload.config ?? railwatchStore.getState().config) as RailWatchConfig);
          railwatchStore.getState().markConfigSaved(saved, Date.now() / 1000);
          const snapshot = stageCurrentDraft();
          draftWriteChain.current = draftWriteChain.current.then(() => writeDraft(snapshot));
        }
        if (successText) {
          message.success(successText);
        }
        await finishClear(result);
        return result as T;
      } catch (error) {
        if (command === "getRuntimeInfo" || command === "loadTripState") finishStartupSplash();
        if (command === "saveConfig") railwatchStore.getState().markConfigSaveError(error instanceof Error ? error.message : String(error));
        if (queryRequestId) railwatchStore.getState().endManualQuery(queryRequestId, error instanceof Error ? error.message : String(error));
        const errorText = error instanceof Error ? error.message : String(error);
        if (environmentOperation) railwatchStore.getState().finishEnvironmentOperation(environmentOperation, errorText);
        message.error(environmentOperation ? {
          key: environmentOperation === "checkEnvironment" ? "environment-check" : "environment-download", content: errorText,
        } : command === "clearLocalData" ? errorText.replace(/^Error invoking remote method ['"]railwatch:command['"]:\s*(?:Error:\s*)?/, "") : errorText);
        return undefined;
      } finally {
        if (queryRequestId && railwatchStore.getState().manualQueryPending) railwatchStore.getState().endManualQuery(queryRequestId);
        setPendingCommands(current => current.filter(pending => pending !== pendingCommand));
        if (environmentOperation) environmentOperationRef.current = false;
        if (command === "clearLocalData") clearingDataRef.current = false;
      }
    },
    [confirm, message, showThemedDialog, stageCurrentDraft, writeDraft],
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
    let alive = true;
    const unsubscribe = railwatchApi.onEvent(applyEvent);
    void (async () => {
      try {
        const runtimeTask = runCommand<RuntimeInfo>("getRuntimeInfo", { probe: false }).then((runtimeInfo) => {
          if (alive && runtimeInfo) {
            railwatchStore.getState().applyRuntimeInfo(runtimeInfo);
          }
        });
        await Promise.all([runtimeTask, loadTrip()]);
      } finally {
        if (alive) setStartupReady(true);
      }
    })();

    const refreshRuntimeInfo = () => {
      if (clearingDataRef.current || document.visibilityState === "hidden") return;
      void railwatchApi
        .command<RuntimeInfo>("getRuntimeInfo", { probe: false })
        .then((runtimeInfo) => {
          if (runtimeInfo) {
            railwatchStore.getState().applyRuntimeMetadata(runtimeInfo);
          }
        })
        .catch(() => undefined);
    };

    const refreshRuntime = window.setInterval(refreshRuntimeInfo, 180000);
    document.addEventListener("visibilitychange", refreshRuntimeInfo);

    return () => {
      alive = false;
      window.clearInterval(refreshRuntime);
      document.removeEventListener("visibilitychange", refreshRuntimeInfo);
      unsubscribe();
    };
  }, [applyEvent, loadTrip, runCommand]);

  useEffect(() => {
    let alive = true;
    void railwatchApi
      .getAppInfo()
      .then((info) => {
        if (!alive || !isRosettaMacApp(info)) return;
        const noticeKey = "railwatch-rosetta-translation";
        notification.warning({
          key: noticeKey,
          title: "当前运行的是 Intel (x64) 版本",
          description:
            "检测到这台 Apple Silicon Mac 正在通过 Rosetta 2 转译运行，建议改用 Apple Silicon (arm64) 原生版安装包以获得更佳性能与续航。",
          placement: "topRight",
          duration: 0,
          actions: (
            <Button
              size="small"
              type="primary"
              onClick={() => {
                void railwatchApi
                  .getUpdateState()
                  .catch(() => null)
                  .then((latestState) => railwatchApi.openExternal(resolveNativeArm64DownloadUrl(latestState)))
                  .then((opened) => {
                    if (opened.ok) {
                      notification.destroy(noticeKey);
                    } else {
                      message.error(opened.error || "无法打开 Apple Silicon 原生版下载链接。");
                    }
                  })
                  .catch(() => {
                    message.error("无法打开 Apple Silicon 原生版下载链接。");
                  });
              }}
            >
              下载 Apple Silicon 原生版
            </Button>
          ),
        });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [message, notification]);

  useEffect(() => {
    if (!tripInitialized || editRevision === 0 || clearingDataRef.current) return;
    const snapshot = stageCurrentDraft();
    const timer = window.setTimeout(() => {
      draftWriteChain.current = draftWriteChain.current.then(() => writeDraft(snapshot));
    }, 650);
    return () => window.clearTimeout(timer);
  }, [editRevision, tripInitialized, savedConfig, stageCurrentDraft, writeDraft]);

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
    if (activePage === "运行复盘") {
      return <RunReviews />;
    }
    if (activePage === "系统设置") {
      return <SettingsPage busy={busy} runCommand={runCommand}
        autoCheckEnvironment={autoCheckEnvironment}
        onEnvironmentCheckStart={finishEnvironmentPreparation} />;
    }
    if (activePage === "关于") {
      return <AboutPage />;
    }
    return <DashboardPage onCheckEnvironment={prepareEnvironmentCheck} />;
  }, [activePage, busy, confirm, runCommand, autoCheckEnvironment, finishEnvironmentPreparation, prepareEnvironmentCheck]);

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
      <EnvironmentProgressDialog
        progress={environmentProgress}
        open={environmentProgressVisible}
        onClose={() => setEnvironmentProgressVisible(false)}
      />
      {exportDialog}
    </ThemeContext.Provider>
  );
}
