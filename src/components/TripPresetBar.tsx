import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Button, Input } from "antd";
import { Bookmark, BookmarkPlus, Check, ChevronDown, Save, X } from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { railwatchStore } from "../store/railwatchStore";
import type { RailWatchConfig, TripPreset, TripPresetsResult } from "../types";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";

export function TripPresetBar({ config, confirm, runCommand, onApply, disabled }: {
  config: RailWatchConfig;
  confirm: ConfirmDialog;
  runCommand: CommandRunner;
  onApply: (preset: TripPreset) => void;
  disabled: boolean;
}) {
  const activeId = useRailWatchStore(state => state.activeTripPresetId);
  const tripBundleImporting = useRailWatchStore(state => state.tripBundleImporting);
  const tripPresetsVersion = useRailWatchStore(state => state.tripPresetsVersion);
  const [items, setItems] = useState<TripPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [writing, setWriting] = useState(false);
  const [name, setName] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const dialogId = useId();
  const menu = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const namedSaveButton = useRef<HTMLButtonElement>(null);
  const confirmingDelete = useRef(false);
  const restoreTriggerFocus = useRef(false);
  const loadGeneration = useRef(0);
  const loadedVersion = useRef(tripPresetsVersion);
  const active = items.find(item => item.id === activeId);
  const triggerLabel = active ? `方案：${active.name}` : items.length ? `行程方案 (${items.length})` : "行程方案";
  const locked = loading || writing || tripBundleImporting;
  const trimmedName = name?.trim() ?? "";
  const nameLength = [...trimmedName].length;
  const validName = nameLength > 0 && nameLength <= 40 && !/\p{Cc}/u.test(name ?? "");

  useEffect(() => {
    if (tripBundleImporting) {
      // Drop any in-flight read started before import completes and lock preset actions.
      loadGeneration.current += 1;
      setLoading(true);
      return;
    }
    if (loadedVersion.current !== tripPresetsVersion) {
      loadedVersion.current = tripPresetsVersion;
      setItems([]);
    }
    let mounted = true;
    const generation = ++loadGeneration.current;
    setLoading(true);
    void runCommand<TripPresetsResult>("loadTripPresets").then(result => {
      if (!mounted || loadGeneration.current !== generation) return;
      if (Array.isArray(result?.items)) setItems(result.items);
      setLoading(false);
    }, () => {
      if (!mounted || loadGeneration.current !== generation) return;
      setLoading(false);
    });
    return () => { mounted = false; };
  }, [runCommand, tripPresetsVersion, tripBundleImporting]);

  useLayoutEffect(() => {
    if (!open) {
      if (restoreTriggerFocus.current) trigger.current?.focus({ preventScroll: true });
      restoreTriggerFocus.current = false;
      return;
    }
    if (!dialog.current || !menu.current) return;
    const panel = dialog.current;
    const anchor = menu.current;
    const position = () => {
      const bounds = anchor.getBoundingClientRect();
      const top = bounds.bottom + 6;
      // Keep the panel inside the viewport while its list takes the available height.
      panel.style.top = `${top}px`;
      panel.style.left = `${Math.max(16, Math.min(bounds.right, window.innerWidth - 16) - panel.offsetWidth)}px`;
      panel.style.maxHeight = `${Math.max(0, window.innerHeight - top - 16)}px`;
    };
    position();
    panel.focus({ preventScroll: true });
    const observer = new ResizeObserver(position);
    observer.observe(anchor);
    const header = anchor.closest(".trip-setup-head");
    if (header) observer.observe(header);
    window.addEventListener("resize", position);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", position);
    };
  }, [open]);

  const closeMenu = useCallback((restoreFocus: boolean) => {
    restoreTriggerFocus.current = restoreFocus;
    setOpen(false);
    setName(null);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!confirmingDelete.current && event.target instanceof Node && !menu.current?.contains(event.target)) {
        closeMenu(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing || confirmingDelete.current) return;
      event.preventDefault();
      event.stopPropagation();
      closeMenu(true);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, closeMenu]);

  const closeNaming = () => {
    setName(null);
    requestAnimationFrame(() => namedSaveButton.current?.focus({ preventScroll: true }));
  };

  const beginNamedSave = () => {
    const suggested = `${config.from_station_cn.trim()}→${config.to_station_cn.trim()} ${config.date.slice(5)}`.trim();
    setName([...suggested].slice(0, 40).join(""));
  };

  const savePreset = async (presetName: string, id?: string) => {
    const { editRevision, tripPresetsVersion } = railwatchStore.getState();
    setWriting(true);
    try {
      const result = await runCommand<TripPresetsResult>("saveTripPreset", {
        name: presetName, config, ...(id ? { preset_id: id } : {}),
      }, id ? "行程方案已更新" : "行程方案已保存");
      if (!Array.isArray(result?.items)) return;
      const latest = railwatchStore.getState();
      if (latest.tripBundleImporting || latest.tripPresetsVersion !== tripPresetsVersion) return;
      setItems(result.items);
      if (!id) closeNaming();
      if (result.saved_id && latest.editRevision === editRevision) {
        latest.setActiveTripPreset(result.saved_id);
      }
    } finally {
      setWriting(false);
    }
  };

  const deletePreset = async (preset: TripPreset) => {
    const { tripPresetsVersion } = railwatchStore.getState();
    setWriting(true);
    confirmingDelete.current = true;
    try {
      if (!await confirm("删除行程方案", `确定删除「${preset.name}」？`)) return;
      confirmingDelete.current = false;
      const beforeDelete = railwatchStore.getState();
      if (beforeDelete.tripBundleImporting || beforeDelete.tripPresetsVersion !== tripPresetsVersion) return;
      const result = await runCommand<TripPresetsResult>("deleteTripPreset", { preset_id: preset.id }, "行程方案已删除");
      if (!Array.isArray(result?.items)) return;
      const latest = railwatchStore.getState();
      if (latest.tripBundleImporting || latest.tripPresetsVersion !== tripPresetsVersion) return;
      setItems(result.items);
      if (latest.activeTripPresetId === preset.id) {
        latest.setActiveTripPreset(null);
      }
    } finally {
      confirmingDelete.current = false;
      setWriting(false);
    }
  };

  return <div className="trip-preset-menu" ref={menu}>
    <Button ref={trigger} className={active ? "trip-preset-trigger is-active" : "trip-preset-trigger"}
      disabled={disabled} icon={<Bookmark size={15} aria-hidden="true" />}
      aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? dialogId : undefined}
      title={active ? triggerLabel : undefined}
      onClick={() => open ? closeMenu(true) : setOpen(true)}>
      <span className="trip-preset-trigger-label">{triggerLabel}</span>
      <ChevronDown size={14} aria-hidden="true" />
    </Button>
    {open && <div id={dialogId} ref={dialog} className="trip-preset-dialog" role="dialog" aria-label="行程方案" tabIndex={-1}>
      <header className="trip-preset-header">
        <h3>行程方案</h3>
        <span className="trip-preset-count">{items.length}/20</span>
      </header>
      {items.length > 0 ? <ul className="trip-preset-list">
        {items.map(preset => {
          const selected = preset.id === activeId;
          const { from_station_cn, to_station_cn, date } = preset.config;
          const route = [from_station_cn, to_station_cn].filter(Boolean).join(" → ");
          const subtitle = [route, date?.slice(5)].filter(Boolean).join(" · ");
          const subtitleId = `${dialogId}-route-${preset.id}`;
          return <li key={preset.id} className={selected ? "trip-preset-row is-active" : "trip-preset-row"}>
            <button type="button" className="trip-preset-load" aria-label={preset.name} aria-pressed={selected}
              aria-describedby={subtitle ? subtitleId : undefined} disabled={locked}
              onClick={() => { onApply(preset); closeMenu(true); }}>
              <span className="trip-preset-row-text">
                <span className="trip-preset-name">{preset.name}</span>
                {subtitle && <small id={subtitleId} className="trip-preset-subtitle">{subtitle}</small>}
              </span>
              {selected && <Check size={14} aria-hidden="true" />}
            </button>
            <button type="button" className="trip-preset-delete" aria-label={`删除方案 ${preset.name}`}
              disabled={locked} onClick={() => void deletePreset(preset)}><X size={13} aria-hidden="true" /></button>
          </li>;
        })}
      </ul> : <p className="trip-preset-empty">
        {loading ? (tripBundleImporting ? "正在导入备份…" : "正在加载行程方案…") : "暂无已保存方案，可将当前配置存为方案以便快速切换。"}
      </p>}
      <footer className="trip-preset-footer">
        {name === null ? <div className="trip-preset-actions">
          {active && <Button size="small" disabled={locked} icon={<Save size={13} aria-hidden="true" />}
            onClick={() => void savePreset(active.name, active.id)}>更新当前方案</Button>}
          <Button ref={namedSaveButton} size="small" disabled={locked}
            icon={<BookmarkPlus size={13} aria-hidden="true" />} onClick={beginNamedSave}>
            {active ? "另存为新方案" : "存为方案"}
          </Button>
        </div> : <form className="trip-preset-form" onSubmit={event => {
          event.preventDefault();
          if (validName && !locked) void savePreset(trimmedName);
        }}>
          <div className="trip-preset-name-field">
            <Input aria-label="方案名称" aria-describedby={`${dialogId}-name-count`} placeholder="方案名称"
              value={name} autoFocus disabled={writing} onChange={event => setName(event.target.value)}
              onKeyDown={event => {
                if (event.key !== "Escape" || event.nativeEvent.isComposing) return;
                event.preventDefault();
                event.stopPropagation();
                closeNaming();
              }} />
            <small id={`${dialogId}-name-count`} className="trip-preset-name-count">{nameLength}/40</small>
          </div>
          <Button size="small" htmlType="submit" type="primary" disabled={!validName || locked}>保存方案</Button>
          <Button size="small" htmlType="button" disabled={writing} onClick={closeNaming}>取消</Button>
          {!validName && <small className="trip-date-hint is-warning">请输入 1–40 个字符的方案名称。</small>}
        </form>}
      </footer>
    </div>}
  </div>;
}
